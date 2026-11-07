"""CPU-only Reliability regressions for 1000-character boundaries and uncertain execution."""
import hashlib

import pytest
from sqlalchemy import func, select

from scripts.api_reliability_smoke import (
    BOUNDARY_TEXT,
    CONCURRENT_TEXTS,
    request_payload,
    sanitized_run,
    validate_fixture,
)
from translation_ai_inference import gpu_runtime
from translation_ai_inference.database import Job
from translation_ai_inference.gpu_runtime import ExecutionUncertain, L40SModelRuntime


def test_boundary_fixture_is_1000_codepoints_not_1000_bytes():
    validate_fixture()
    assert len(BOUNDARY_TEXT) == 1000
    assert len(BOUNDARY_TEXT.encode("utf-8")) > 1000
    assert len(BOUNDARY_TEXT + "x") == 1001
    assert "\n\n" in BOUNDARY_TEXT
    assert len(set(CONCURRENT_TEXTS)) == 2


def test_api_1000_accepted_and_1001_rejected_before_db_charge(client_factory, headers):
    client, repo = client_factory(dispatcher_mode="record-only")
    url = "/v1/jobs/translations"
    invalid = request_payload(BOUNDARY_TEXT + "x", model="hy_mt2_30b")
    response = client.post(url, headers=headers, json=invalid)
    assert response.status_code == 422
    with repo.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 0
    valid = request_payload(BOUNDARY_TEXT, model="hy_mt2_30b")
    accepted = client.post(url, headers=headers, json=valid)
    assert accepted.status_code == 202
    assert client.post(url, headers=headers, json=valid).json()["job_id"] == accepted.json()["job_id"]
    conflict = client.post(url, headers=headers,
                           json=request_payload(BOUNDARY_TEXT[:-1] + "!", model="hy_mt2_30b"))
    assert conflict.status_code == 409
    with repo.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 1
    job = client.get(accepted.json()["status_url"], headers=headers).json()
    assert job["status"] == "queued"
    assert job["runs"][0]["status"] == "queued"


def test_public_unauthorized_cannot_create_1000_character_job(client_factory):
    client, repo = client_factory(dispatcher_mode="record-only")
    response = client.post(
        "/v1/jobs/translations",
        json=request_payload(BOUNDARY_TEXT, model="hy_mt2_30b"),
    )
    assert response.status_code == 401
    with repo.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 0


def test_1001_input_rejected_for_four_model_benchmark(client_factory, headers):
    client, repo = client_factory(dispatcher_mode="record-only")
    payload = request_payload(
        BOUNDARY_TEXT + "x",
        models=("hy_mt2_30b", "index_35b", "gemma4_31b_it", "qwen35_35b"),
    )
    response = client.post("/v1/jobs/benchmarks", json=payload, headers=headers)
    assert response.status_code == 422
    with repo.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 0


@pytest.mark.parametrize("error", [
    TimeoutError("The local GPU socket timed out"),
    ConnectionError("The local GPU connection dropped"),
    ValueError("Invalid JSON response from llama-server"),
])
def test_gpu_transport_unknown_result_never_reports_confirmed_failure(monkeypatch, error):
    runtime = L40SModelRuntime("hy_mt2_30b")

    class Process:
        @staticmethod
        def poll():
            return None

    runtime.process = Process()
    runtime.spec = {"gguf_filename": "pinned.gguf"}

    def broken_transport(*args, **kwargs):
        raise error

    monkeypatch.setattr(gpu_runtime, "_request_json", broken_transport)
    with pytest.raises(ExecutionUncertain, match="Completion status unknown"):
        runtime.translate(
            "en", "vi", "One nonempty source sentence.",
            '{"preserve_formatting": true}',
        )


def test_sanitized_report_excludes_translation_text():
    translated = "Bản dịch riêng tư."
    sanitized = sanitized_run({
        "model": "hy_mt2_30b", "status": "completed",
        "translation_text": translated, "is_mock_result": False,
        "attempt_no": 1, "error_code": None,
    })
    assert sanitized["translation_sha256"] == hashlib.sha256(translated.encode()).hexdigest()
    assert sanitized["translation_characters"] == len(translated)
    assert "translation_text" not in sanitized
    assert translated not in repr(sanitized)


def _reliability_report(name: str) -> dict:
    import json
    from pathlib import Path

    return json.loads(
        (Path(__file__).resolve().parents[1] / "reports" / name).read_text(
            encoding="utf-8"
        )
    )


def test_real_boundary_report_has_four_nonmock_models_and_rejections():
    report = _reliability_report("unicode_input_boundary.json")
    assert report["status"] == "pass"
    assert report["input_codepoints"] == 1000
    assert report["input_utf8_bytes"] > 1000
    assert len(report["runs"]) == 4
    assert {run["model"] for run in report["runs"]} == {
        "hy_mt2_30b", "index_35b", "gemma4_31b_it", "qwen35_35b",
    }
    assert all(v == 422 for v in report["rejected_inputs_http_422"].values())
    assert set(report["rejected_inputs_http_422"]) == {
        "1001_codepoints", "empty_whitespace", "same_language",
        "unknown_language",
    }
    assert report["idempotent_job_reused"] is True
    assert report["conflicting_payload_http_409"] == 409
    assert report["parent_job_status"] == "completed"
    for run in report["runs"]:
        assert run["status"] == "completed"
        assert run["is_mock_result"] is False
        assert run["has_nonempty_output"] is True
        assert run["attempt_no"] == 1
        assert run["translation_characters"] > 0
        assert len(run["translation_sha256"]) == 64
        assert "translation_text" not in run


def test_real_same_model_report_has_two_distinct_completed_jobs():
    report = _reliability_report("concurrent_model_jobs.json")
    assert report["status"] == "pass"
    assert report["gpu_model"] == "hy_mt2_30b"
    assert report["number_of_jobs"] == 2
    assert report["unique_job_ids"] == 2
    assert len(report["post_latencies_seconds"]) == 2
    assert len(report["runs"]) == 2
    assert all(run["status"] == "completed" and
               run["is_mock_result"] is False and
               run["has_nonempty_output"] and
               run["attempt_no"] == 1 for run in report["runs"])


def test_real_warm_worker_reuse_report_preserves_cold_start_uncertainty():
    report = _reliability_report("gpu_container_reuse.json")
    assert report["status"] == "two_readiness_calls_passed"
    assert report["first_call_cold_start_guaranteed"] is False
    assert report["warm_container_reuse_observed"] is True
    assert report["same_gpu_uuid"] is True
    assert len(report["measurements"]) == 2
    first, second = report["measurements"]
    assert first["gpu_uuid"] == second["gpu_uuid"]
    assert first["model"] == second["model"] == "hy_mt2_30b"
    assert second["rpc_wall_seconds"] < first["rpc_wall_seconds"]
    assert first["model_initialization_seconds"] > 0
