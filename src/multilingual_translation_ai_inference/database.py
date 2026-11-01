"""SQLAlchemy persistence (PostgreSQL in deployment, SQLite in offline tests)."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def uuid_string() -> str:
    return str(uuid4())


def valid_token_count(value) -> int | None:
    """Optional engine counts must fit PostgreSQL INTEGER; bool is not a count."""
    return value if type(value) is int and 0 <= value <= 2_147_483_647 else None


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("request_owner", "idempotency_key", name="uq_jobs_owner_idempotency"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    request_owner: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    source_language: Mapped[str] = mapped_column(String(64), nullable=False)
    target_language: Mapped[str] = mapped_column(String(64), nullable=False)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    options_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    runs: Mapped[list["JobRun"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class JobRun(Base):
    __tablename__ = "job_runs"
    __table_args__ = (UniqueConstraint("job_id", "model_key", "attempt_no", name="uq_job_runs_attempt"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False)
    model_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    attempt_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False, index=True)
    claim_token: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow)
    metrics_json: Mapped[str | None] = mapped_column(Text)
    dispatch_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    modal_call_id: Mapped[str | None] = mapped_column(String(128))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    job: Mapped[Job] = relationship(back_populates="runs")
    result: Mapped["TranslationResult | None"] = relationship(back_populates="run", uselist=False)


class TranslationResult(Base):
    __tablename__ = "translation_results"

    run_id: Mapped[str] = mapped_column(ForeignKey("job_runs.id", ondelete="CASCADE"), primary_key=True)
    translation_text: Mapped[str] = mapped_column(Text, nullable=False)
    is_mock_result: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    run: Mapped[JobRun] = relationship(back_populates="result")


def normalize_postgresql_url(database_url: str) -> str:
    """Use installed psycopg v3 for provider URLs written as postgresql://."""
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url[len("postgresql://"):]
    return database_url



class AdmissionLock(Base):
    """Stable lock keys: capacities are derived from actual unfinished attempts."""
    __tablename__ = "admission_locks"
    scope: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), primary_key=True)


class UsageWindow(Base):
    """Atomic per-owner quota counters; bucket timestamps are UTC Unix seconds."""

    __tablename__ = "usage_windows"

    request_owner: Mapped[str] = mapped_column(String(128), primary_key=True)
    scope: Mapped[str] = mapped_column(String(32), primary_key=True)
    bucket_start: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    used: Mapped[int] = mapped_column(Integer, nullable=False)

def make_engine(database_url: str):
    database_url = normalize_postgresql_url(database_url)
    args = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        args["connect_args"] = {"check_same_thread": False}
    else:
        args["pool_size"] = 2
        args["max_overflow"] = 2
        args["pool_recycle"] = 300
    engine = create_engine(database_url, **args)
    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def enable_sqlite_foreign_keys(connection, _connection_record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


def make_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)
