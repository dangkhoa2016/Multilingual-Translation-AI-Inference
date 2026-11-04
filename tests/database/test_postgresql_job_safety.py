"""PostgreSQL transaction regressions; use a dedicated test database only."""
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select, update
from sqlalchemy.schema import CreateSchema, DropSchema

from multilingual_translation_ai_inference.database import (
    Base,
    Job,
    make_engine,
    make_session_factory,
    utcnow,
)
from multilingual_translation_ai_inference.repository import JobRepository, RetryNotAllowed

OWNER = "postgresql-regression-test"
PAYLOAD = {"source_language": "en", "target_language": "vi", "text": "Synthetic test text",
           "options": {"preserve_formatting": True}}


@pytest.fixture
def pg_repo():
    url = os.environ.get("TRANSLATION_TEST_POSTGRESQL_URL")
    if not url:
        pytest.skip("Set TRANSLATION_TEST_POSTGRESQL_URL to a dedicated test database")
    engine = make_engine(url)
    assert engine.dialect.name == "postgresql", "These regressions require PostgreSQL"
    schema = "translation_test_" + uuid4().hex
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    isolated = engine.execution_options(schema_translate_map={None: schema})
    try:
        Base.metadata.create_all(isolated)
        yield JobRepository(make_session_factory(isolated)), isolated
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


def _job(repo, models):
    return repo.submit(owner=OWNER, idempotency_key=uuid4().hex,
                       kind="benchmark" if len(models) > 1 else "translation",
                       payload=PAYLOAD, model_keys=models)


def _old_failed_job(repo):
    jid = _job(repo, ["hy_mt2_30b"])
    run = repo.get(jid, OWNER).runs[0]
    token = repo.claim_dispatch(run.id)
    repo.fail_run(run.id, token, "CONFIRMED_FAILURE")
    with repo.session_factory.begin() as session:
        session.execute(update(Job).where(Job.id == jid).values(
            finished_at=utcnow() - timedelta(days=91)))
    return jid, run.id


@pytest.mark.parametrize("second_failed, expected_status", [
    (False, "completed"), (True, "partial_failed"),
])
def test_concurrent_terminal_attempts_keep_parent_eligible_for_retention(
    pg_repo, second_failed, expected_status,
):
    repo, engine = pg_repo
    jid = _job(repo, ["hy_mt2_30b", "index_35b"])
    runs = repo.get(jid, OWNER).runs
    tokens = {r.id: repo.claim_dispatch(r.id) for r in runs}
    for run in runs:
        assert repo.start_run(run.id, tokens[run.id]) is not None
    first_snapshot = threading.Event()
    second_snapshot = threading.Event()
    release_first = threading.Event()

    def after_sql(connection, cursor, statement, parameters, context, executemany):
        if "SELECT " not in statement or ".job_runs" not in statement or ".job_runs.job_id =" not in statement:
            return
        name = threading.current_thread().name
        if name.startswith("first-completion") and not first_snapshot.is_set():
            first_snapshot.set()
            assert release_first.wait(10)
        elif name.startswith("second-completion"):
            second_snapshot.set()

    event.listen(engine, "after_cursor_execute", after_sql)
    try:
        with ThreadPoolExecutor(1, thread_name_prefix="first-completion") as first_pool, \
             ThreadPoolExecutor(1, thread_name_prefix="second-completion") as second_pool:
            first = first_pool.submit(repo.finish_run, runs[0].id, tokens[runs[0].id], "First", mock=True)
            try:
                assert first_snapshot.wait(10)
                if second_failed:
                    second = second_pool.submit(repo.fail_run, runs[1].id, tokens[runs[1].id], "TEST_FAILURE")
                else:
                    second = second_pool.submit(repo.finish_run, runs[1].id, tokens[runs[1].id], "Second", mock=True)
                # An unlocked implementation reads a stale snapshot here. A serialized
                # transaction waits for the first commit and then sees both outcomes.
                second_snapshot.wait(1)
            finally:
                release_first.set()
            assert first.result(timeout=10) is True
            second.result(timeout=10)
    finally:
        event.remove(engine, "after_cursor_execute", after_sql)
    job = repo.get(jid, OWNER)
    assert job.status == expected_status
    assert job.finished_at is not None
    with repo.session_factory.begin() as session:
        session.execute(update(Job).where(Job.id == jid).values(
            finished_at=utcnow() - timedelta(days=91)))
    assert repo.purge_old_terminal_jobs(retention_days=90, apply=False) == 1


def test_purge_cannot_delete_an_accepted_active_retry(pg_repo):
    repo, engine = pg_repo
    jid, old_run = _old_failed_job(repo)
    selected = threading.Event()
    release_purge = threading.Event()
    retry_finished = threading.Event()

    def after_sql(connection, cursor, statement, parameters, context, executemany):
        if threading.current_thread().name.startswith("purge") and statement.startswith("SELECT "):
            if ".jobs.id" in statement and not selected.is_set():
                selected.set()
                assert release_purge.wait(10)

    def retry():
        try:
            run_id = repo.retry_failed_run(job_id=jid, owner=OWNER, run_id=old_run,
                                           expected_dispatch_mode="record-only")
            token = repo.claim_dispatch(run_id)
            assert repo.start_run(run_id, token) is not None
            return run_id, token
        except RetryNotAllowed:
            return None
        finally:
            retry_finished.set()

    event.listen(engine, "after_cursor_execute", after_sql)
    try:
        with ThreadPoolExecutor(1, thread_name_prefix="purge") as purge_pool, \
             ThreadPoolExecutor(1, thread_name_prefix="retry") as retry_pool:
            purge = purge_pool.submit(repo.purge_old_terminal_jobs, retention_days=90, apply=True)
            try:
                assert selected.wait(10)
                retried = retry_pool.submit(retry)
                retry_finished.wait(1)
            finally:
                release_purge.set()
            assert purge.result(timeout=10) in (0, 1)
            accepted = retried.result(timeout=10)
    finally:
        event.remove(engine, "after_cursor_execute", after_sql)
    if accepted is not None:
        run_id, token = accepted
        assert repo.get(jid, OWNER) is not None
        assert repo.finish_run(run_id, token, "Retry result retained", mock=True) is True
    else:
        assert repo.get(jid, OWNER) is None


def test_purge_skips_a_job_locked_by_an_in_progress_retry(pg_repo):
    repo, _ = pg_repo
    jid, old_run = _old_failed_job(repo)
    # Hold the same parent lock used by retry while purge scans old terminal rows.
    with repo.session_factory.begin() as session:
        session.scalar(select(Job).where(Job.id == jid).with_for_update())
        with ThreadPoolExecutor(1) as pool:
            purge = pool.submit(repo.purge_old_terminal_jobs, retention_days=90, apply=True)
            try:
                deleted = purge.result(timeout=2)
            finally:
                # Release before joining even if the old implementation blocks.
                session.rollback()
    assert deleted == 0
    run_id = repo.retry_failed_run(job_id=jid, owner=OWNER, run_id=old_run,
                                           expected_dispatch_mode="record-only")
    assert any(run.id == run_id for run in repo.get(jid, OWNER).runs)


def test_shared_model_admission_is_atomic_between_independent_owners(pg_repo):
    from multilingual_translation_ai_inference.quotas import QuotaExceeded
    repo, _ = pg_repo
    barrier = threading.Barrier(8)
    def submit(index):
        barrier.wait(timeout=10)
        try:
            return repo.submit(owner=f"owner-{index}", idempotency_key="new", kind="translation",
                payload=PAYLOAD, model_keys=["hy_mt2_30b"], max_pending_runs_per_model=2)
        except QuotaExceeded:
            return None
    with ThreadPoolExecutor(8) as pool:
        result = list(pool.map(submit, range(8)))
    assert sum(jid is not None for jid in result) == 2
    with repo.session_factory() as session:
        assert session.scalar(select(func.count(Job.id))) == 2


def test_shared_owner_admission_is_atomic_and_replays_remain_idempotent(pg_repo):
    from multilingual_translation_ai_inference.quotas import QuotaExceeded
    repo, _ = pg_repo
    barrier = threading.Barrier(8)
    def submit(index):
        barrier.wait(timeout=10)
        try:
            return repo.submit(owner=OWNER, idempotency_key=f"new-{index}", kind="translation",
                payload=PAYLOAD, model_keys=["hy_mt2_30b"], max_pending_jobs_per_owner=2)
        except QuotaExceeded:
            return None
    with ThreadPoolExecutor(8) as pool:
        result = list(pool.map(submit, range(8)))
    accepted = [jid for jid in result if jid is not None]
    assert len(accepted) == 2
    index = next(i for i, jid in enumerate(result) if jid)
    assert repo.submit(owner=OWNER, idempotency_key=f"new-{index}", kind="translation",
        payload=PAYLOAD, model_keys=["hy_mt2_30b"], max_pending_jobs_per_owner=2) == result[index]


def _gateway_process_probe(url, schema, scenario, worker_index, barrier, queue):
    """A separate engine/app per process; no network or GPU dispatcher."""
    from datetime import datetime, timezone
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from multilingual_translation_ai_inference.api import create_api
    from multilingual_translation_ai_inference.settings import Settings

    engine = make_engine(url)
    isolated = engine.execution_options(schema_translate_map={None: schema})
    repo = JobRepository(make_session_factory(isolated))
    statuses = []
    try:
        settings = Settings(database_url=url, api_bearer_token="process-test-token-2026",
            request_owner=f"owner-{worker_index}" if scenario == "model" else OWNER,
            max_jobs_per_minute=100, max_jobs_per_day=1000, max_model_runs_per_day=1000,
            max_pending_jobs_per_owner=3 if scenario == "owner" else 20,
            max_pending_runs_per_model=3 if scenario == "model" else 20,
            max_job_polls_per_minute=3)
        with TestClient(create_api(settings, repository=repo)) as client, \
             patch("multilingual_translation_ai_inference.quotas.datetime") as clock:
            # Fixed UTC bucket avoids a real minute boundary splitting the probe.
            clock.now.return_value = datetime(2026, 1, 2, tzinfo=timezone.utc)
            barrier.wait(timeout=15)
            for index in range(4):
                headers = {"Authorization": "Bearer process-test-token-2026",
                           "Idempotency-Key": f"worker-{worker_index}-{index}"}
                if scenario == "poll":
                    response = client.get("/v1/jobs/00000000-0000-0000-0000-000000000001", headers=headers)
                else:
                    response = client.post("/v1/jobs/translations", headers=headers,
                        json={**PAYLOAD, "model": "hy_mt2_30b"})
                statuses.append(response.status_code)
        queue.put(statuses)
    finally:
        engine.dispose()


@pytest.mark.parametrize("scenario", ["owner", "model", "poll"])
def test_postgresql_limits_are_shared_between_gateway_processes(pg_repo, scenario):
    import multiprocessing

    repo, engine = pg_repo
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    barrier = context.Barrier(2)
    schema = engine.get_execution_options()["schema_translate_map"][None]
    url = engine.url.render_as_string(hide_password=False)
    processes = [context.Process(target=_gateway_process_probe,
        args=(url, schema, scenario, index, barrier, queue)) for index in range(2)]
    try:
        for process in processes:
            process.start()
        results = [queue.get(timeout=30) for _ in processes]
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0
        statuses = [status for batch in results for status in batch]
        assert statuses.count(404 if scenario == "poll" else 202) == 3
        assert statuses.count(429) == 5
        with repo.session_factory() as session:
            assert session.scalar(select(func.count(Job.id))) == (0 if scenario == "poll" else 3)
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        queue.close()


@pytest.mark.parametrize("value", ["private\x00text", "private\ud800text", "private\udffftext"])
def test_postgresql_api_rejects_unstorable_text_before_admission(pg_repo, value):
    import json

    from fastapi.testclient import TestClient

    from multilingual_translation_ai_inference.api import create_api
    from multilingual_translation_ai_inference.database import UsageWindow
    from multilingual_translation_ai_inference.settings import Settings
    repo, engine = pg_repo
    settings = Settings(database_url=str(engine.url), api_bearer_token="synthetic-pg-text-token")
    with TestClient(create_api(settings, repository=repo)) as client:
        response = client.post("/v1/jobs/translations",
            content=json.dumps({**PAYLOAD, "model": "hy_mt2_30b", "text": value}),
            headers={"Authorization": "Bearer synthetic-pg-text-token", "Content-Type": "application/json"})
    assert response.status_code == 422
    assert "private" not in response.text
    with repo.session_factory() as session:
        assert session.scalar(select(func.count(Job.id))) == 0
        assert session.scalar(select(func.count(UsageWindow.scope))) == 0


@pytest.mark.parametrize("model", ["hy_mt2_30b", "index_35b", "gemma4_31b_it", "qwen35_35b"])
def test_postgresql_worker_preserves_translation_with_invalid_usage(pg_repo, monkeypatch, model):
    from types import SimpleNamespace
    from unittest.mock import patch

    from multilingual_translation_ai_inference.gpu_runtime import L40SModelRuntime
    repo, engine = pg_repo
    jid = _job(repo, [model])
    run = repo.get(jid, OWNER).runs[0]
    token = repo.claim_dispatch(run.id)
    monkeypatch.setattr("multilingual_translation_ai_inference.database.make_engine", lambda url: engine)
    monkeypatch.setenv("TRANSLATION_INFERENCE_DATABASE_URL", str(engine.url))
    runtime = L40SModelRuntime(model)
    runtime.process = SimpleNamespace(pid=None, poll=lambda: None)
    runtime.spec = {"gguf_filename": "synthetic.gguf"}
    response = {"choices": [{"finish_reason": "stop", "message": {"content": "Translation retained"}}],
                "usage": {"prompt_tokens": 2**31, "completion_tokens": 7}}
    with patch("multilingual_translation_ai_inference.gpu_runtime._request_json", return_value=response), \
         patch("multilingual_translation_ai_inference.telemetry.sample_gpu", return_value={}):
        assert runtime.process_job(run.id, token)
    stored = repo.get(jid, OWNER).runs[0]
    assert stored.status == "completed"
    assert stored.result.translation_text == "Translation retained"
    assert stored.result.input_tokens is None and stored.result.output_tokens == 7


def test_postgresql_worker_closes_connections_between_sequential_jobs(pg_repo, monkeypatch):
    import time
    from unittest.mock import patch

    from sqlalchemy import text

    from multilingual_translation_ai_inference.gpu_runtime import L40SModelRuntime
    repo, engine = pg_repo
    schema = engine.get_execution_options()["schema_translate_map"][None]
    name = "worker-lifecycle-" + uuid4().hex
    url = engine.url.update_query_dict({"options": f"-csearch_path={schema}", "application_name": name})
    monkeypatch.setenv("TRANSLATION_INFERENCE_DATABASE_URL", url.render_as_string(hide_password=False))
    runtime = L40SModelRuntime("hy_mt2_30b")
    with patch.object(runtime, "translate", return_value=("Synthetic output", 3, 4)), \
         patch("multilingual_translation_ai_inference.telemetry.sample_gpu", return_value={}):
        for index in range(12):
            jid = repo.submit(owner=OWNER, idempotency_key=str(index), kind="translation", payload=PAYLOAD,
                              model_keys=["hy_mt2_30b"], max_jobs_per_minute=100)
            rid = repo.get(jid, OWNER).runs[0].id
            token = repo.claim_dispatch(rid)
            assert runtime.process_job(rid, token)
            assert runtime.process_job(rid, token) is False
            # PostgreSQL may briefly retain a closed backend in pg_stat_activity
            # after SQLAlchemy has disposed the worker engine. Verify eventual
            # cleanup with a short bound instead of racing backend shutdown.
            deadline = time.monotonic() + 3
            while True:
                with engine.connect() as connection:
                    remaining = connection.scalar(text(
                        "SELECT count(*) FROM pg_stat_activity WHERE application_name=:name"),
                        {"name": name})
                if remaining == 0:
                    break
                assert time.monotonic() < deadline, "Worker database backend was not released"
                time.sleep(0.05)


@pytest.mark.parametrize("stored_mode", [None, "modal-cpu-mock"])
def test_postgresql_legacy_or_mismatched_retry_intent_preserves_quota(
    pg_repo, stored_mode,
):
    """The strict retry guard also applies inside PostgreSQL parent locks."""
    from multilingual_translation_ai_inference.database import JobRun, UsageWindow

    repo, _ = pg_repo
    jid, old_run = _old_failed_job(repo)
    with repo.session_factory.begin() as session:
        session.execute(update(Job).where(Job.id == jid).values(
            dispatch_mode=stored_mode))
    with repo.session_factory() as session:
        used_before = list(session.execute(select(
            UsageWindow.scope, UsageWindow.bucket_start, UsageWindow.used
        )).all())
    with pytest.raises(RetryNotAllowed, match="dispatch mode"):
        repo.retry_failed_run(
            job_id=jid, owner=OWNER, run_id=old_run,
            expected_dispatch_mode="record-only",
        )
    with repo.session_factory() as session:
        used_after = list(session.execute(select(
            UsageWindow.scope, UsageWindow.bucket_start, UsageWindow.used
        )).all())
        assert session.scalar(select(func.count(JobRun.id)).where(
            JobRun.job_id == jid)) == 1
    assert used_after == used_before
