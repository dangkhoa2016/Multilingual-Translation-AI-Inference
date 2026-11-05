"""Validate sanitized historical GPU reports without launching or contacting GPUs."""
import json
from pathlib import Path

from multilingual_translation_ai_inference.model_registry import MODEL_REGISTRY

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
KEYS = set(MODEL_REGISTRY)


def _report(filename):
    return json.loads((REPORTS / filename).read_text(encoding="utf-8"))


def test_recorded_gpu_readiness_contains_four_distinct_l40s_workers():
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


def test_recorded_database_jobs_cover_four_completed_gpu_models():
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


def test_recorded_gateway_translation_and_benchmark_reports_are_complete():
    for filename, expected_count in (
        ("gpu_api_translation.json", 1),
        ("gpu_api_four_model_benchmark.json", 4),
    ):
        report = _report(filename)
        assert report["status"] == "real_gpu_api_passed"
        assert report["scope"] == (
            "Recorded HTTP POST through deployed Modal GPU and PostgreSQL; "
            "authenticated GET (single observed run)"
        )
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


def test_new_per_model_sanitized_evidence_is_consistent_and_redacted():
    """Validate numeric aggregation without exposing private run IDs or logs."""
    import statistics

    path = ROOT / "docs" / "gpu-per-model-evidence.json"
    raw = path.read_text(encoding="utf-8")
    for forbidden in ("v9", "2026-", "https://", "/v1/jobs/", "Bearer ", "ghp_",
                      "gmanley943", "gpu_uuid", "deployment_id"):
        assert forbidden not in raw
    report = json.loads(raw)
    assert report["kind"] == "sanitized_gpu_inference_telemetry"
    assert report["sequence"] == "per_model"
    assert set(report["models"]) == KEYS
    runs = report["runs"]
    assert len(runs) == 16
    total_reuse = 0
    for model in report["models"]:
        selected = [r for r in runs if r["model_key"] == model]
        assert [r["stage"] for r in selected] == [
            "warmup", "measured_1", "measured_2", "measured_3"
        ]
        assert selected[0]["metrics"]["worker_reuse_confirmed"] == 0
        measured = selected[1:]
        assert all(r["metrics"]["worker_reuse_confirmed"] == 1 for r in measured)
        total_reuse += sum(r["metrics"]["worker_reuse_confirmed"] for r in measured)
        values = report["summary"][model]
        assert values["successful_runs"] == 4
        assert values["warmup_runs"] == 1
        assert values["measured_runs"] == 3
        assert values["measured_reuse_confirmed"] == 3
        for field, median in values["measured_medians"].items():
            assert median == statistics.median(
                r["metrics"][field] for r in measured
            )
        for row in selected:
            metrics = row["metrics"]
            assert metrics["queue_ms"] >= 0
            assert metrics["inference_ms"] > 0
            assert metrics["total_ms"] >= metrics["inference_ms"]
            assert type(metrics["prompt_tokens"]) is int
            assert type(metrics["completion_tokens"]) is int
            assert "engine_ready_ms" not in metrics or row["stage"] == "warmup"
    assert total_reuse == 12
