"""Verify pinned Hy-MT2 model metadata without downloading weights or starting GPU."""
import json
import runpy
import struct
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/verify_hy_mt2_p3.py"
HELPERS = runpy.run_path(str(SCRIPT))


def test_pinned_lock_has_no_false_runtime_or_gpu_claims():
    lock = HELPERS["load_lock"]()
    assert lock["gguf"]["size_bytes"] == 31_985_729_376
    assert lock["source"]["architecture"] == "hy_v3"
    assert not lock["verification"]["full_gguf_sha256_computed_locally"]
    assert not lock["verification"]["gpu_l40s_smoke_passed"]
    assert not lock["verification"]["ready_for_real_inference"]
    assert not lock["llama_cpp"]["full_gguf_load_verified"]
    assert lock["llama_cpp"]["cpu_only_binary_build_verified"] is True
    assert lock["llama_cpp"]["cuda_binary_build_verified"] is False


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
