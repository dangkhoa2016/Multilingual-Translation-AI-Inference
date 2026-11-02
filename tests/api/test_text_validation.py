"""Text accepted by the API must be representable in UTF-8 and PostgreSQL."""
import json

import pytest
from sqlalchemy import func, select

from multilingual_translation_ai_inference.database import Job, UsageWindow


@pytest.mark.parametrize("endpoint", ["translations", "benchmarks"])
@pytest.mark.parametrize("value", ["private\x00text", "private\ud800text", "private\udffftext"])
def test_unstorable_text_is_rejected_before_jobs_quotas_or_dispatch(
    client_factory, headers, translation_payload, endpoint, value,
):
    client, repo = client_factory()
    payload = {**translation_payload, "text": value}
    if endpoint == "benchmarks":
        payload["models"] = [payload.pop("model")]
    response = client.post("/v1/jobs/" + endpoint, content=json.dumps(payload, ensure_ascii=True),
                           headers={**headers, "Content-Type": "application/json"})
    assert response.status_code == 422
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "private" not in response.text
    with repo.session_factory() as session:
        assert session.scalar(select(func.count(Job.id))) == 0
        assert session.scalar(select(func.count(UsageWindow.scope))) == 0


@pytest.mark.parametrize("extra", [
    {"model": "\ud800"}, {"source_language": "\ud800"}, {"unexpected\ud800key": "secret"},
])
def test_validation_response_handles_surrogates_in_other_invalid_fields(
    client_factory, headers, translation_payload, extra,
):
    client, _ = client_factory()
    response = client.post("/v1/jobs/translations", content=json.dumps({**translation_payload, **extra}),
                           headers={**headers, "Content-Type": "application/json"})
    assert response.status_code == 422
    assert response.json()["detail"]
    assert all("input" not in error and "ctx" not in error for error in response.json()["detail"])


@pytest.mark.parametrize("value", ["Tiếng Việt", "😀", "a\n\tb", "e\u0301", "👩\u200d💻"])
def test_valid_unicode_text_keeps_its_exact_content(client_factory, headers, translation_payload, value):
    client, _ = client_factory()
    response = client.post("/v1/jobs/translations", json={**translation_payload, "text": value}, headers=headers)
    assert response.status_code == 202
    job = client.get(response.json()["status_url"], headers=headers).json()
    assert job["runs"][0]["translation_text"].endswith(value)


def test_json_surrogate_pair_is_accepted_as_one_valid_unicode_character(client_factory, headers, translation_payload):
    client, _ = client_factory()
    payload = {**translation_payload, "text": "😀"}
    response = client.post("/v1/jobs/translations", content=json.dumps(payload, ensure_ascii=True),
                           headers={**headers, "Content-Type": "application/json"})
    assert response.status_code == 202
    job = client.get(response.json()["status_url"], headers=headers).json()
    assert job["runs"][0]["translation_text"].endswith("😀")


@pytest.mark.parametrize("endpoint", ["translations", "benchmarks"])
@pytest.mark.parametrize("unknown_key", [
    "secret_session_id_testing", "private\\ud800field", "x" * 500,
])
def test_unknown_json_field_name_is_not_echoed_in_validation_error(
    client_factory, headers, translation_payload, endpoint, unknown_key,
):
    client, repo = client_factory()
    payload = {**translation_payload, unknown_key: "sensitive_value"}
    if endpoint == "benchmarks":
        payload["models"] = [payload.pop("model")]
    response = client.post("/v1/jobs/" + endpoint,
        content=json.dumps(payload, ensure_ascii=True),
        headers={**headers, "Content-Type": "application/json"})
    assert response.status_code == 422
    assert unknown_key not in response.text
    assert "sensitive_value" not in response.text
    assert any("unknown_field" in item["loc"] for item in response.json()["detail"])
    assert all(set(item) == {"type", "loc", "msg"} for item in response.json()["detail"])
    with repo.session_factory() as session:
        assert session.scalar(select(func.count(Job.id))) == 0
        assert session.scalar(select(func.count(UsageWindow.scope))) == 0


def test_validation_error_preserves_known_field_location(client_factory, headers, translation_payload):
    client, _ = client_factory()
    response = client.post("/v1/jobs/translations",
        json={**translation_payload, "text": 123}, headers=headers)
    assert response.status_code == 422
    assert any(item["loc"] == ["body", "text"] for item in response.json()["detail"])


@pytest.mark.parametrize("method,path,expected_location", [
    ("GET", "/v1/jobs/not-a-uuid", ["path", "job_id"]),
    ("POST", "/v1/jobs/not-a-uuid/runs/00000000-0000-0000-0000-000000000001/retry", ["path", "job_id"]),
    ("POST", "/v1/jobs/00000000-0000-0000-0000-000000000001/runs/not-a-uuid/retry", ["path", "run_id"]),
])
def test_invalid_path_uuid_retains_its_public_parameter_location(
    client_factory, headers, method, path, expected_location,
):
    client, _ = client_factory()
    response = client.request(method, path, headers=headers)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == expected_location
    assert "not-a-uuid" not in response.text


@pytest.mark.parametrize("key", ["path", "job_id", "run_id", "body"])
def test_trusted_location_labels_do_not_expose_unknown_json_fields(
    client_factory, headers, translation_payload, key,
):
    client, _ = client_factory()
    response = client.post("/v1/jobs/translations", headers=headers,
                           json={**translation_payload, key: "private-value"})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "unknown_field"]
    assert "private-value" not in response.text
