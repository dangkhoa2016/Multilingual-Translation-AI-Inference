"""P7 CPU-only production safety tests: no remote Modal/GPU credentials."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from scripts.check_production_safeguards import (
    billing_summary,
    make_alerts,
    positive_usd_argument,
)
from translation_ai_inference.database import Job, UsageWindow
from translation_ai_inference.dispatcher import RecordOnlyDispatcher
from translation_ai_inference.gpu_budget import (
    configured_estimate,
    usd_to_microusd,
)
from translation_ai_inference.operations import collect_operations_snapshot
from translation_ai_inference.quotas import QuotaExceeded
from translation_ai_inference.settings import Settings


def _headers(key):
    return {"Authorization": "Bearer unit-test-token", "Idempotency-Key": key}


@pytest.mark.parametrize("value,micro", [
    ("0.01", 10000), ("0.1000001", 100001),
    ("1.0000000001", 1000001), ("0.0000001", 1),
    ("1999.999", 1999999000),
])
def test_estimated_usd_never_rounds_reservation_down(value, micro):
    assert usd_to_microusd(value, variable="test") == micro


@pytest.mark.parametrize("invalid", [
    "0", "-1", "nan", "NaN", "Infinity", "-Infinity",
    "2000.01", "bad", "", "1e100",
])
def test_invalid_estimated_budget_is_rejected(invalid):
    with pytest.raises(ValueError):
        usd_to_microusd(invalid, variable="test")


def test_both_budget_configuration_fields_are_mandatory():
    assert configured_estimate(None, None) == (0, 0)
    assert configured_estimate("0.1", "0.5") == (100000, 500000)
    for per_run, day in (("0.1", None), (None, "0.5"), ("0.5", "0.1")):
        with pytest.raises(ValueError):
            configured_estimate(per_run, day)


def test_settings_parse_optional_budget_without_default_spend_invention(monkeypatch):
    monkeypatch.setenv("TRANSLATION_INFERENCE_DATABASE_URL", "sqlite+pysqlite:///test.db")
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", "long-unit-test-token")
    monkeypatch.setenv("TRANSLATION_DISPATCHER_MODE", "modal-gpu")
    monkeypatch.delenv("TRANSLATION_ESTIMATED_GPU_USD_PER_RUN", raising=False)
    monkeypatch.delenv("TRANSLATION_MAX_ESTIMATED_GPU_USD_PER_DAY", raising=False)
    assert Settings.from_environment().estimated_gpu_microusd_per_run == 0
    monkeypatch.setenv("TRANSLATION_ESTIMATED_GPU_USD_PER_RUN", "0.30")
    monkeypatch.setenv("TRANSLATION_MAX_ESTIMATED_GPU_USD_PER_DAY", "0.50")
    settings = Settings.from_environment()
    assert settings.estimated_gpu_microusd_per_run == 300000
    assert settings.max_estimated_gpu_microusd_per_day == 500000
    monkeypatch.delenv("TRANSLATION_MAX_ESTIMATED_GPU_USD_PER_DAY")
    with pytest.raises(ValueError, match="Both estimated"):
        Settings.from_environment()


def _estimated_usage(repo):
    with repo.session_factory() as session:
        return session.scalar(select(UsageWindow.used).where(
            UsageWindow.scope == "estimated-gpu-usd-per-day",
        ))


def test_estimated_gpu_admission_and_replay_do_not_double_reserve(
    client_factory, translation_payload,
):
    client, repo = client_factory(
        dispatcher_mode="modal-gpu", dispatcher=RecordOnlyDispatcher(),
        estimated_gpu_microusd_per_run=100000,
        max_estimated_gpu_microusd_per_day=200000,
    )
    first_key = _headers("first")
    first = client.post("/v1/jobs/translations", json=translation_payload, headers=first_key)
    assert first.status_code == 202
    assert _estimated_usage(repo) == 100000
    replay = client.post("/v1/jobs/translations", json=translation_payload, headers=first_key)
    assert replay.json()["job_id"] == first.json()["job_id"]
    assert _estimated_usage(repo) == 100000
    second = client.post("/v1/jobs/translations", json=translation_payload,
                         headers=_headers("second"))
    assert second.status_code == 202
    assert _estimated_usage(repo) == 200000
    denied = client.post("/v1/jobs/translations", json=translation_payload,
                         headers=_headers("third"))
    assert denied.status_code == 429
    assert "estimated-gpu-usd-per-day" in denied.json()["detail"]
    with repo.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 2
    assert _estimated_usage(repo) == 200000
    replay_again = client.post("/v1/jobs/translations", json=translation_payload,
                               headers=first_key)
    assert replay_again.status_code == 202


def test_four_model_budget_excess_rolls_back_all_quota_counters(
    client_factory, translation_payload,
):
    client, repo = client_factory(
        dispatcher_mode="modal-gpu", dispatcher=RecordOnlyDispatcher(),
        estimated_gpu_microusd_per_run=100000,
        max_estimated_gpu_microusd_per_day=300000,
    )
    body = {"source_language": "en", "target_language": "vi", "text": "Full benchmark"}
    response = client.post("/v1/jobs/benchmarks", json=body,
                           headers=_headers("oversized-benchmark"))
    assert response.status_code == 429
    with repo.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 0
        assert session.scalar(select(func.count()).select_from(UsageWindow)) == 0
    accepted = client.post("/v1/jobs/translations", json=translation_payload,
                           headers=_headers("single-after-reject"))
    assert accepted.status_code == 202
    assert _estimated_usage(repo) == 100000


def test_manual_confirmed_failure_retry_reserves_again_or_returns_429(
    client_factory, translation_payload,
):
    client, repo = client_factory(
        dispatcher_mode="modal-gpu", dispatcher=RecordOnlyDispatcher(),
        estimated_gpu_microusd_per_run=200000,
        max_estimated_gpu_microusd_per_day=200000,
    )
    response = client.post("/v1/jobs/translations", json=translation_payload,
                           headers=_headers("retry-budget"))
    job_id = response.json()["job_id"]
    run = client.get(response.json()["status_url"],
                     headers=_headers("retry-budget")).json()["runs"][0]
    token = repo.claim_dispatch(run["run_id"])
    repo.fail_run(run["run_id"], token, "TEST_DEFINITE_FAILURE")
    retry = client.post(f"/v1/jobs/{job_id}/runs/{run['run_id']}/retry",
                        headers=_headers("retry-budget"))
    assert retry.status_code == 429
    assert _estimated_usage(repo) == 200000
    state = repo.get(job_id, "single-tenant-api")
    assert len(state.runs) == 1
    assert state.runs[0].status == "failed"


def test_mock_dispatch_mode_never_reserves_estimated_real_gpu_usd(
    client_factory, translation_payload,
):
    client, repo = client_factory(
        dispatcher_mode="inline-mock", estimated_gpu_microusd_per_run=100000,
        max_estimated_gpu_microusd_per_day=100000,
    )
    response = client.post("/v1/jobs/translations", json=translation_payload,
                           headers=_headers("mock-not-gpu"))
    assert response.status_code == 202
    assert _estimated_usage(repo) is None


def test_atomically_reserve_with_concurrent_job_creations(client_factory):
    _client, repo = client_factory(dispatcher_mode="record-only")
    body = {"source_language": "en", "target_language": "vi",
            "text": "Concurrent estimated-USD quota test",
            "options": {"preserve_formatting": True}}
    def submit(_):
        try:
            return repo.submit(
                owner="single-tenant-api",
                idempotency_key=str(uuid4()), kind="translation",
                payload=body, model_keys=["hy_mt2_30b"],
                max_jobs_per_minute=30, max_jobs_per_day=30,
                max_model_runs_per_day=30,
                estimated_gpu_microusd_per_run=100000,
                max_estimated_gpu_microusd_per_day=400000,
            )
        except QuotaExceeded:
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(submit, range(12)))
    assert sum(key is not None for key in outcomes) == 4
    assert _estimated_usage(repo) == 400000


def test_readonly_operations_snapshot_aggregates_states_not_text(
    client_factory, translation_payload,
):
    client, repo = client_factory(dispatcher_mode="record-only")
    job_id = client.post("/v1/jobs/translations", json=translation_payload,
                         headers=_headers("ops-readonly")).json()["job_id"]
    before = repo.get(job_id, "single-tenant-api")
    snap = collect_operations_snapshot(repo)
    assert snap["total_runs_by_state"]["queued"] == 1
    assert snap["recent_runs_by_state"]["queued"] == 1
    assert snap["recent_real_results_count"] == 0
    assert snap["stale_dispatching_count"] == 0
    assert snap["stale_running_count"] == 0
    assert "Good morning!" not in str(snap)
    assert repo.get(job_id, "single-tenant-api").status == before.status


def test_modal_billing_summary_reads_workspace_without_raw_billing_dump(monkeypatch):
    import json
    from types import SimpleNamespace

    def mocked_run(command, **_kwargs):
        assert command[1:5] == ["billing", "summary", "--for", "this month"]
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "metered_cost": "1.59568943",
            "billed_cost": "0E-8",
            "customer_email": "must-not-expose@example.invalid",
        }), stderr="")
    monkeypatch.setattr("scripts.check_production_safeguards.subprocess.run", mocked_run)
    summary = billing_summary(profile="test-profile")
    assert summary["metered_cost_usd"] == "1.59568943"
    assert summary["billed_cost_usd"] == "0E-8"
    assert "customer_email" not in str(summary)
    alerts = make_alerts(
        {"total_runs_by_state": {}, "stale_dispatching_count": 0,
         "stale_running_count": 0},
        summary, metered_limit=Decimal("1.50"), billed_limit=Decimal("0.01"),
    )
    assert alerts == ["workspace_metered_usd_alert_threshold"]


def test_monitor_alerts_uncertain_or_stale_without_starting_gpu():
    alerts = make_alerts({
        "total_runs_by_state": {"dispatch_uncertain": 1, "execution_uncertain": 2},
        "stale_dispatching_count": 1, "stale_running_count": 0,
    }, None, metered_limit=None, billed_limit=None)
    assert alerts == [
        "uncertain_runs_require_operator_investigation",
        "stale_running_or_dispatching_runs_detected",
    ]


@pytest.mark.parametrize("bad", ["0", "-1", "NaN", "Infinity", "wrong"])
def test_monitor_rejects_invalid_usd_alert_thresholds(bad):
    import argparse
    with pytest.raises(argparse.ArgumentTypeError):
        positive_usd_argument(bad)


def test_deployed_operations_monitor_is_hourly_cpu_and_never_runs_gpu():
    from pathlib import Path

    import modal_app

    root = Path(__file__).resolve().parents[1]
    source = (root / "modal_app.py").read_text(encoding="utf-8")
    assert hasattr(modal_app, "translation_inference_cpu_operations_safety_monitor")
    assert 'name="translation_inference_cpu_operations_safety_monitor"' in source
    assert "schedule=modal.Period(hours=1)" in source
    assert '"gpu_allocations": 0' in source
    assert '"automatic_retries": 0' in source
    assert '"recent_inference_error_codes"' in source


def test_live_cpu_monitor_snapshot_is_readonly_and_redacted():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    report = json.loads(
        (root / "reports/p7_cpu_only_live_safeguards_snapshot_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["read_only"] is True
    assert report["kind"] == "cpu_only_workspace_billing_and_postgresql_safety_snapshot"
    assert report["modal_billing"]["scope"] == "entire_modal_workspace"
    assert Decimal(report["modal_billing"]["metered_cost_usd"]) >= 0
    assert Decimal(report["modal_billing"]["billed_cost_usd"]) >= 0
    assert report["database"]["total_runs_by_state"]["completed"] >= 36
    assert report["database"]["stale_running_count"] == 0
    assert report["database"]["stale_dispatching_count"] == 0
    assert report["alerts"] == []
    content = json.dumps(report)
    assert "TRANSLATION_API_BEARER_TOKEN" not in content
    assert "TRANSLATION_INFERENCE_DATABASE_URL" not in content
    assert "translation_text" not in content
