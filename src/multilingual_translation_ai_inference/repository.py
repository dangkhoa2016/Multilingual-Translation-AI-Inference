"""Transactional job persistence, claim tokens and result aggregation."""
import hashlib
import json
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from .admission import enforce_pending_limits
from .database import Job, JobRun, TranslationResult, utcnow, valid_token_count
from .gpu_budget import reserve_estimated_gpu_budget
from .quotas import QuotaExceeded, apply_submission_quotas, consume_quota


class IdempotencyConflict(Exception):
    pass


class RetryNotAllowed(Exception):
    pass


def payload_hash(kind: str, payload: dict, model_keys: list[str]) -> str:
    canonical = json.dumps({"kind": kind, "request": payload, "models": model_keys},
                           sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class JobRepository:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def submit(self, *, owner: str, idempotency_key: str | None, kind: str,
               payload: dict, model_keys: list[str], max_jobs_per_minute: int = 10,
               max_jobs_per_day: int = 100, max_model_runs_per_day: int = 200,
               estimated_gpu_microusd_per_run: int = 0,
               max_estimated_gpu_microusd_per_day: int = 0,
               max_pending_jobs_per_owner: int = 20,
               max_pending_runs_per_model: int = 20,
               dispatch_mode: str = "record-only") -> str:
        if dispatch_mode not in {"record-only", "inline-mock", "modal-cpu-mock", "modal-gpu"}:
            raise ValueError("Unsupported job dispatch mode")
        digest = payload_hash(kind, payload, model_keys)
        with self.session_factory() as session:
            if idempotency_key:
                previous = session.scalar(select(Job).where(
                    Job.request_owner == owner, Job.idempotency_key == idempotency_key))
                if previous:
                    if previous.request_hash != digest:
                        raise IdempotencyConflict("Key already used with a different request")
                    return previous.id
            try:
                apply_submission_quotas(
                    session, owner=owner, model_count=len(model_keys),
                    max_jobs_per_minute=max_jobs_per_minute,
                    max_jobs_per_day=max_jobs_per_day,
                    max_model_runs_per_day=max_model_runs_per_day,
                )
                reserve_estimated_gpu_budget(
                    session, owner=owner, model_count=len(model_keys),
                    microusd_per_run=estimated_gpu_microusd_per_run,
                    daily_microusd_limit=max_estimated_gpu_microusd_per_day,
                )
                enforce_pending_limits(session, owner=owner, model_keys=model_keys,
                    max_jobs=max_pending_jobs_per_owner, max_runs_per_model=max_pending_runs_per_model)
            except QuotaExceeded:
                # Another request with this key may have committed while our
                # earlier SELECT was waiting on the shared quota counter.
                session.rollback()
                if idempotency_key:
                    with self.session_factory() as check:
                        previous = check.scalar(select(Job).where(
                            Job.request_owner == owner, Job.idempotency_key == idempotency_key))
                        if previous is not None:
                            if previous.request_hash != digest:
                                raise IdempotencyConflict("Key already used with a different request")
                            return previous.id
                raise
            job = Job(request_owner=owner, idempotency_key=idempotency_key, request_hash=digest,
                      kind=kind, dispatch_mode=dispatch_mode, source_language=payload["source_language"],
                      target_language=payload["target_language"], input_text=payload["text"],
                      options_json=json.dumps(
                          {
                              **payload["options"],
                              **({"model_configs": payload["model_configs"]}
                                 if payload.get("model_configs") else {}),
                          },
                          sort_keys=True,
                      ))
            job.runs = [JobRun(model_key=key) for key in model_keys]
            session.add(job)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                if not idempotency_key:
                    raise
                # Another HTTP request may have inserted the same idempotency key.
                with self.session_factory() as check:
                    previous = check.scalar(select(Job).where(
                        Job.request_owner == owner, Job.idempotency_key == idempotency_key))
                    if previous:
                        if previous.request_hash != digest:
                            raise IdempotencyConflict("Key already used with a different request")
                        return previous.id
                raise
            return job.id

    def get(self, job_id: str, owner: str) -> Job | None:
        with self.session_factory() as session:
            return session.scalar(select(Job).where(Job.id == job_id, Job.request_owner == owner)
                                  .options(selectinload(Job.runs).selectinload(JobRun.result)))

    def consume_job_poll_quota(self, *, owner: str, limit: int) -> None:
        with self.session_factory.begin() as session:
            consume_quota(session, owner=owner, scope="job-polls-per-minute", amount=1,
                          limit=limit, window_seconds=60)

    def queued_run_ids(self, job_id: str, owner: str, *,
                       expected_mode: str | None = None) -> list[str]:
        with self.session_factory() as session:
            statement = select(JobRun.id).join(Job).where(
                Job.id == job_id, Job.request_owner == owner, JobRun.status == "queued")
            if expected_mode is not None:
                statement = statement.where(Job.dispatch_mode == expected_mode)
            return list(session.scalars(statement))

    def queued_recovery_candidates(self, *, mode: str, min_age_seconds: int = 30,
                                   limit: int = 20) -> list[tuple[str, str, str]]:
        """Oldest queued runs, fairly interleaved by model; never select uncertain runs.

        Candidate scans do not claim work. The compare-and-set update under the
        parent lock is authoritative when multiple schedulers compete.
        Legacy jobs with unknown dispatch intent cannot be recovered.
        """
        if mode not in {"modal-cpu-mock", "modal-gpu"}:
            raise ValueError("Recovery only supports Modal dispatch modes")
        if (type(limit) is not int or not 1 <= limit <= 100
                or type(min_age_seconds) is not int or min_age_seconds < 1):
            raise ValueError("Invalid recovery scan bounds")
        cutoff = utcnow() - timedelta(seconds=min_age_seconds)
        model_rank = func.row_number().over(
            partition_by=JobRun.model_key, order_by=(JobRun.created_at, JobRun.id))
        ranked = (select(
            JobRun.id.label("run_id"), Job.id.label("job_id"),
            Job.request_owner.label("owner"), JobRun.created_at.label("created_at"),
            model_rank.label("model_rank"),
        ).join(Job, Job.id == JobRun.job_id).where(
            JobRun.status == "queued", JobRun.created_at < cutoff,
            Job.dispatch_mode == mode,
        ).subquery())
        with self.session_factory() as session:
            rows = session.execute(select(
                ranked.c.run_id, ranked.c.job_id, ranked.c.owner
            ).order_by(ranked.c.model_rank, ranked.c.created_at, ranked.c.run_id)
                .limit(limit)).all()
            return [(row.run_id, row.job_id, row.owner) for row in rows]

    def claim_dispatch(self, run_id: str, *, expected_mode: str | None = None) -> str | None:
        token = str(uuid4())
        with self.session_factory.begin() as session:
            if not self._lock_parent_for_run(session, run_id):
                return None
            if expected_mode is not None:
                accepted_mode = session.scalar(select(Job.dispatch_mode).join(
                    JobRun, JobRun.job_id == Job.id).where(JobRun.id == run_id))
                if accepted_mode != expected_mode:
                    return None
            result = session.execute(update(JobRun).where(JobRun.id == run_id, JobRun.status == "queued")
                                     .values(status="dispatching", claim_token=token, dispatch_claimed_at=utcnow()))
            if result.rowcount != 1:
                return None
            return token

    def record_modal_call(self, run_id: str, token: str, modal_call_id: str | None) -> None:
        if not modal_call_id:
            return
        with self.session_factory.begin() as session:
            if not self._lock_parent_for_run(session, run_id):
                return
            session.execute(update(JobRun).where(JobRun.id == run_id, JobRun.claim_token == token)
                            .values(modal_call_id=modal_call_id))

    def mark_dispatch_uncertain(self, run_id: str, token: str) -> None:
        with self.session_factory.begin() as session:
            if not self._lock_parent_for_run(session, run_id):
                return
            session.execute(update(JobRun).where(JobRun.id == run_id,
                         JobRun.claim_token == token, JobRun.status == "dispatching")
                            .values(status="dispatch_uncertain", error_code="DISPATCH_UNKNOWN"))
            self._refresh_parent(session, run_id)

    def start_run(self, run_id: str, token: str) -> tuple[str, str, str, str, str] | None:
        with self.session_factory.begin() as session:
            if not self._lock_parent_for_run(session, run_id):
                return None
            updated = session.execute(update(JobRun).where(JobRun.id == run_id,
                JobRun.claim_token == token, JobRun.status.in_(["dispatching", "dispatch_uncertain"]))
                .values(status="running", started_at=utcnow(), error_code=None))
            if updated.rowcount != 1:
                return None
            run = session.get(JobRun, run_id)
            job = session.get(Job, run.job_id)
            self._refresh_parent(session, run_id)
            return job.source_language, job.target_language, job.input_text, job.options_json, run.model_key

    def finish_run(self, run_id: str, token: str, translation: str, *, mock: bool,
                   input_tokens: int | None = None,
                   output_tokens: int | None = None,
                   metrics: dict | None = None) -> bool:
        with self.session_factory.begin() as session:
            if not self._lock_parent_for_run(session, run_id):
                return False
            # Optional measurements must never discard a valid translation.
            try:
                metrics_json = json.dumps(metrics, allow_nan=False, sort_keys=True) if metrics else None
            except (TypeError, ValueError, OverflowError):
                metrics_json = None
            updated = session.execute(update(JobRun).where(
                JobRun.id == run_id, JobRun.claim_token == token,
                JobRun.status.in_(["running", "execution_uncertain"]))
                .values(status="completed", finished_at=utcnow(), error_code=None,
                        metrics_json=metrics_json))
            if updated.rowcount != 1:
                return False
            session.add(TranslationResult(
                run_id=run_id, translation_text=translation,
                is_mock_result=mock, input_tokens=valid_token_count(input_tokens),
                output_tokens=valid_token_count(output_tokens),
            ))
            self._refresh_parent(session, run_id)
            return True

    def get_run_model_key(self, run_id: str) -> str | None:
        with self.session_factory() as session:
            return session.scalar(select(JobRun.model_key).where(JobRun.id == run_id))

    def mark_execution_uncertain(self, run_id: str, token: str, code: str) -> bool:
        """Do not treat a lost GPU RPC acknowledgement as a confirmed failure."""
        with self.session_factory.begin() as session:
            if not self._lock_parent_for_run(session, run_id):
                return False
            changed = session.execute(update(JobRun).where(
                JobRun.id == run_id, JobRun.claim_token == token,
                JobRun.status == "running",
            ).values(status="execution_uncertain", error_code=code))
            if changed.rowcount == 1:
                session.expire_all()
                self._refresh_parent(session, run_id)
                return True
            return False

    def fail_run(self, run_id: str, token: str, code: str) -> None:
        with self.session_factory.begin() as session:
            if not self._lock_parent_for_run(session, run_id):
                return
            session.execute(update(JobRun).where(JobRun.id == run_id, JobRun.claim_token == token,
                     JobRun.status.in_(["running", "execution_uncertain", "dispatching", "dispatch_uncertain"]))
                            .values(status="failed", error_code=code, finished_at=utcnow()))
            self._refresh_parent(session, run_id)


    def retry_failed_run(self, *, job_id: str, owner: str, run_id: str,
                         expected_dispatch_mode: str,
                         max_attempts_per_model: int = 2,
                         max_model_runs_per_day: int = 200,
                         estimated_gpu_microusd_per_run: int = 0,
                         max_estimated_gpu_microusd_per_day: int = 0,
                         max_pending_jobs_per_owner: int = 20,
                         max_pending_runs_per_model: int = 20) -> str:
        """Explicit retry of a *definitely failed* run, never an uncertain execution.

        Lock the parent job row (PostgreSQL) so concurrent retry requests cannot
        both start another attempt. Quota is reserved in the same transaction.
        """
        with self.session_factory.begin() as session:
            job = session.scalar(select(Job).where(
                Job.id == job_id, Job.request_owner == owner).with_for_update())
            if job is None:
                raise RetryNotAllowed("Job not found")
            # Check stored intent while holding the parent lock, before
            # reserving quota or creating a retry attempt. Legacy NULL
            # and a changed dispatcher must fail closed.
            if (job.dispatch_mode is None
                    or job.dispatch_mode != expected_dispatch_mode):
                raise RetryNotAllowed(
                    "Retry dispatch mode does not match the original job intent"
                )
            original = session.scalar(select(JobRun).where(
                JobRun.id == run_id, JobRun.job_id == job_id))
            if original is None:
                raise RetryNotAllowed("Run not found in job")
            latest = session.scalar(select(JobRun).where(
                JobRun.job_id == job_id, JobRun.model_key == original.model_key)
                .order_by(JobRun.attempt_no.desc()).limit(1))
            if latest.id != original.id or original.status != "failed":
                raise RetryNotAllowed("Only the latest confirmed-failed run can be retried")
            if original.attempt_no >= max_attempts_per_model:
                raise RetryNotAllowed("Maximum attempts reached")
            apply_submission_quotas(
                session, owner=owner, model_count=1,
                max_jobs_per_minute=1, max_jobs_per_day=1,
                max_model_runs_per_day=max_model_runs_per_day, retry=True,
            )
            reserve_estimated_gpu_budget(
                session, owner=owner, model_count=1,
                microusd_per_run=estimated_gpu_microusd_per_run,
                daily_microusd_limit=max_estimated_gpu_microusd_per_day,
            )
            enforce_pending_limits(session, owner=owner, model_keys=[original.model_key],
                max_jobs=max_pending_jobs_per_owner, max_runs_per_model=max_pending_runs_per_model,
                existing_job_id=job_id)
            new_run = JobRun(job_id=job_id, model_key=original.model_key,
                             attempt_no=original.attempt_no + 1, status="queued")
            session.add(new_run)
            session.flush()
            job.status = "queued"
            job.finished_at = None
            return new_run.id

    def stale_counts(self, *, dispatch_age_seconds: int = 300,
                     running_age_seconds: int = 900) -> dict:
        """Read-only operator preview for old dispatching or running attempts."""
        if min(dispatch_age_seconds, running_age_seconds) < 1:
            raise ValueError("Ages must be positive")
        now = utcnow()
        with self.session_factory() as session:
            counts = {}
            for status, column, age in (
                ("dispatching", JobRun.dispatch_claimed_at, dispatch_age_seconds),
                ("running", JobRun.started_at, running_age_seconds),
            ):
                counts[status] = session.scalar(select(func.count(JobRun.id)).where(
                    JobRun.status == status, column.is_not(None),
                    column < now - timedelta(seconds=age),
                ))
            return counts

    def purge_old_terminal_jobs(self, *, retention_days: int = 90,
                                limit: int = 100, apply: bool = False) -> int:
        """Remove old terminal jobs + results only with explicit operator approval.

        Pending, running and uncertain jobs are never deleted. Does not delete
        quota counters; these roll out of their UTC bucket automatically.
        """
        if retention_days < 1 or limit < 1 or limit > 1000:
            raise ValueError("Retention days must be >=1; limit must be 1..1000")
        cutoff = utcnow() - timedelta(days=retention_days)
        with self.session_factory.begin() as session:
            eligible = list(session.scalars(select(Job.id).where(
                Job.status.in_(["completed", "failed", "partial_failed"]),
                Job.finished_at.is_not(None), Job.finished_at < cutoff,
            ).order_by(Job.finished_at, Job.id).limit(limit)
                .with_for_update(skip_locked=True)))
            if eligible and apply:
                session.execute(delete(Job).where(Job.id.in_(eligible)))
            return len(eligible)

    def reconcile_stale(self, *, dispatch_age_seconds: int = 300,
                        running_age_seconds: int = 900, limit: int = 100) -> dict:
        """Fail closed: mark stale work uncertain; NEVER spawn or retry it.

        Late workers may still complete with the original claim token. A timeout
        by itself never proves that external execution stopped.
        """
        if min(dispatch_age_seconds, running_age_seconds, limit) < 1:
            raise ValueError("Reconciliation ages and limit must be positive")
        now = utcnow()
        limits = [
            ("dispatching", "dispatch_uncertain", "DISPATCH_STALE_UNVERIFIED",
             JobRun.dispatch_claimed_at, now - timedelta(seconds=dispatch_age_seconds)),
            ("running", "execution_uncertain", "EXECUTION_STALE_UNVERIFIED",
             JobRun.started_at, now - timedelta(seconds=running_age_seconds)),
        ]
        changes = {"dispatch_uncertain": 0, "execution_uncertain": 0}
        for before, after, code, time_column, cutoff in limits:
            with self.session_factory() as session:
                candidates = list(session.scalars(
                    select(JobRun.id).where(JobRun.status == before,
                                            time_column.is_not(None), time_column < cutoff)
                    .order_by(time_column).limit(limit)))
            # One parent per transaction keeps lock ordering consistent with
            # workers, retry and purge, even across concurrent reconciliation.
            for run_id in candidates:
                with self.session_factory.begin() as session:
                    if not self._lock_parent_for_run(session, run_id):
                        continue
                    changed = session.execute(update(JobRun).where(
                        JobRun.id == run_id, JobRun.status == before,
                        time_column < cutoff).values(status=after, error_code=code))
                    if changed.rowcount == 1:
                        session.expire_all()
                        self._refresh_parent(session, run_id)
                        changes[after] += 1
        return changes

    @staticmethod
    def _lock_parent_for_run(session, run_id: str) -> bool:
        """Serialize attempt changes with retry/purge: always parent before child."""
        return session.scalar(select(Job.id).join(JobRun, JobRun.job_id == Job.id)
                              .where(JobRun.id == run_id).with_for_update(of=Job)) is not None

    @staticmethod
    def _refresh_parent(session, run_id: str) -> None:
        run = session.get(JobRun, run_id)
        runs = list(session.scalars(select(JobRun).where(JobRun.job_id == run.job_id)))
        states = {item.status for item in latest_model_attempts(runs)}
        if states == {"completed"}:
            status = "completed"
        elif states <= {"completed", "failed"}:
            status = "partial_failed" if "completed" in states else "failed"
        elif "execution_uncertain" in states:
            status = "execution_uncertain"
        elif "running" in states:
            status = "running"
        elif "dispatch_uncertain" in states:
            status = "dispatch_uncertain"
        elif "dispatching" in states:
            status = "dispatching"
        else:
            status = "queued"
        # The caller holds the parent lock; GET still derives status from attempts.
        job = session.get(Job, run.job_id)
        job.status = status
        job.finished_at = utcnow() if status in {"completed", "partial_failed", "failed"} else None


def latest_model_attempts(runs: list[JobRun]) -> list[JobRun]:
    """Use only the latest attempt per model for parent status, preserve history."""
    latest = {}
    for run in runs:
        if run.model_key not in latest or run.attempt_no > latest[run.model_key].attempt_no:
            latest[run.model_key] = run
    return list(latest.values())


def summarize_run_states(runs: list[JobRun]) -> str:
    states = {run.status for run in latest_model_attempts(runs)}
    if states == {"completed"}:
        return "completed"
    if states <= {"completed", "failed"}:
        return "partial_failed" if "completed" in states else "failed"
    if "execution_uncertain" in states:
        return "execution_uncertain"
    if "running" in states:
        return "running"
    if "dispatch_uncertain" in states:
        return "dispatch_uncertain"
    if "dispatching" in states:
        return "dispatching"
    return "queued"
