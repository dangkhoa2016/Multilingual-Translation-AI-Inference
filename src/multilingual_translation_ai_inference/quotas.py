"""Durable atomic rate and cost guard counters, shared by all Modal containers."""
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .database import UsageWindow


class QuotaExceeded(Exception):
    def __init__(self, scope: str, retry_after_seconds: int):
        self.scope = scope
        self.retry_after_seconds = max(1, retry_after_seconds)
        super().__init__(f"Job submission limit reached: {scope}")


def consume_quota(session, *, owner: str, scope: str, amount: int, limit: int,
                  window_seconds: int, now: datetime | None = None) -> None:
    """Increment a per-owner window in the caller transaction, or rollback on rejection.

    Supports PostgreSQL and SQLite. Insert / conditional update is atomic, including
    across independent web containers; no in-memory counters or Redis required.
    """
    now = now or datetime.now(timezone.utc)
    timestamp = int(now.timestamp())
    bucket_start = timestamp // window_seconds * window_seconds
    dialect = session.bind.dialect.name
    if dialect == "postgresql":
        statement = postgresql_insert(UsageWindow)
    elif dialect == "sqlite":
        statement = sqlite_insert(UsageWindow)
    else:
        raise RuntimeError("Quota transactions require PostgreSQL or SQLite")
    statement = statement.values(
        request_owner=owner, scope=scope, bucket_start=bucket_start, used=amount,
    )
    statement = statement.on_conflict_do_update(
        index_elements=["request_owner", "scope", "bucket_start"],
        set_={"used": UsageWindow.used + amount},
        where=UsageWindow.used + amount <= limit,
    ).returning(UsageWindow.used)
    if amount > limit or session.scalar(statement) is None:
        raise QuotaExceeded(scope, bucket_start + window_seconds - timestamp)


def apply_submission_quotas(session, *, owner: str, model_count: int,
                            max_jobs_per_minute: int, max_jobs_per_day: int,
                            max_model_runs_per_day: int, retry: bool = False) -> None:
    if not retry:
        consume_quota(session, owner=owner, scope="jobs-per-minute", amount=1,
                      limit=max_jobs_per_minute, window_seconds=60)
        consume_quota(session, owner=owner, scope="jobs-per-day", amount=1,
                      limit=max_jobs_per_day, window_seconds=86400)
    consume_quota(session, owner=owner, scope="model-runs-per-day", amount=model_count,
                  limit=max_model_runs_per_day, window_seconds=86400)
