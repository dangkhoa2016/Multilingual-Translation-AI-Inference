"""CPU-only regression coverage for crash recovery and dispatch-mode fencing."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Lock

from sqlalchemy import update

from multilingual_translation_ai_inference.database import Job, JobRun, utcnow
from multilingual_translation_ai_inference.dispatcher import recover_queued_runs
from multilingual_translation_ai_inference.worker import process_mock_translation_run

OWNER = "single-tenant-api"
PAYLOAD = {
    "source_language": "en", "target_language": "vi", "text": "Recovery fixture",
    "options": {"preserve_formatting": True},
}


class FakeCpuDispatcher:
    def __init__(self):
        self.calls = []
        self.lock = Lock()

    def submit(self, repo, run_id, claim_token):
        with self.lock:
            self.calls.append(run_id)
        assert process_mock_translation_run(repo, run_id, claim_token)
        return None


class ForbiddenDispatcher:
    def submit(self, *_args):
        raise AssertionError("Recovered a run without explicit authorization")


def queued_job(repo, *, key, mode="modal-cpu-mock", model="hy_mt2_30b"):
    job_id = repo.submit(
        owner=OWNER, idempotency_key=key, kind="translation",
        payload=PAYLOAD, model_keys=[model], dispatch_mode=mode,
    )
    with repo.session_factory.begin() as session:
        session.execute(update(JobRun).where(JobRun.job_id == job_id).values(
            created_at=utcnow() - timedelta(minutes=2)))
    return job_id, repo.get(job_id, OWNER).runs[0].id


def test_crash_after_database_commit_recovers_once(client_factory):
    _client, repo = client_factory(dispatcher_mode="record-only")
    job_id, run_id = queued_job(repo, key="crash-before-dispatch")
    # No HTTP callback is needed; simulate gateway death after submit() commits.
    assert repo.get(job_id, OWNER).runs[0].status == "queued"
    dispatcher = FakeCpuDispatcher()
    result = recover_queued_runs(repo, dispatcher, mode="modal-cpu-mock",
                                 min_age_seconds=1)
    assert result == {"status": "ok", "candidates": 1, "claimed": 1}
    assert dispatcher.calls == [run_id]
    assert repo.get(job_id, OWNER).runs[0].status == "completed"
    repeat = recover_queued_runs(repo, dispatcher, mode="modal-cpu-mock",
                                 min_age_seconds=1)
    assert repeat["claimed"] == 0 and dispatcher.calls == [run_id]


def test_two_concurrent_schedulers_claim_one_run(client_factory):
    _client, repo = client_factory(dispatcher_mode="record-only")
    job_id, run_id = queued_job(repo, key="concurrent-recovery")
    dispatcher = FakeCpuDispatcher()
    barrier = Barrier(2)
    original_candidates = repo.queued_recovery_candidates

    def same_candidate_snapshot(**kwargs):
        candidates = original_candidates(**kwargs)
        barrier.wait(timeout=5)
        return candidates

    repo.queued_recovery_candidates = same_candidate_snapshot
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(recover_queued_runs, repo, dispatcher,
                        mode="modal-cpu-mock", min_age_seconds=1)
        b = pool.submit(recover_queued_runs, repo, dispatcher,
                        mode="modal-cpu-mock", min_age_seconds=1)
        results = [a.result(timeout=10), b.result(timeout=10)]
    assert sum(result["claimed"] for result in results) == 1
    assert dispatcher.calls == [run_id]
    assert repo.get(job_id, OWNER).runs[0].status == "completed"


def test_ambiguous_states_are_never_retried(client_factory):
    _client, repo = client_factory(dispatcher_mode="record-only")
    first_id, first_run = queued_job(repo, key="dispatch-uncertain")
    second_id, second_run = queued_job(repo, key="execution-uncertain")
    first_token = repo.claim_dispatch(first_run)
    repo.mark_dispatch_uncertain(first_run, first_token)
    second_token = repo.claim_dispatch(second_run)
    assert repo.start_run(second_run, second_token) is not None
    assert repo.mark_execution_uncertain(second_run, second_token, "TIMEOUT")
    result = recover_queued_runs(repo, ForbiddenDispatcher(), mode="modal-cpu-mock",
                                 min_age_seconds=1)
    assert result["candidates"] == 0
    assert repo.get(first_id, OWNER).runs[0].status == "dispatch_uncertain"
    assert repo.get(second_id, OWNER).runs[0].status == "execution_uncertain"


def test_recovery_fails_closed_when_mode_changes(client_factory):
    _client, repo = client_factory(dispatcher_mode="record-only")
    mock_id, mock_run = queued_job(repo, key="accepted-mock", mode="modal-cpu-mock")
    gpu_id, gpu_run = queued_job(repo, key="accepted-gpu", mode="modal-gpu")
    # Switching global dispatcher to GPU must not replay an older mock job.
    gpu_attempt = recover_queued_runs(repo, ForbiddenDispatcher(), mode="modal-gpu",
                                      allow_gpu=True, min_age_seconds=1, batch_size=1)
    assert gpu_attempt["candidates"] == 1
    assert gpu_attempt["claimed"] == 1
    assert repo.get(mock_id, OWNER).runs[0].status == "queued"
    # GPU opt-out must fail closed before even fetching candidates.
    blocked = recover_queued_runs(repo, ForbiddenDispatcher(), mode="modal-gpu",
                                  min_age_seconds=1)
    assert blocked["status"] == "gpu_recovery_disabled"
    # A per-run compare-and-set also rejects direct mode escalation.
    assert repo.claim_dispatch(mock_run, expected_mode="modal-gpu") is None
    assert repo.get(gpu_id, OWNER).runs[0].status == "dispatch_uncertain"


def test_idempotent_replay_after_dispatcher_change_does_not_escalate(client_factory, headers):
    from fastapi.testclient import TestClient

    from multilingual_translation_ai_inference.api import create_api
    from multilingual_translation_ai_inference.settings import Settings

    client, repo = client_factory(dispatcher_mode="record-only")
    body = {
        "model": "hy_mt2_30b", "source_language": "en", "target_language": "vi",
        "text": "Recovery fixture",
    }
    first = client.post("/v1/jobs/translations", json=body, headers=headers)
    assert first.status_code == 202
    switched = TestClient(create_api(
        Settings(database_url="sqlite+pysqlite:///:memory:",
                 api_bearer_token="unit-test-token-2026", dispatcher_mode="modal-gpu"),
        repository=repo, dispatcher=ForbiddenDispatcher(),
    ))
    replay = switched.post("/v1/jobs/translations", json=body, headers=headers)
    assert replay.status_code == 202
    assert replay.json()["job_id"] == first.json()["job_id"]
    assert repo.get(first.json()["job_id"], OWNER).runs[0].status == "queued"


def test_legacy_null_intent_is_not_recovered(client_factory):
    _client, repo = client_factory(dispatcher_mode="record-only")
    job_id, run_id = queued_job(repo, key="legacy", mode="modal-cpu-mock")
    with repo.session_factory.begin() as session:
        session.execute(update(Job).where(Job.id == job_id).values(dispatch_mode=None))
    assert repo.claim_dispatch(run_id, expected_mode="modal-cpu-mock") is None
    result = recover_queued_runs(repo, ForbiddenDispatcher(), mode="modal-cpu-mock",
                                 min_age_seconds=1)
    assert result["candidates"] == 0 and result["claimed"] == 0


def test_fair_recovery_candidate_batch_by_model(client_factory):
    _client, repo = client_factory(dispatcher_mode="record-only")
    queued_job(repo, key="h1", model="hy_mt2_30b")
    queued_job(repo, key="h2", model="hy_mt2_30b")
    queued_job(repo, key="h3", model="hy_mt2_30b")
    queued_job(repo, key="i1", model="index_35b")
    runs = repo.queued_recovery_candidates(mode="modal-cpu-mock",
                                           min_age_seconds=1, limit=2)
    models = {repo.get_run_model_key(run_id) for run_id, _job_id, _owner in runs}
    assert models == {"hy_mt2_30b", "index_35b"}


def test_retry_rejects_legacy_and_mode_mismatch_before_quota_or_attempt(
    client_factory, headers, translation_payload,
):
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select

    from multilingual_translation_ai_inference.api import create_api
    from multilingual_translation_ai_inference.database import UsageWindow
    from multilingual_translation_ai_inference.settings import Settings

    for intent in (None, "modal-cpu-mock"):
        client, repo = client_factory(dispatcher_mode="record-only")
        response = client.post(
            "/v1/jobs/translations", headers={
                **headers, "Idempotency-Key": f"failed-legacy-{intent}"
            }, json=translation_payload
        )
        assert response.status_code == 202
        jid = response.json()["job_id"]
        run = repo.get(jid, OWNER).runs[0]
        token = repo.claim_dispatch(run.id)
        repo.fail_run(run.id, token, "CONFIRMED_FAILURE")
        with repo.session_factory.begin() as session:
            session.execute(update(Job).where(Job.id == jid).values(
                dispatch_mode=intent))
        with repo.session_factory() as session:
            quota_before = list(session.execute(select(
                UsageWindow.scope, UsageWindow.bucket_start, UsageWindow.used
            )).all())
        changed_mode = TestClient(create_api(
            Settings(
                database_url="sqlite+pysqlite:///:memory:",
                api_bearer_token="unit-test-token-2026",
                dispatcher_mode="inline-mock"
            ),
            repository=repo,
        ))
        attempt = changed_mode.post(
            f"/v1/jobs/{jid}/runs/{run.id}/retry", headers=headers,
        )
        assert attempt.status_code == 409, attempt.text
        assert "dispatch mode" in attempt.json()["detail"]
        assert len(repo.get(jid, OWNER).runs) == 1
        assert repo.get(jid, OWNER).runs[0].status == "failed"
        with repo.session_factory() as session:
            quota_after = list(session.execute(select(
                UsageWindow.scope, UsageWindow.bucket_start, UsageWindow.used
            )).all())
            assert session.scalar(select(func.count(JobRun.id)).where(
                JobRun.job_id == jid)) == 1
        assert quota_before == quota_after


def test_explicit_retry_with_matching_intent_completes_using_correct_dispatcher(
    client_factory, headers, translation_payload,
):
    from fastapi.testclient import TestClient

    from multilingual_translation_ai_inference.api import create_api
    from multilingual_translation_ai_inference.dispatcher import RecordOnlyDispatcher
    from multilingual_translation_ai_inference.settings import Settings

    client, repo = client_factory(
        dispatcher_mode="inline-mock", dispatcher=RecordOnlyDispatcher()
    )
    response = client.post(
        "/v1/jobs/translations", headers=headers, json=translation_payload
    )
    assert response.status_code == 202
    jid = response.json()["job_id"]
    run = repo.get(jid, OWNER).runs[0]
    token = repo.claim_dispatch(run.id, expected_mode="inline-mock")
    repo.fail_run(run.id, token, "CONFIRMED_FAILURE")
    allowed = TestClient(create_api(
        Settings(
            database_url="sqlite+pysqlite:///:memory:",
            api_bearer_token="unit-test-token-2026",
            dispatcher_mode="inline-mock",
        ), repository=repo,
    ))
    retried = allowed.post(f"/v1/jobs/{jid}/runs/{run.id}/retry", headers=headers)
    assert retried.status_code == 202
    assert retried.json()["status"] == "completed"
    attempts = repo.get(jid, OWNER).runs
    assert len(attempts) == 2
    assert next(x for x in attempts if x.attempt_no == 2).status == "completed"
