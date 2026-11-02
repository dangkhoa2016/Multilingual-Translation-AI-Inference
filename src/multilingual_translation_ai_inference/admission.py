"""Transactional backpressure shared by gateways; uncertain work retains capacity."""
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .database import AdmissionLock, Job, JobRun
from .quotas import QuotaExceeded

ACTIVE_RUN_STATES = ("queued", "dispatching", "running", "dispatch_uncertain", "execution_uncertain")


def enforce_pending_limits(session, *, owner: str, model_keys: list[str],
                           max_jobs: int, max_runs_per_model: int,
                           existing_job_id: str | None = None) -> None:
    if any(type(value) is not int or value < 1 for value in (max_jobs, max_runs_per_model)):
        raise ValueError("Pending workload limits must be positive integers")
    dialect = session.bind.dialect.name
    insert = {"postgresql": pg_insert, "sqlite": sqlite_insert}.get(dialect)
    if insert is None:
        raise RuntimeError("Pending admission requires PostgreSQL or SQLite")
    # Every admission locks the owner, then model names in deterministic order.
    # Workers only remove work from these counts; they need no admission lock.
    for scope, name in [("owner", owner), *(("model", key) for key in sorted(set(model_keys)))]:
        session.execute(insert(AdmissionLock).values(scope=scope, name=name)
                        .on_conflict_do_nothing(index_elements=["scope", "name"]))
        session.scalar(select(AdmissionLock).where(
            AdmissionLock.scope == scope, AdmissionLock.name == name).with_for_update())
    active = JobRun.status.in_(ACTIVE_RUN_STATES)
    already_active = existing_job_id is not None and session.scalar(
        select(func.count(JobRun.id)).where(JobRun.job_id == existing_job_id, active)) > 0
    pending_jobs = session.scalar(select(func.count(func.distinct(Job.id))).join(
        JobRun, JobRun.job_id == Job.id).where(Job.request_owner == owner, active))
    if not already_active and pending_jobs >= max_jobs:
        raise QuotaExceeded("pending-jobs", 30)
    counts = dict(session.execute(select(JobRun.model_key, func.count(JobRun.id)).where(
        JobRun.model_key.in_(model_keys), active).group_by(JobRun.model_key)).all())
    if any(counts.get(key, 0) >= max_runs_per_model for key in model_keys):
        raise QuotaExceeded("pending-model-runs", 30)
