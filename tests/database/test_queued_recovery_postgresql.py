"""PostgreSQL-only recovery races; never point this test at production."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Lock
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.schema import CreateSchema, DropSchema

from multilingual_translation_ai_inference.database import (
    Base,
    Job,
    JobRun,
    make_engine,
    make_session_factory,
    utcnow,
)
from multilingual_translation_ai_inference.dispatcher import recover_queued_runs
from multilingual_translation_ai_inference.repository import JobRepository
from multilingual_translation_ai_inference.worker import process_mock_translation_run


@pytest.fixture
def pg_repositories():
    url = os.environ.get("TRANSLATION_TEST_POSTGRESQL_URL")
    if not url:
        pytest.skip("Dedicated PostgreSQL test database required")
    engine = make_engine(url)
    assert engine.dialect.name == "postgresql"
    schema = "queued_recovery_" + uuid4().hex
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    isolated = engine.execution_options(schema_translate_map={None: schema})
    try:
        Base.metadata.create_all(isolated)
        yield (JobRepository(make_session_factory(isolated)),
               JobRepository(make_session_factory(isolated)))
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


def _submitted(repo, *, mode="modal-cpu-mock"):
    job_id = repo.submit(
        owner="single-tenant-api", idempotency_key=uuid4().hex,
        kind="translation",
        payload={
            "source_language": "en", "target_language": "vi",
            "text": "CPU-only PostgreSQL race fixture",
            "options": {"preserve_formatting": True},
        },
        model_keys=["hy_mt2_30b"], dispatch_mode=mode,
    )
    with repo.session_factory.begin() as session:
        session.execute(update(JobRun).where(JobRun.job_id == job_id)
                        .values(created_at=utcnow() - timedelta(minutes=2)))
    return job_id, repo.get(job_id, "single-tenant-api").runs[0].id


class CpuCompleter:
    def __init__(self):
        self.calls = []
        self.lock = Lock()

    def submit(self, repo, run_id, token):
        with self.lock:
            self.calls.append(run_id)
        assert process_mock_translation_run(repo, run_id, token)
        return None


def test_two_independent_pg_sessions_claim_exactly_once(pg_repositories):
    first, second = pg_repositories
    job_id, run_id = _submitted(first)
    dispatcher = CpuCompleter()
    barrier = Barrier(2)

    def install_barrier(repo):
        old = repo.queued_recovery_candidates

        def both_saw_queued(*, mode, min_age_seconds, limit):
            items = old(mode=mode, min_age_seconds=min_age_seconds, limit=limit)
            barrier.wait(timeout=10)
            return items

        repo.queued_recovery_candidates = both_saw_queued

    install_barrier(first)
    install_barrier(second)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(recover_queued_runs, first, dispatcher,
                        mode="modal-cpu-mock", min_age_seconds=1)
        b = pool.submit(recover_queued_runs, second, dispatcher,
                        mode="modal-cpu-mock", min_age_seconds=1)
        results = [a.result(timeout=20), b.result(timeout=20)]

    assert sum(r["claimed"] for r in results) == 1
    assert dispatcher.calls == [run_id]
    assert first.get(job_id, "single-tenant-api").runs[0].status == "completed"


def test_pg_mode_fence_and_legacy_rows(pg_repositories):
    first, second = pg_repositories
    mock_job, mock_run = _submitted(first, mode="modal-cpu-mock")
    old_job, old_run = _submitted(first, mode="modal-cpu-mock")
    with first.session_factory.begin() as session:
        session.execute(update(Job).where(Job.id == old_job)
                        .values(dispatch_mode=None))
    assert second.claim_dispatch(mock_run, expected_mode="modal-gpu") is None
    assert second.claim_dispatch(old_run, expected_mode="modal-cpu-mock") is None
    assert second.queued_recovery_candidates(
        mode="modal-gpu", min_age_seconds=1, limit=10) == []
    pending = second.queued_recovery_candidates(
        mode="modal-cpu-mock", min_age_seconds=1, limit=10)
    assert [run_id for run_id, _job, _owner in pending] == [mock_run]
    assert first.get(mock_job, "single-tenant-api").runs[0].status == "queued"


def test_pg_uncertain_does_not_reenter_recovery(pg_repositories):
    first, second = pg_repositories
    job_id, run_id = _submitted(first)
    token = first.claim_dispatch(run_id, expected_mode="modal-cpu-mock")
    first.mark_dispatch_uncertain(run_id, token)
    assert second.queued_recovery_candidates(
        mode="modal-cpu-mock", min_age_seconds=1, limit=10) == []
    assert first.get(job_id, "single-tenant-api").runs[0].status == "dispatch_uncertain"
