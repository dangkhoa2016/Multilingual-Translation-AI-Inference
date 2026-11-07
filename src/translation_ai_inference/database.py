"""SQLAlchemy persistence (PostgreSQL in deployment, SQLite in offline tests)."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
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
    source_language: Mapped[str] = mapped_column(String(8), nullable=False)
    target_language: Mapped[str] = mapped_column(String(8), nullable=False)
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


def make_engine(database_url: str):
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
