"""Offline verification of recorded deployed four-worker GPU/API evidence."""
import json
from pathlib import Path

from translation_ai_inference.model_registry import MODEL_REGISTRY

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
KEYS = set(MODEL_REGISTRY)


def _report(filename):
    return json.loads((REPORTS / filename).read_text(encoding="utf-8"))


def test_deployed_model_classes_loaded_four_unique_l40s_gpus():
    report = _report("deployed_gpu_readiness.json")
    assert report["status"] == "four_deployed_gpu_classes_ready"
    assert report["errors"] == {}
    assert set(report["results"]) == KEYS
    assert len({x["gpu_uuid"] for x in report["results"].values()}) == 4
    for key, result in report["results"].items():
        assert result["model"] == key
        assert "L40S" in result["gpu"]
        assert result["model_loaded"] is True
        assert result["single_GPU"] is True
        assert result["ready_seconds"] > 0
        assert result["sampled_vram_mib"] < result["total_vram_mib"]


def test_database_gpu_benchmark_all_four_nonmock_and_gateway_readback():
    report = _report("postgresql_gpu_jobs.json")
    assert report["status"] == "four_real_gpu_jobs_persisted_and_read_by_gateway"
    assert report["model_count"] == 4
    assert report["input_codepoints"] == 849
    assert len(report["results"]) == 4
    assert {x["model"] for x in report["results"]} == KEYS
    assert set(report["api_states"]) == KEYS
    assert all(v == "completed" for v in report["api_states"].values())
    for result in report["results"]:
        assert result["status"] == "completed"
        assert result["is_mock_result"] is False
        assert result["nonempty_translation"] is True
        assert result["translation_codepoints"] > 0
        assert result["input_tokens"] > 0 and result["output_tokens"] > 0
        assert len(result["translation_sha256"]) == 64
        assert result["error_code"] is None


def test_live_api_single_real_translation_and_four_model_benchmark():
    for filename, expected_count in (
        ("gpu_api_translation.json", 1),
        ("gpu_api_four_model_benchmark.json", 4),
    ):
        report = _report(filename)
        assert report["status"] == "real_gpu_api_passed"
        assert report["elapsed_seconds"] > 0
        assert report["all_models"] is (expected_count == 4)
        runs = report["runs"]
        assert len(runs) == expected_count
        if expected_count == 4:
            assert {run["model"] for run in runs} == KEYS
        for run in runs:
            assert run["status"] == "completed"
            assert run["is_mock_result"] is False
            assert run["translation_codepoints"] > 0
            assert len(run["translation_sha256"]) == 64
            assert run["error_code"] is None


def test_production_api_mode_enabled_only_under_explicit_setting(client_factory, headers):
    from translation_ai_inference.dispatcher import RecordOnlyDispatcher

    mock_client, _ = client_factory(dispatcher_mode="record-only")
    real_client, _ = client_factory(
        dispatcher_mode="modal-gpu", dispatcher=RecordOnlyDispatcher(),
    )
    assert mock_client.get("/health").json()["inference_enabled"] is False
    assert real_client.get("/health").json() == {
        "status": "ok", "inference_enabled": True, "phase": "gpu",
    }
    models = real_client.get("/v1/models", headers=headers).json()["models"]
    assert len(models) == 4
    assert all(x["runtime_verified"] and x["enabled"] for x in models)
    assert real_client.get("/v1/models").status_code == 401


def test_dispatch_mode_switcher_avoids_cli_secret_values():
    source = (ROOT / "scripts/set_modal_dispatch_mode.py").read_text(encoding="utf-8")
    assert '"--from-json", str(path)' in source
    assert 'path.chmod(0o600)' in source
    assert '"app", "rollover"' in source
    assert '"--strategy", "recreate"' in source
    assert '"TRANSLATION_API_BEARER_TOKEN": token' in source
    assert 'if not args.apply:' in source
    assert 'previous.get("inference_enabled") is not False' in source
