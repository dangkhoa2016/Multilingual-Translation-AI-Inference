"""Bound unfinished workload without charging quota twice or replaying GPUs."""
from sqlalchemy import func, select, update

from multilingual_translation_ai_inference.database import Job, JobRun, UsageWindow


def _body(translation_payload, model):
    return {**translation_payload, "model": model}


def _finish(repo, job_id):
    for run in repo.get(job_id, "single-tenant-api").runs:
        if run.status == "queued":
            token = repo.claim_dispatch(run.id)
            assert repo.start_run(run.id, token)
            assert repo.finish_run(run.id, token, "Synthetic completion", mock=True)


def test_owner_capacity_rejects_new_work_but_allows_replay_and_releases_on_completion(
    client_factory, headers, translation_payload,
):
    client, repo = client_factory(dispatcher_mode="record-only", max_pending_jobs_per_owner=1)
    first = client.post("/v1/jobs/translations", json=translation_payload, headers=headers)
    assert first.status_code == 202
    assert client.post("/v1/jobs/translations", json=translation_payload, headers=headers).json()["job_id"] == first.json()["job_id"]
    next_headers = {**headers, "Idempotency-Key": "second-work"}
    rejected = client.post("/v1/jobs/translations", json=_body(translation_payload, "index_35b"), headers=next_headers)
    assert rejected.status_code == 429 and "pending-jobs" in rejected.text
    assert int(rejected.headers["Retry-After"]) >= 1
    with repo.session_factory() as session:
        assert session.scalar(select(func.count(Job.id))) == 1
        assert all(row.used == 1 for row in session.scalars(select(UsageWindow)))
    _finish(repo, first.json()["job_id"])
    assert client.post("/v1/jobs/translations", json=translation_payload, headers=next_headers).status_code == 202


def test_model_capacity_rejects_entire_benchmark_and_rolls_back_reservations(
    client_factory, headers, translation_payload,
):
    client, repo = client_factory(dispatcher_mode="record-only", max_pending_runs_per_model=1)
    assert client.post("/v1/jobs/translations", json=translation_payload, headers=headers).status_code == 202
    body = {k: v for k, v in translation_payload.items() if k != "model"}
    body["models"] = ["hy_mt2_30b", "index_35b"]
    response = client.post("/v1/jobs/benchmarks", json=body, headers={**headers, "Idempotency-Key": "benchmark"})
    assert response.status_code == 429 and "pending-model-runs" in response.text
    with repo.session_factory() as session:
        assert session.scalar(select(func.count(Job.id))) == 1
        assert session.scalar(select(func.count(JobRun.id))) == 1
        assert all(row.used == 1 for row in session.scalars(select(UsageWindow)))


def test_uncertain_work_keeps_capacity_even_with_stale_parent_cache(client_factory, headers, translation_payload):
    client, repo = client_factory(dispatcher_mode="record-only", max_pending_jobs_per_owner=1)
    jid = client.post("/v1/jobs/translations", json=translation_payload, headers=headers).json()["job_id"]
    run = repo.get(jid, "single-tenant-api").runs[0]
    token = repo.claim_dispatch(run.id)
    repo.mark_dispatch_uncertain(run.id, token)
    with repo.session_factory.begin() as session:
        session.execute(update(Job).where(Job.id == jid).values(status="completed"))
    response = client.post("/v1/jobs/translations", json=translation_payload,
                           headers={**headers, "Idempotency-Key": "second"})
    assert response.status_code == 429
    assert repo.get(jid, "single-tenant-api").runs[0].status == "dispatch_uncertain"


def test_retry_cannot_bypass_owner_capacity(client_factory, headers, translation_payload):
    client, repo = client_factory(dispatcher_mode="record-only", max_pending_jobs_per_owner=1)
    jid = client.post("/v1/jobs/translations", json=translation_payload, headers=headers).json()["job_id"]
    run = repo.get(jid, "single-tenant-api").runs[0]
    repo.fail_run(run.id, repo.claim_dispatch(run.id), "CONFIRMED_FAILURE")
    blocker = client.post("/v1/jobs/translations", json=_body(translation_payload, "index_35b"),
                          headers={**headers, "Idempotency-Key": "blocker"}).json()["job_id"]
    retry_url = f"/v1/jobs/{jid}/runs/{run.id}/retry"
    assert client.post(retry_url, headers=headers).status_code == 429
    assert len(repo.get(jid, "single-tenant-api").runs) == 1
    _finish(repo, blocker)
    assert client.post(retry_url, headers=headers).status_code == 202
    assert len(repo.get(jid, "single-tenant-api").runs) == 2


def test_retry_inside_an_already_active_benchmark_does_not_take_another_job_slot(
    client_factory, headers, translation_payload,
):
    client, repo = client_factory(dispatcher_mode="record-only", max_pending_jobs_per_owner=1,
                                 max_pending_runs_per_model=1)
    body = {key: value for key, value in translation_payload.items() if key != "model"}
    body["models"] = ["hy_mt2_30b", "index_35b"]
    jid = client.post("/v1/jobs/benchmarks", json=body, headers=headers).json()["job_id"]
    run = next(run for run in repo.get(jid, "single-tenant-api").runs if run.model_key == "hy_mt2_30b")
    repo.fail_run(run.id, repo.claim_dispatch(run.id), "CONFIRMED_FAILURE")
    assert client.post(f"/v1/jobs/{jid}/runs/{run.id}/retry", headers=headers).status_code == 202
