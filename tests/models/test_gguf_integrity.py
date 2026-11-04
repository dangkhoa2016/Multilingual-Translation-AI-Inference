"""CPU-only validation for Hy-MT2 metadata in the shared model manifest."""
import json
import runpy
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "models/four_l40s_workers_q8_0_manifest.json"
SCRIPT = ROOT / "scripts/models/verify_gguf.py"
HELPERS = runpy.run_path(str(SCRIPT))


def spec():
    return HELPERS["load_manifest"]()["models"]["hy_mt2_30b"]


def test_single_manifest_pins_hy_mt2_and_engine():
    manifest = HELPERS["load_manifest"]()
    hy = manifest["models"]["hy_mt2_30b"]
    assert hy["checkpoint"] == "tencent/Hy-MT2-30B-A3B"
    assert hy["gguf_size_bytes"] == 31_985_729_376
    assert hy["source_architecture"] == "hy_v3"
    assert hy["gguf_lfs_sha256"] and len(hy["gguf_lfs_sha256"]) == 64
    assert hy["weights_staged_and_fully_hashed"] is True
    assert hy["l40s_model_load_verified"] is True
    assert hy["production_worker_registered"] is True
    assert hy["llama_cpp_architecture_source"] == "src/models/hy-v3.cpp"
    assert len(hy["llama_cpp_architecture_source_sha256"]) == 64
    assert len(hy["source_small_file_sha256"]) == 3
    assert len(manifest["llama_cpp_revision_hy_mt2_proven"]) == 40
    assert not (ROOT / "models/hy_mt2_30b_q8_0.lock.json").exists()


def test_parse_bounded_gguf_architecture_prefix():
    key = b"general.architecture"
    value = b"hy_v3"
    mock = (
        b"GGUF" + struct.pack("<IQQ", 3, 766, 37)
        + struct.pack("<Q", len(key)) + key + struct.pack("<I", 8)
        + struct.pack("<Q", len(value)) + value + bytes(32)
    )
    assert HELPERS["gguf_header_from_prefix"](mock) == spec()["gguf_header"]
    with pytest.raises(ValueError):
        HELPERS["gguf_header_from_prefix"](b"NOPE" + mock[4:])
    with pytest.raises(ValueError):
        HELPERS["gguf_header_from_prefix"](mock[:15])


def test_malformed_manifest_metadata_is_rejected(tmp_path):
    data = HELPERS["load_manifest"]()
    hy = data["models"]["hy_mt2_30b"]
    hy["gguf_lfs_sha256"] = "missing"
    changed = tmp_path / "bad.json"
    changed.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(AssertionError):
        HELPERS["load_manifest"](changed)

    data = HELPERS["load_manifest"]()
    data["models"]["hy_mt2_30b"]["gguf_metadata_file_type"] = 999
    changed.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(AssertionError):
        HELPERS["load_manifest"](changed)

    data = HELPERS["load_manifest"]()
    data["models"]["hy_mt2_30b"]["source_small_file_sha256"]["config.json"] = "invalid"
    changed.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(AssertionError):
        HELPERS["load_manifest"](changed)


def test_local_full_hash_requires_exact_size(tmp_path):
    path = tmp_path / "tiny.gguf"
    path.write_bytes(b"GGUFnot-a-real-model")
    with pytest.raises(AssertionError):
        HELPERS["verify_local_gguf"](spec(), path)


def test_gguf_file_type_7_for_q8_0():
    key = b"general.file_type"
    data = (b"prefix-with-metadata" + struct.pack("<Q", len(key))
            + key + struct.pack("<II", 4, 7) + bytes(16))
    assert HELPERS["file_type_from_bounded_prefix"](data) == 7
    with pytest.raises(ValueError):
        HELPERS["file_type_from_bounded_prefix"](b"not-a-header")


def test_cuda_and_cpu_staging_use_shared_manifest():
    stage = (ROOT / "scripts/models/stage_model_weights.py").read_text()
    smoke = (ROOT / "scripts/models/cuda_image.py").read_text()
    preflight = (ROOT / "scripts/models/build_llama_cpp_cpu.sh").read_text()
    for source in (stage, smoke, preflight):
        assert "four_l40s_workers_q8_0_manifest.json" in source
        assert "hy_mt2_30b_q8_0.lock.json" not in source
    assert "spec[\"gguf_lfs_sha256\"]" in stage
    assert "HY_SPEC[\"llama_cpp_architecture_source_sha256\"]" in smoke
    assert "llama_cpp_revision_hy_mt2_proven" in smoke
    assert "llama_cpp_revision_hy_mt2_proven" in preflight


def test_public_gpu_smoke_report_matches_shared_manifest():
    data = HELPERS["load_manifest"]()
    hy = data["models"]["hy_mt2_30b"]
    report = json.loads((ROOT / "reports/hy_mt2_gpu_smoke.json").read_text())
    result = report["result"]
    assert report["model_manifest"] == "models/four_l40s_workers_q8_0_manifest.json"
    assert report["engine_revision"] == data["llama_cpp_revision_hy_mt2_proven"]
    assert result["status"] == "smoke_passed"
    assert result["model_key"] == "hy_mt2_30b"
    assert result["gguf_sha256_verified_on_cpu"] == hy["gguf_lfs_sha256"]
    assert result["translation_output"]
    assert result["observed_gpu_used_mib"] > 30000
    assert result["load_to_ready_seconds"] > 0
    assert result["usage"]["completion_tokens"] > 0
    assert result["exact_gpu_memory_peak_externally_instrumented"] is False


def test_four_model_gguf_integrity_has_individual_checksum_contracts():
    data = HELPERS["load_manifest"]()
    assert len(data["models"]) == 4
    for key, row in data["models"].items():
        assert len(row["gguf_lfs_sha256"]) == 64, key
        assert row["gguf_filename"].endswith(".gguf"), key
        assert row["gguf_size_bytes"] > 30_000_000_000, key
    assert HELPERS["verify_online_selected"].__name__ == "verify_online_selected"
