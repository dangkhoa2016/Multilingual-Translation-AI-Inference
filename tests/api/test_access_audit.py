"""Optional access records disclose metadata only and have a bounded rate."""
import json

from fastapi.testclient import TestClient

from multilingual_translation_ai_inference.api import create_api
from multilingual_translation_ai_inference.settings import Settings


def test_access_records_hide_body_credentials_identifiers_and_query(client_factory, headers, translation_payload, capsys):
    client, _ = client_factory(dispatcher_mode="record-only", audit_log_enabled=True)
    body = {**translation_payload, "text": "PRIVATE_TRANSLATION_INPUT"}
    posted = client.post("/v1/jobs/translations?private=PRIVATE_QUERY", json=body, headers=headers)
    assert posted.status_code == 202
    client.get(posted.json()["status_url"], headers=headers)
    output = capsys.readouterr().out
    rows = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
    assert [row["status_code"] for row in rows] == [202, 200]
    assert all(row["event"] == "api_access" for row in rows)
    assert rows[1]["route"] == "/v1/jobs/{job_id}"
    for private in ("PRIVATE_TRANSLATION_INPUT", "PRIVATE_QUERY", posted.json()["job_id"], headers["Authorization"]):
        assert private not in output


def test_audit_is_opt_in_and_does_not_fill_demo_output(client_factory, headers, capsys):
    client, _ = client_factory()
    assert client.get("/v1/models", headers=headers).status_code == 200
    assert capsys.readouterr().out == ""


def test_access_logging_is_bounded_even_during_hard_rate_rejection(capsys, monkeypatch):
    from multilingual_translation_ai_inference import access_audit, api
    from multilingual_translation_ai_inference.auth_guard import RequestRateGuard

    # Both budgets use fixed-minute windows. A real clock can cross a window
    # boundary during CI and legitimately allow another two requests/logs.
    # Inject the same fixed clock into both independent budgets instead.
    def fixed_window_guard(*, per_peer, per_process, max_clients=4096):
        return RequestRateGuard(
            per_peer=per_peer, per_process=per_process,
            max_clients=max_clients, clock=lambda: 123.5,
        )

    monkeypatch.setattr(api, "RequestRateGuard", fixed_window_guard)
    monkeypatch.setattr(access_audit, "RequestRateGuard", fixed_window_guard)
    token = "synthetic-access-log-token"
    settings = Settings(database_url="sqlite+pysqlite:///:memory:", api_bearer_token=token,
                        audit_log_enabled=True, max_requests_per_minute_per_peer=2,
                        max_requests_per_minute_per_process=2)
    with TestClient(create_api(settings, repository=object(), dispatcher=object())) as client:
        statuses = [client.get("/v1/models").status_code for _ in range(10)]
    assert statuses == [200, 200] + [429] * 8
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    assert len(rows) == 2
    assert all(row["status_code"] == 200 and row["route"] == "/v1/models" for row in rows)
    assert all(row["authenticated"] is False for row in rows)


def test_private_server_exception_is_redacted_and_audited(capsys):
    token = "synthetic-access-log-token"
    class BrokenRepository:
        def consume_job_poll_quota(self, **kwargs):
            pass
        def get(self, *args, **kwargs):
            raise RuntimeError("PRIVATE_DATABASE_DETAIL")
    settings = Settings(database_url="sqlite+pysqlite:///:memory:", api_bearer_token=token,
                        audit_log_enabled=True)
    with TestClient(create_api(settings, repository=BrokenRepository(), dispatcher=object())) as client:
        response = client.get("/v1/jobs/00000000-0000-0000-0000-000000009001",
                              headers={"Authorization": "Bearer " + token})
    output = capsys.readouterr().out
    assert response.status_code == 500
    assert response.headers["Cache-Control"] == "no-store"
    assert "PRIVATE_DATABASE_DETAIL" not in response.text + output
    assert token not in output
    assert json.loads(output)["status_code"] == 500


def test_unavailable_log_sink_cannot_change_successful_response(client_factory, headers, monkeypatch):
    client, _ = client_factory(audit_log_enabled=True)
    def broken_sink(*args, **kwargs):
        raise OSError("PRIVATE_LOG_SINK_DETAIL")
    monkeypatch.setattr("builtins.print", broken_sink)
    response = client.get("/v1/models", headers=headers)
    assert response.status_code == 200
    assert "PRIVATE_LOG_SINK_DETAIL" not in response.text
