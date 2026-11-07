"""Transactional job persistence, claim tokens and result aggregation."""
import hashlib
import json
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from .database import Job, JobRun, TranslationResult, utcnow


class IdempotencyConflict(Exception):
    pass


def payload_hash(kind: str, payload: dict, model_keys: list[str]) -> str:
    canonical = json.dumps({"kind": kind, "request": payload, "models": model_keys},
                           sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class JobRepository:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def submit(self, *, owner: str, idempotency_key: str | None, kind: str,
               payload: dict, model_keys: list[str]) -> str:
        digest = payload_hash(kind, payload, model_keys)
        with self.session_factory() as session:
            if idempotency_key:
                previous = session.scalar(select(Job).where(
                    Job.request_owner == owner, Job.idempotency_key == idempotency_key))
                if previous:
                    if previous.request_hash != digest:
                        raise IdempotencyConflict("Key already used with a different request")
                    return previous.id
            job = Job(request_owner=owner, idempotency_key=idempotency_key, request_hash=digest,
                      kind=kind, source_language=payload["source_language"],
                      target_language=payload["target_language"], input_text=payload["text"],
                      options_json=json.dumps(payload["options"], sort_keys=True))
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

    def queued_run_ids(self, job_id: str, owner: str) -> list[str]:
        with self.session_factory() as session:
            return list(session.scalars(select(JobRun.id).join(Job).where(
                Job.id == job_id, Job.request_owner == owner, JobRun.status == "queued")))

    def claim_dispatch(self, run_id: str) -> str | None:
        token = str(uuid4())
        with self.session_factory.begin() as session:
            result = session.execute(update(JobRun).where(JobRun.id == run_id, JobRun.status == "queued")
                                     .values(status="dispatching", claim_token=token))
            if result.rowcount != 1:
                return None
            return token

    def record_modal_call(self, run_id: str, token: str, modal_call_id: str | None) -> None:
        if not modal_call_id:
            return
        with self.session_factory.begin() as session:
            session.execute(update(JobRun).where(JobRun.id == run_id, JobRun.claim_token == token)
                            .values(modal_call_id=modal_call_id))

    def mark_dispatch_uncertain(self, run_id: str, token: str) -> None:
        with self.session_factory.begin() as session:
            session.execute(update(JobRun).where(JobRun.id == run_id,
                         JobRun.claim_token == token, JobRun.status == "dispatching")
                            .values(status="dispatch_uncertain", error_code="DISPATCH_UNKNOWN"))
            self._refresh_parent(session, run_id)

    def start_run(self, run_id: str, token: str) -> tuple[str, str, str, str, str] | None:
        with self.session_factory.begin() as session:
            updated = session.execute(update(JobRun).where(JobRun.id == run_id,
                JobRun.claim_token == token, JobRun.status.in_(["dispatching", "dispatch_uncertain"]))
                .values(status="running", started_at=utcnow(), error_code=None))
            if updated.rowcount != 1:
                return None
            run = session.get(JobRun, run_id)
            job = session.get(Job, run.job_id)
            self._refresh_parent(session, run_id)
            return job.source_language, job.target_language, job.input_text, job.options_json, run.model_key

    def finish_run(self, run_id: str, token: str, translation: str, *, mock: bool) -> bool:
        with self.session_factory.begin() as session:
            updated = session.execute(update(JobRun).where(
                JobRun.id == run_id, JobRun.claim_token == token, JobRun.status == "running")
                .values(status="completed", finished_at=utcnow()))
            if updated.rowcount != 1:
                return False
            session.add(TranslationResult(run_id=run_id, translation_text=translation,
                                          is_mock_result=mock))
            self._refresh_parent(session, run_id)
            return True

    def fail_run(self, run_id: str, token: str, code: str) -> None:
        with self.session_factory.begin() as session:
            session.execute(update(JobRun).where(JobRun.id == run_id, JobRun.claim_token == token,
                     JobRun.status.in_(["running", "dispatching", "dispatch_uncertain"]))
                            .values(status="failed", error_code=code, finished_at=utcnow()))
            self._refresh_parent(session, run_id)

    @staticmethod
    def _refresh_parent(session, run_id: str) -> None:
        run = session.get(JobRun, run_id)
        runs = list(session.scalars(select(JobRun).where(JobRun.job_id == run.job_id)))
        states = {item.status for item in runs}
        if states == {"completed"}:
            status = "completed"
        elif states <= {"completed", "failed"}:
            status = "partial_failed" if "completed" in states else "failed"
        elif "running" in states:
            status = "running"
        elif "dispatch_uncertain" in states:
            status = "dispatch_uncertain"
        elif "dispatching" in states:
            status = "dispatching"
        else:
            status = "queued"
        # Parent cache/status is best effort; GET reads run state as source of truth.
        job = session.get(Job, run.job_id)
        job.status = status
        job.finished_at = utcnow() if status in {"completed", "partial_failed", "failed"} else None


def summarize_run_states(runs: list[JobRun]) -> str:
    states = {run.status for run in runs}
    if states == {"completed"}:
        return "completed"
    if states <= {"completed", "failed"}:
        return "partial_failed" if "completed" in states else "failed"
    if "running" in states:
        return "running"
    if "dispatch_uncertain" in states:
        return "dispatch_uncertain"
    if "dispatching" in states:
        return "dispatching"
    return "queued"
