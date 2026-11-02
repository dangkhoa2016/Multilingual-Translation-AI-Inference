"""CPU-only per-attempt telemetry regression and security tests."""
import json
from unittest.mock import patch

from multilingual_translation_ai_inference.database import JobRun
from multilingual_translation_ai_inference.telemetry import (
    cpu_during_inference,
    llama_timing_metrics,
    sample_gpu,
    valid_metric,
)


def test_mock_response_has_no_fabricated_gpu_metrics(client_factory, headers, translation_payload):
    client, _ = client_factory()
    posted = client.post("/v1/jobs/translations", json=translation_payload, headers=headers)
    run = client.get(posted.json()["status_url"], headers=headers).json()["runs"][0]
    assert run["is_mock_result"]
    assert run["usage"] is None and run["resources"] is None
    assert run["timings"]["queue_ms"] >= 0 and run["timings"]["total_ms"] >= 0
    assert "inference_ms" not in run["timings"]


def test_per_attempt_metrics_persist_and_require_auth(client_factory, headers, translation_payload):
    client, repo = client_factory(dispatcher_mode="record-only")
    posted = client.post("/v1/jobs/translations", headers=headers, json=translation_payload)
    url = posted.json()["status_url"]
    assert client.get(url).status_code == 401
    rid = client.get(url, headers=headers).json()["runs"][0]["run_id"]
    token = repo.claim_dispatch(rid)
    assert repo.start_run(rid, token)
    assert repo.finish_run(rid, token, "Xin chào", mock=False, input_tokens=12, output_tokens=7,
        metrics={"timings": {"inference_ms": 123.456, "prefill_ms": 20.1,
                             "decode_ms": 90.2, "tokens_per_second": 77.6,
                             "worker_reuse_confirmed": 1.0,
                             "engine_ready_ms": 22000.0},
                 "resources": {"sampled_vram_mib": 31151,
                               "sampled_gpu_utilization_percent": 4,
                               "cpu_process_seconds": 0.13, "cpu_utilization_percent": 103.5}})
    run = client.get(url, headers=headers).json()["runs"][0]
    assert run["usage"] == {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19}
    assert run["timings"]["inference_ms"] == 123.456
    assert run["timings"]["worker_reuse_confirmed"] == 1.0
    assert run["timings"]["engine_ready_ms"] == 22000.0
    assert run["timings"]["queue_ms"] >= 0
    assert run["timings"]["total_ms"] >= run["timings"]["queue_ms"]
    assert run["resources"]["sampled_vram_mib"] == 31151
    assert run["resources"]["cpu_utilization_percent"] == 103.5
    with repo.session_factory() as session:
        assert json.loads(session.get(JobRun, rid).metrics_json)["resources"]["sampled_vram_mib"] == 31151


def test_old_rows_and_bad_metric_json_return_null(client_factory, headers, translation_payload):
    client, repo = client_factory(dispatcher_mode="record-only")
    posted = client.post("/v1/jobs/translations", headers=headers, json=translation_payload)
    url = posted.json()["status_url"]
    rid = client.get(url, headers=headers).json()["runs"][0]["run_id"]
    with repo.session_factory.begin() as session:
        run = session.get(JobRun, rid)
        run.metrics_json = "{invalid"
        run.created_at = None
    run = client.get(url, headers=headers).json()["runs"][0]
    assert run["usage"] is None and run["timings"] is None and run["resources"] is None


def test_llama_timings_are_numeric_and_whitelisted():
    assert llama_timing_metrics({"timings": {
        "prompt_ms": 12.56, "predicted_ms": 43, "predicted_per_second": 90.01,
        "prompt_per_second": float("nan"), "api_token": "SECRET",
    }}) == {"prefill_ms": 12.56, "decode_ms": 43.0, "tokens_per_second": 90.01}
    assert llama_timing_metrics({"timings": "SECRET"}) == {}
    for value in (float("nan"), float("inf"), -1, True, "12"):
        assert valid_metric(value) is None


def test_telemetry_failure_never_blocks_inference():
    assert cpu_during_inference(None, 3, 1) == {}
    assert cpu_during_inference(4, 3, 1) == {}
    assert cpu_during_inference(1, 3, 0) == {}
    assert cpu_during_inference(1, 3, 1) == {
        "cpu_process_seconds": 2, "cpu_utilization_percent": 200.0,
    }
    with patch("subprocess.check_output", side_effect=FileNotFoundError()):
        assert sample_gpu() == {}
    with patch("subprocess.check_output", return_value="32000, 40\n"):
        assert sample_gpu() == {"sampled_vram_mib": 32000, "sampled_gpu_utilization_percent": 40}
    with patch("subprocess.check_output", return_value="32000, 101\n"):
        assert sample_gpu() == {}


def test_numeric_telemetry_overflow_is_ignored():
    assert valid_metric(10**400) is None
    assert valid_metric(-(10**400)) is None
    assert llama_timing_metrics({"timings": {"prompt_ms": 10**400, "predicted_ms": 12}}) == {"decode_ms": 12.0}


def test_stored_oversized_metric_does_not_break_authenticated_get(client_factory, headers, translation_payload):
    client, repo = client_factory(dispatcher_mode="record-only")
    submitted = client.post("/v1/jobs/translations", json=translation_payload, headers=headers).json()
    rid = repo.get(submitted["job_id"], "single-tenant-api").runs[0].id
    token = repo.claim_dispatch(rid)
    assert repo.start_run(rid, token)
    assert repo.finish_run(rid, token, "Translation retained", mock=False,
                           metrics={"timings": {"inference_ms": 10**400}})
    response = client.get(submitted["status_url"], headers=headers)
    assert response.status_code == 200
    run = response.json()["runs"][0]
    assert run["translation_text"] == "Translation retained"
    assert "inference_ms" not in (run["timings"] or {})


def test_engine_telemetry_overflow_does_not_discard_successful_translation(
    client_factory, headers, translation_payload, monkeypatch,
):
    from types import SimpleNamespace

    from multilingual_translation_ai_inference.gpu_runtime import L40SModelRuntime

    client, repo = client_factory(dispatcher_mode="record-only")
    submitted = client.post("/v1/jobs/translations", json=translation_payload, headers=headers).json()
    run = repo.get(submitted["job_id"], "single-tenant-api").runs[0]
    token = repo.claim_dispatch(run.id)
    runtime = L40SModelRuntime("hy_mt2_30b")
    runtime.process = SimpleNamespace(pid=None, poll=lambda: None)
    runtime.spec = {"gguf_filename": "synthetic.gguf"}
    monkeypatch.setenv("TRANSLATION_INFERENCE_DATABASE_URL", str(repo.session_factory.kw["bind"].url))
    response = {"choices": [{"finish_reason": "stop", "message": {"content": "Successful translation"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4},
                "timings": {"prompt_ms": 10**400}}
    with patch("multilingual_translation_ai_inference.gpu_runtime._request_json", return_value=response), \
         patch("multilingual_translation_ai_inference.telemetry.sample_gpu", return_value={}):
        assert runtime.process_job(run.id, token) is True
    persisted = repo.get(submitted["job_id"], "single-tenant-api").runs[0]
    assert persisted.status == "completed"
    assert persisted.result.translation_text == "Successful translation"


def test_nonserializable_optional_metrics_cannot_prevent_result_storage(client_factory, headers, translation_payload):
    client, repo = client_factory(dispatcher_mode="record-only")
    submitted = client.post("/v1/jobs/translations", json=translation_payload, headers=headers).json()
    rid = repo.get(submitted["job_id"], "single-tenant-api").runs[0].id
    token = repo.claim_dispatch(rid)
    assert repo.start_run(rid, token)
    assert repo.finish_run(rid, token, "Valid translation", mock=False,
                           metrics={"timings": {"inference_ms": float("nan")}})
    assert client.get(submitted["status_url"], headers=headers).json()["runs"][0]["translation_text"] == "Valid translation"


def test_persistence_ignores_invalid_optional_token_counts(client_factory, headers, translation_payload):
    client, repo = client_factory(dispatcher_mode="record-only")
    submitted = client.post("/v1/jobs/translations", json=translation_payload, headers=headers).json()
    rid = repo.get(submitted["job_id"], "single-tenant-api").runs[0].id
    token = repo.claim_dispatch(rid)
    repo.start_run(rid, token)
    assert repo.finish_run(rid, token, "Valid output retained", mock=False,
                           input_tokens=2**40, output_tokens=True)
    run = client.get(submitted["status_url"], headers=headers).json()["runs"][0]
    assert run["translation_text"] == "Valid output retained"
    assert run["usage"] is None


def test_get_ignores_legacy_invalid_counts_and_keeps_valid_sibling(client_factory, headers, translation_payload):
    from multilingual_translation_ai_inference.database import TranslationResult
    client, repo = client_factory()
    submitted = client.post("/v1/jobs/translations", json=translation_payload, headers=headers).json()
    rid = repo.get(submitted["job_id"], "single-tenant-api").runs[0].id
    with repo.session_factory.begin() as session:
        result = session.get(TranslationResult, rid)
        result.input_tokens = 2**40
        result.output_tokens = 7
    run = client.get(submitted["status_url"], headers=headers).json()["runs"][0]
    assert run["usage"] == {"completion_tokens": 7}

def test_invalid_worker_reuse_metrics_are_not_exposed(client_factory, headers, translation_payload):
    client, repo = client_factory(dispatcher_mode="record-only")
    posted = client.post("/v1/jobs/translations", headers=headers, json=translation_payload)
    rid = client.get(posted.json()["status_url"], headers=headers).json()["runs"][0]["run_id"]
    token = repo.claim_dispatch(rid)
    assert repo.start_run(rid, token)
    assert repo.finish_run(rid, token, "Valid translation", mock=False,
        metrics={"timings": {"worker_reuse_confirmed": "secret-string",
                              "engine_ready_ms": -100.0,
                              "inference_ms": 25.0}})
    timings = client.get(posted.json()["status_url"], headers=headers).json()["runs"][0]["timings"]
    assert "worker_reuse_confirmed" not in timings
    assert "engine_ready_ms" not in timings
    assert timings["inference_ms"] == 25.0
