"""P2 safety: durable quotas, explicit failed-run retries and uncertain reconciliation."""
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select, update

from translation_ai_inference.database import JobRun, UsageWindow, utcnow
from translation_ai_inference.repository import summarize_run_states
from translation_ai_inference.worker import process_mock_translation_run


def new_headers():
    return {"Authorization": "Bearer unit-test-token", "Idempotency-Key": str(uuid4())}


def test_atomic_quota_limits_new_jobs_but_idempotent_replays_work(client_factory, translation_payload):
    client, repo = client_factory(max_jobs_per_minute=2)
    one = new_headers()
    first = client.post("/v1/jobs/translations", json=translation_payload, headers=one)
    assert first.status_code == 202
    assert client.post("/v1/jobs/translations", json=translation_payload,
                       headers=new_headers()).status_code == 202
    denied = client.post("/v1/jobs/translations", json=translation_payload,
                         headers=new_headers())
    assert denied.status_code == 429
    assert int(denied.headers["Retry-After"]) > 0
    replay = client.post("/v1/jobs/translations", json=translation_payload, headers=one)
    assert replay.status_code == 202
    assert replay.json()["job_id"] == first.json()["job_id"]
    with repo.session_factory() as session:
        windows = list(session.scalars(select(UsageWindow).where(
            UsageWindow.scope == "jobs-per-minute")))
        assert len(windows) == 1 and windows[0].used == 2


def test_daily_model_run_quota_counts_all_benchmark_models(client_factory, translation_payload):
    client, _repo = client_factory(max_model_runs_per_day=4)
    all_models = {"source_language": "en", "target_language": "vi", "text": "Benchmark"}
    first = client.post("/v1/jobs/benchmarks", json=all_models, headers=new_headers())
    assert first.status_code == 202
    second = client.post("/v1/jobs/translations", json=translation_payload, headers=new_headers())
    assert second.status_code == 429
    assert "model-runs-per-day" in second.json()["detail"]


def test_daily_jobs_cap_is_distinct_from_model_runs(client_factory, translation_payload):
    client, _repo = client_factory(max_jobs_per_day=1, max_jobs_per_minute=5)
    assert client.post("/v1/jobs/translations", json=translation_payload,
                       headers=new_headers()).status_code == 202
    result = client.post("/v1/jobs/translations", json=translation_payload,
                         headers=new_headers())
    assert result.status_code == 429 and "jobs-per-day" in result.json()["detail"]


def test_failed_run_can_explicitly_retry_once_and_preserve_attempts(
    client_factory, translation_payload,
):
    client, repo = client_factory(dispatcher_mode="record-only", max_attempts_per_model=2)
    headers = new_headers()
    response = client.post("/v1/jobs/translations", json=translation_payload, headers=headers)
    job_id = response.json()["job_id"]
    details = client.get(response.json()["status_url"], headers=headers).json()
    old_id = details["runs"][0]["run_id"]
    token = repo.claim_dispatch(old_id)
    repo.fail_run(old_id, token, "CONFIRMED_TEST_FAILURE")
    retry_url = f"/v1/jobs/{job_id}/runs/{old_id}/retry"
    accepted = client.post(retry_url, headers=headers)
    assert accepted.status_code == 202 and accepted.json()["status"] == "queued"
    assert client.post(retry_url, headers=headers).status_code == 409
    updated = client.get(response.json()["status_url"], headers=headers).json()
    assert len(updated["runs"]) == 2
    assert {r["attempt_no"] for r in updated["runs"]} == {1, 2}
    new_id = next(r["run_id"] for r in updated["runs"] if r["attempt_no"] == 2)
    assert updated["status"] == "queued"
    assert process_mock_translation_run(repo, old_id, token) is False
    token2 = repo.claim_dispatch(new_id)
    assert process_mock_translation_run(repo, new_id, token2) is True
    final = client.get(response.json()["status_url"], headers=headers).json()
    assert final["status"] == "completed"
    assert len(final["runs"]) == 2
    assert sorted(r["status"] for r in final["runs"]) == ["completed", "failed"]
    assert summarize_run_states(repo.get(job_id, "single-tenant-api").runs) == "completed"
    assert client.post(f"/v1/jobs/{job_id}/runs/{new_id}/retry", headers=headers).status_code == 409


def test_uncertain_dispatch_is_never_retried_and_late_worker_completes(
    client_factory, translation_payload,
):
    client, repo = client_factory(dispatcher_mode="record-only")
    headers = new_headers()
    submitted = client.post("/v1/jobs/translations", headers=headers, json=translation_payload)
    job_id = submitted.json()["job_id"]
    old_id = client.get(submitted.json()["status_url"], headers=headers).json()["runs"][0]["run_id"]
    token = repo.claim_dispatch(old_id)
    with repo.session_factory.begin() as session:
        session.execute(update(JobRun).where(JobRun.id == old_id)
                        .values(dispatch_claimed_at=utcnow() - timedelta(minutes=10)))
    result = repo.reconcile_stale(dispatch_age_seconds=300, running_age_seconds=900)
    assert result == {"dispatch_uncertain": 1, "execution_uncertain": 0}
    assert client.get(submitted.json()["status_url"], headers=headers).json()["status"] == "dispatch_uncertain"
    assert client.post(f"/v1/jobs/{job_id}/runs/{old_id}/retry", headers=headers).status_code == 409
    assert process_mock_translation_run(repo, old_id, token) is True
    assert client.get(submitted.json()["status_url"], headers=headers).json()["status"] == "completed"
    assert repo.reconcile_stale() == {"dispatch_uncertain": 0, "execution_uncertain": 0}


def test_stale_running_is_marked_uncertain_but_can_finish(
    client_factory, translation_payload,
):
    client, repo = client_factory(dispatcher_mode="record-only")
    headers = new_headers()
    submitted = client.post("/v1/jobs/translations", headers=headers, json=translation_payload)
    run_id = client.get(submitted.json()["status_url"], headers=headers).json()["runs"][0]["run_id"]
    token = repo.claim_dispatch(run_id)
    assert repo.start_run(run_id, token) is not None
    with repo.session_factory.begin() as session:
        session.execute(update(JobRun).where(JobRun.id == run_id)
                        .values(started_at=utcnow() - timedelta(minutes=20)))
    assert repo.reconcile_stale(running_age_seconds=900)["execution_uncertain"] == 1
    assert client.get(submitted.json()["status_url"], headers=headers).json()["status"] == "execution_uncertain"
    assert client.post(
        f"/v1/jobs/{submitted.json()['job_id']}/runs/{run_id}/retry", headers=headers,
    ).status_code == 409
    assert repo.finish_run(run_id, token, "MOCK TEST FINISHED", mock=True) is True
    assert client.get(submitted.json()["status_url"], headers=headers).json()["status"] == "completed"


def test_reconcile_never_fails_new_queued_runs(client_factory, translation_payload):
    client, repo = client_factory(dispatcher_mode="record-only")
    response = client.post("/v1/jobs/translations", headers=new_headers(),
                           json=translation_payload)
    assert repo.reconcile_stale(dispatch_age_seconds=1, running_age_seconds=1) == {
        "dispatch_uncertain": 0, "execution_uncertain": 0,
    }
    assert repo.get(response.json()["job_id"], "single-tenant-api").status == "queued"


def test_retry_respects_daily_model_run_budget(client_factory, translation_payload):
    client, repo = client_factory(dispatcher_mode="record-only", max_model_runs_per_day=1)
    headers = new_headers()
    submit = client.post("/v1/jobs/translations", json=translation_payload, headers=headers)
    run_id = client.get(submit.json()["status_url"], headers=headers).json()["runs"][0]["run_id"]
    token = repo.claim_dispatch(run_id)
    repo.fail_run(run_id, token, "CONFIRMED_FAILURE")
    response = client.post(
        f"/v1/jobs/{submit.json()['job_id']}/runs/{run_id}/retry", headers=headers,
    )
    assert response.status_code == 429
    assert len(repo.get(submit.json()["job_id"], "single-tenant-api").runs) == 1


def test_retention_dry_run_only_deletes_old_terminal_jobs(
    client_factory, translation_payload,
):
    client, repo = client_factory()
    headers = new_headers()
    terminal = client.post("/v1/jobs/translations", json=translation_payload,
                           headers=headers).json()["job_id"]
    queued_client, _ = client_factory(dispatcher_mode="record-only")
    # Both clients share the same SQLite file created by client_factory.
    queued = queued_client.post("/v1/jobs/translations", json=translation_payload,
                                headers=new_headers()).json()["job_id"]
    with repo.session_factory.begin() as session:
        from translation_ai_inference.database import Job
        session.execute(update(Job).where(Job.id.in_([terminal, queued])).values(
            finished_at=utcnow() - timedelta(days=100)))
    assert repo.purge_old_terminal_jobs(retention_days=90, apply=False) == 1
    assert repo.get(terminal, "single-tenant-api") is not None
    assert repo.purge_old_terminal_jobs(retention_days=90, apply=True) == 1
    assert repo.get(terminal, "single-tenant-api") is None
    assert repo.get(queued, "single-tenant-api") is not None


def test_purge_does_not_remove_fresh_terminal_jobs(client_factory, translation_payload):
    client, repo = client_factory()
    job_id = client.post("/v1/jobs/translations", json=translation_payload,
                         headers=new_headers()).json()["job_id"]
    assert repo.purge_old_terminal_jobs(retention_days=90, apply=True) == 0
    assert repo.get(job_id, "single-tenant-api") is not None


def test_concurrent_unique_submissions_do_not_exceed_shared_quota(client_factory):
    from concurrent.futures import ThreadPoolExecutor

    _client, repo = client_factory(dispatcher_mode="record-only")
    from translation_ai_inference.quotas import QuotaExceeded

    def submit(index):
        try:
            repo.submit(
                owner="quota-load-test", idempotency_key=f"key-{index}",
                kind="translation",
                payload={"source_language": "en", "target_language": "vi",
                         "text": "One sentence", "options": {"preserve_formatting": True}},
                model_keys=["hy_mt2_30b"], max_jobs_per_minute=3,
                max_jobs_per_day=10, max_model_runs_per_day=10,
            )
            return "created"
        except QuotaExceeded:
            return "limited"

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(submit, range(5)))
    assert results.count("created") == 3
    assert results.count("limited") == 2
    with repo.session_factory() as session:
        windows = list(session.scalars(select(UsageWindow).where(
            UsageWindow.request_owner == "quota-load-test",
            UsageWindow.scope == "jobs-per-minute")))
        assert len(windows) == 1 and windows[0].used == 3


def test_concurrent_identical_requests_reuse_job_even_with_quota_one(client_factory):
    from concurrent.futures import ThreadPoolExecutor

    _client, repo = client_factory(dispatcher_mode="record-only")
    payload = {"source_language": "en", "target_language": "vi",
               "text": "Same request at the same instant",
               "options": {"preserve_formatting": True}}

    def submit(_index):
        return repo.submit(owner="same-key-quota-one", idempotency_key="same-key",
                           kind="translation", payload=payload, model_keys=["hy_mt2_30b"],
                           max_jobs_per_minute=1, max_jobs_per_day=1,
                           max_model_runs_per_day=1)

    with ThreadPoolExecutor(max_workers=4) as pool:
        job_ids = list(pool.map(submit, range(6)))
    assert len(set(job_ids)) == 1
    with repo.session_factory() as session:
        counters = list(session.scalars(select(UsageWindow).where(
            UsageWindow.request_owner == "same-key-quota-one")))
        assert len(counters) == 3 and all(counter.used == 1 for counter in counters)
