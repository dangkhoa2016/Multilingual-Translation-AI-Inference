"""Verify pinned Hy-MT2 model metadata without downloading weights or starting GPU."""
import json
import runpy
import struct
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/verify_hy_mt2_p3.py"
HELPERS = runpy.run_path(str(SCRIPT))


def test_pinned_lock_has_verified_smoke_but_no_production_readiness():
    lock = HELPERS["load_lock"]()
    assert lock["gguf"]["size_bytes"] == 31_985_729_376
    assert lock["source"]["architecture"] == "hy_v3"
    assert lock["verification"]["full_gguf_sha256_computed_locally"] is True
    assert lock["verification"]["volume_sha256_match"] is True
    assert lock["verification"]["gpu_l40s_smoke_passed"] is True
    assert not lock["verification"]["ready_for_real_inference"]
    assert lock["llama_cpp"]["full_gguf_load_verified"] is True
    assert lock["llama_cpp"]["cpu_only_binary_build_verified"] is True
    assert lock["llama_cpp"]["cuda_binary_build_verified"] is True


def test_parse_bounded_gguf_architecture_prefix():
    key = b"general.architecture"
    value = b"hy_v3"
    mock = (
        b"GGUF" + struct.pack("<IQQ", 3, 766, 37)
        + struct.pack("<Q", len(key)) + key + struct.pack("<I", 8)
        + struct.pack("<Q", len(value)) + value
        + bytes(32)
    )
    header = HELPERS["gguf_header_from_prefix"](mock)
    assert header == HELPERS["load_lock"]()["gguf"]["header"]
    with pytest.raises(ValueError):
        HELPERS["gguf_header_from_prefix"](b"NOPE" + mock[4:])
    with pytest.raises(ValueError):
        HELPERS["gguf_header_from_prefix"](mock[:15])


def test_invalid_lock_sha_or_readiness_is_rejected(tmp_path):
    lock = HELPERS["load_lock"]()
    lock["gguf"]["sha256_from_huggingface_metadata"] = "missing"
    test_lock = tmp_path / "bad.json"
    test_lock.write_text(json.dumps(lock), encoding="utf-8")
    with pytest.raises(AssertionError):
        HELPERS["load_lock"](test_lock)
    lock = HELPERS["load_lock"]()
    lock["verification"]["ready_for_real_inference"] = True
    test_lock.write_text(json.dumps(lock), encoding="utf-8")
    with pytest.raises(AssertionError):
        HELPERS["load_lock"](test_lock)


def test_local_full_hash_requires_exact_size(tmp_path):
    path = tmp_path / "tiny.gguf"
    path.write_bytes(b"GGUFnot-a-real-model")
    with pytest.raises(AssertionError):
        HELPERS["verify_local_gguf"](HELPERS["load_lock"](), path)

def test_gguf_file_type_7_for_q8_0():
    name = b"general.file_type"
    data = (
        b"prefix-with-metadata" + struct.pack("<Q", len(name))
        + name + struct.pack("<II", 4, 7) + bytes(16)
    )
    assert HELPERS["file_type_from_bounded_prefix"](data) == 7
    with pytest.raises(ValueError):
        HELPERS["file_type_from_bounded_prefix"](b"not-a-header")


def test_l40s_smoke_report_consistent_with_pinned_lock():
    lock = HELPERS["load_lock"]()
    report_path = Path(__file__).resolve().parents[1] / lock["verification"]["gpu_smoke_report"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    result = report["result"]
    assert report["engine_revision"] == lock["llama_cpp"]["revision"]
    assert result["status"] == "smoke_passed"
    assert result["model_key"] == lock["model_key"]
    assert result["gguf_sha256_verified_on_cpu"] == lock["gguf"]["sha256_from_huggingface_metadata"]
    assert "bình minh" in result["translation_output"]
    assert result["observed_gpu_used_mib"] > 30000
    assert result["load_to_ready_seconds"] > 0
    assert result["usage"]["completion_tokens"] > 0
    assert result["exact_gpu_memory_peak_externally_instrumented"] is False
    assert lock["verification"]["ready_for_real_inference"] is False
