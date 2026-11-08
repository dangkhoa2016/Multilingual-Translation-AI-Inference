"""Hard request admission and shared polling quotas, without a live gateway/GPU."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from multilingual_translation_ai_inference import api as api_module
from multilingual_translation_ai_inference.settings import Settings

TOKEN = "synthetic-gateway-limit-test-token"


def test_peer_budget_stops_secret_comparisons_even_for_a_correct_candidate():
    settings = Settings(database_url="sqlite+pysqlite:///:memory:", api_bearer_token=TOKEN,
                        max_requests_per_minute_per_peer=2, max_requests_per_minute_per_process=10)
    app = api_module.create_api(settings, repository=object(), dispatcher=object())
    comparisons = []
    original = api_module.secrets.compare_digest
    def compare(candidate, secret):
        comparisons.append(True)
        return original(candidate, secret)
    with patch.object(api_module, "secrets", SimpleNamespace(compare_digest=compare)), \
         TestClient(app, client=("203.0.113.1", 1234)) as client:
        for _ in range(2):
            assert client.get("/v1/models", headers={"Authorization": "Bearer wrong-token-candidate"}).status_code == 401
        blocked = client.get("/v1/models", headers={"Authorization": "Bearer " + TOKEN})
    assert blocked.status_code == 429
    assert len(comparisons) == 2
    assert 1 <= int(blocked.headers["Retry-After"]) <= 60
    assert blocked.headers["Cache-Control"] == "no-store"
    assert blocked.headers["X-Content-Type-Options"] == "nosniff"
    assert TOKEN not in blocked.text


def test_process_budget_cannot_be_avoided_by_changing_peer():
    settings = Settings(database_url="sqlite+pysqlite:///:memory:", api_bearer_token=TOKEN,
                        max_requests_per_minute_per_peer=10, max_requests_per_minute_per_process=2)
    app = api_module.create_api(settings, repository=object(), dispatcher=object())
    responses = []
    for host in ("203.0.113.1", "203.0.113.2", "203.0.113.3"):
        with TestClient(app, client=(host, 1234)) as client:
            responses.append(client.get("/v1/models", headers={"Authorization": "Bearer " + TOKEN}).status_code)
    assert responses == [200, 200, 429]


def test_request_window_resets_and_global_budget_survives_peer_eviction():
    from multilingual_translation_ai_inference.auth_guard import RequestRateGuard
    clock = [0.1]
    guard = RequestRateGuard(per_peer=2, per_process=3, max_clients=1, clock=lambda: clock[0])
    assert guard.admit("A") is None
    assert guard.admit("B") is None
    assert guard.admit("A") is None
    assert guard.admit("C") == 60
    clock[0] = 60.1
    assert guard.admit("A") is None


def test_job_polling_quota_is_shared_between_api_instances(client_factory, headers, translation_payload):
    first, repo = client_factory(dispatcher_mode="record-only", max_job_polls_per_minute=2)
    second, _ = client_factory(dispatcher_mode="record-only", max_job_polls_per_minute=2)
    submitted = first.post("/v1/jobs/translations", json=translation_payload, headers=headers).json()
    assert first.get(submitted["status_url"], headers=headers).status_code == 200
    assert second.get(submitted["status_url"], headers=headers).status_code == 200
    limited = first.get(submitted["status_url"], headers=headers)
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1
    assert len(repo.get(submitted["job_id"], "single-tenant-api").runs) == 1


@pytest.mark.parametrize("field", ["max_requests_per_minute_per_peer", "max_requests_per_minute_per_process",
                                   "max_job_polls_per_minute", "max_pending_jobs_per_owner",
                                   "max_pending_runs_per_model"])
@pytest.mark.parametrize("value", [0, -1, True, 1_000_001])
def test_new_admission_settings_reject_invalid_limits(field, value):
    with pytest.raises(ValueError):
        Settings(database_url="sqlite+pysqlite:///:memory:", api_bearer_token=TOKEN, **{field: value})
