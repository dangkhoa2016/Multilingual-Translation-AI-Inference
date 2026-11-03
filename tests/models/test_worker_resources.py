"""CPU-only regression gates for four independently scalable L40S workers."""
import json
from pathlib import Path

from scripts.models.probe_gpu_capacity import peak_concurrent_intervals
from scripts.models.verify_manifest import EXPECTED_KEYS, load_manifest

ROOT = Path(__file__).resolve().parents[2]


def test_four_q8_0_pins_and_unique_volume_names():
    manifest = load_manifest()
    models = manifest["models"]
    assert tuple(models) == EXPECTED_KEYS
    volumes = [x["modal_volume_name"] for x in models.values()]
    assert len(set(volumes)) == 4
    assert all(len(name) < 64 for name in volumes)
    assert all(x["gpu"] == "L40S" and x["max_containers"] == 1 for x in models.values())
    assert all(x["min_containers"] == 0 and x["buffer_containers"] == 0 for x in models.values())
    assert all(x["production_worker_registered"] is True for x in models.values())
    assert sum(x["gguf_size_bytes"] for x in models.values()) > 120_000_000_000


def test_readiness_flags_match_completed_smoke_evidence():
    manifest = load_manifest()
    assert manifest["models"]["hy_mt2_30b"]["weights_staged_and_fully_hashed"] is True
    index = manifest["models"]["index_35b"]
    assert index["weights_staged_and_fully_hashed"] is True
    assert index["l40s_model_load_verified"] is True
    report = json.loads(
        (ROOT / "reports/index_35b_l40s_worker_smoke.json").read_text(encoding="utf-8")
    )
    assert report["results"]["index_35b"]["status"] == "single_sentence_gpu_smoke_passed"
    assert (
        report["results"]["index_35b"]["gguf_sha256_verification_marker"]
        == index["gguf_lfs_sha256"]
    )
    gemma = manifest["models"]["gemma4_31b_it"]
    qwen = manifest["models"]["qwen35_35b"]
    assert gemma["weights_staged_and_fully_hashed"] is True
    assert gemma["l40s_model_load_verified"] is True
    assert qwen["weights_staged_and_fully_hashed"] is True
    assert qwen["l40s_model_load_verified"] is True
    for key in ("gemma4_31b_it", "qwen35_35b"):
        model = manifest["models"][key]
        result_path = ROOT / f"reports/{key}_l40s_worker_smoke.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        assert result["results"][key]["status"] == "single_sentence_gpu_smoke_passed"
        assert result["results"][key]["gguf_sha256_verification_marker"] == model["gguf_lfs_sha256"]
        assert result["results"][key]["highest_sampled_vram_mib"] < 47000
        assert result["results"][key]["gpu_uuid"]


def test_recorded_capacity_probe_shows_four_distinct_l40s_workers():
    report_path = ROOT / "reports/four_gpu_capacity.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "four_concurrent_l40s_verified"
    assert report["max_concurrent_gpu_reservations_observed"] == 4
    assert report["unique_gpu_uuid_count"] == 4
    entries = report["instances"]
    assert len(entries) == 4
    assert len({v["model_key"] for v in entries}) == 4
    assert all("L40S" in v["gpu_name"] for v in entries)
    assert all(v["gpu_memory_mib"] >= 46000 for v in entries)
    assert all(v["end_unix_seconds"] > v["start_unix_seconds"] for v in entries)
    assert peak_concurrent_intervals(entries) == 4


def test_capacity_overlap_check_rejects_serial_queues():
    samples = [
        {"start_unix_seconds": 0.0, "end_unix_seconds": 1.0},
        {"start_unix_seconds": 1.0, "end_unix_seconds": 2.0},
        {"start_unix_seconds": 2.0, "end_unix_seconds": 3.0},
        {"start_unix_seconds": 3.0, "end_unix_seconds": 4.0},
    ]
    assert peak_concurrent_intervals(samples) == 1
    samples[1] = {"start_unix_seconds": 0.5, "end_unix_seconds": 1.5}
    assert peak_concurrent_intervals(samples) == 2


def test_gateway_retains_cpu_mock_fallback_and_four_registered_gpu_classes():
    gateway = (ROOT / "modal_app.py").read_text(encoding="utf-8")
    assert "translation_inference_cpu_mock_job_worker" in gateway
    assert "translation_inference_fastapi_cpu_gateway" in gateway
    assert "gpu=\"L40S\"" not in gateway
    helper = (ROOT / "scripts/models/smoke_gpu_models.py").read_text(
        encoding="utf-8")
    assert "smoke: bool = False" in helper
    assert "all_models: bool = False" in helper
    assert "min_containers" in helper


def test_recorded_parallel_execution_covers_four_distinct_workers():
    path = ROOT / "reports/four_gpu_parallel_inference.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    manifest = load_manifest()
    assert manifest["status"] == "real_api_and_four_gpu_worker_classes_verified"
    assert manifest["concurrent_smoke"]["distinct_gpu_uuids"] == 4
    assert data["status"] == "all_selected_models_passed"
    outputs = data["results"]
    assert set(outputs) == set(EXPECTED_KEYS)
    assert len({x["gpu_uuid"] for x in outputs.values()}) == 4
    # Modal exposes a common hostname inside containers; GPU UUID proves isolation.
    assert peak_concurrent_intervals(list(outputs.values())) == 4
    for key, result in outputs.items():
        pin = manifest["models"][key]
        assert result["model_key"] == key
        assert result["status"] == "single_sentence_gpu_smoke_passed"
        assert result["gguf_sha256_verification_marker"] == pin["gguf_lfs_sha256"]
        assert result["cuda_llama_revision"] == manifest["llama_cpp_revision_hy_mt2_proven"]
        assert result["highest_sampled_vram_mib"] < 47000
        assert result["translation"].strip()
        assert result["real_http_production_endpoint"] is False
        assert result["end_unix_seconds"] > result["start_unix_seconds"]


def test_gpu_smoke_reporting_preserves_individual_errors_and_evidence():
    source = (ROOT / "scripts/models/smoke_gpu_models.py").read_text(
        encoding="utf-8"
    )
    assert 'report_path = REPORT if all_models else REPORT.with_name(' in source
    assert '"status": "gpu_smoke_failed"' in source
    assert 'if not all_ok:' in source
    assert 'str(exc)[:500]' in source
