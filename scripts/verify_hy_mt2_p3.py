#!/usr/bin/env python3
"""Reproducible Hy-MT2 P3 preflight; DOES NOT download 32 GB weights or use GPU.

Offline: python scripts/verify_hy_mt2_p3.py
Online:  python scripts/verify_hy_mt2_p3.py --online
Full file (after separately downloading):
         python scripts/verify_hy_mt2_p3.py --local-gguf /path/model.gguf
"""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

LOCK_PATH = Path(__file__).resolve().parents[1] / "models/hy_mt2_30b_q8_0.lock.json"


def load_lock(path: Path = LOCK_PATH) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["model_key"] == "hy_mt2_30b"
    assert data["source"]["architecture"] == "hy_v3"
    assert data["gguf"]["header"]["architecture"] == "hy_v3"
    assert data["gguf"]["quantization"] == "Q8_0"
    assert data["gguf"]["size_bytes"] > 30_000_000_000
    for scope in ("source", "gguf", "llama_cpp"):
        assert re.fullmatch(r"[0-9a-f]{40}", data[scope]["revision"])
    assert re.fullmatch(r"[0-9a-f]{64}", data["gguf"]["sha256_from_huggingface_metadata"])
    assert data["verification"]["ready_for_real_inference"] is False
    return data


def gguf_header_from_prefix(data: bytes) -> dict:
    """Read the first GGUF metadata field, where architecture appears.

    This validates only the bounded header prefix, NOT the tensor body.
    """
    if len(data) < 80 or data[:4] != b"GGUF":
        raise ValueError("GGUF magic or prefix length invalid")
    version, tensor_count, metadata_count = struct.unpack_from("<IQQ", data, 4)
    offset = 24
    key_length = struct.unpack_from("<Q", data, offset)[0]
    offset += 8
    if key_length != len("general.architecture"):
        raise ValueError("Expected general.architecture as first GGUF key")
    key = data[offset:offset + key_length].decode("ascii")
    offset += key_length
    value_type = struct.unpack_from("<I", data, offset)[0]
    offset += 4
    if key != "general.architecture" or value_type != 8:
        raise ValueError("GGUF architecture key/type mismatch")
    value_length = struct.unpack_from("<Q", data, offset)[0]
    offset += 8
    if not 1 <= value_length <= 64 or offset + value_length > len(data):
        raise ValueError("GGUF architecture length invalid")
    arch = data[offset:offset + value_length].decode("ascii")
    return {"magic": "GGUF", "version": version, "tensor_count": tensor_count,
            "metadata_count": metadata_count, "architecture": arch}


def file_type_from_bounded_prefix(data: bytes) -> int:
    """Inspect GGUF general.file_type without reading tensor payloads."""
    key = b"general.file_type"
    pos = data.find(key)
    if pos < 8 or len(data) < pos + len(key) + 8:
        raise ValueError("general.file_type is not inside the supplied bounded header")
    if struct.unpack_from("<Q", data, pos - 8)[0] != len(key):
        raise ValueError("general.file_type key length mismatch")
    value_type = struct.unpack_from("<I", data, pos + len(key))[0]
    if value_type != 4:
        raise ValueError("general.file_type is not a UINT32")
    return struct.unpack_from("<I", data, pos + len(key) + 4)[0]


def read_small(client, url: str, max_bytes: int = 100_000) -> bytes:
    with client.stream("GET", url) as response:
        response.raise_for_status()
        if int(response.headers.get("content-length", "0")) > max_bytes:
            raise ValueError("Refusing unexpectedly large source file")
        parts = bytearray()
        for piece in response.iter_bytes(chunk_size=8192):
            parts.extend(piece)
            if len(parts) > max_bytes:
                raise ValueError("Refusing unexpectedly large source file")
        return bytes(parts)


def verify_online(lock: dict, deep_header: bool = False) -> None:
    import httpx

    src, gguf, engine = lock["source"], lock["gguf"], lock["llama_cpp"]
    with httpx.Client(timeout=40, follow_redirects=True) as client:
        for record in (src, gguf):
            url = (f"https://huggingface.co/api/models/{record['repository']}"
                   f"/revision/{record['revision']}?blobs=true")
            response = client.get(url)
            response.raise_for_status()
            info = response.json()
            assert info["sha"] == record["revision"]
            assert info["cardData"]["license"] == record["license"]
            if record is gguf:
                match = [item for item in info["siblings"] if item["rfilename"] == gguf["file"]]
                assert len(match) == 1
                item = match[0]
                assert item["size"] == gguf["size_bytes"]
                assert item["lfs"]["sha256"] == gguf["sha256_from_huggingface_metadata"]
            print("OK pinned Hugging Face revision/license:", record["repository"])

        for filename, expected_hash in src["small_file_sha256"].items():
            url = (f"https://huggingface.co/{src['repository']}/resolve/"
                   f"{src['revision']}/{filename}")
            value = read_small(client, url)
            assert hashlib.sha256(value).hexdigest() == expected_hash, filename
            if filename == "config.json":
                assert json.loads(value)["model_type"] == src["architecture"]
            print("OK pinned small file SHA256:", filename)

        url = (f"https://huggingface.co/{gguf['repository']}/resolve/"
               f"{gguf['revision']}/{gguf['file']}")
        with httpx.Client(timeout=40, follow_redirects=False) as no_redirects:
            head = no_redirects.head(url)
            assert head.status_code in (302, 307)
            assert head.headers["x-linked-etag"].strip('"') == gguf["sha256_from_huggingface_metadata"]
            assert int(head.headers["x-linked-size"]) == gguf["size_bytes"]
        print("OK remote GGUF HEAD: metadata SHA256 and byte length")

        # Stream a bounded 8 KiB range; refuse any 200/full-file response.
        with client.stream("GET", url, headers={"Range": "bytes=0-8191"}) as response:
            assert response.status_code == 206, "Server refused bounded Range request"
            assert response.headers["content-range"] == f"bytes 0-8191/{gguf['size_bytes']}"
            header = bytearray()
            for piece in response.iter_bytes(chunk_size=8192):
                header.extend(piece)
                if len(header) > 8192:
                    raise ValueError("GGUF range exceeded 8 KiB cap")
        assert gguf_header_from_prefix(bytes(header)) == gguf["header"]
        print("OK GGUF 8 KiB header: hy_v3, tensor count, format version")

        if deep_header:
            limit = 8 * 1024 * 1024
            with client.stream("GET", url, headers={
                "Range": f"bytes=0-{limit - 1}"
            }) as response:
                assert response.status_code == 206
                assert response.headers["content-range"] == f"bytes 0-{limit - 1}/{gguf['size_bytes']}"
                deep = bytearray()
                for piece in response.iter_bytes(chunk_size=65536):
                    deep.extend(piece)
                    if len(deep) > limit:
                        raise ValueError("GGUF deep header range exceeded 8 MiB")
            assert file_type_from_bounded_prefix(bytes(deep)) == gguf["metadata_file_type"]
            print("OK GGUF Q8_0 metadata: general.file_type=7 (bounded 8 MiB read)")

        source_url = (f"https://raw.githubusercontent.com/{engine['repository']}/"
                      f"{engine['revision']}/{engine['architecture_source']}")
        cpp = read_small(client, source_url, 100_000)
        assert hashlib.sha256(cpp).hexdigest() == engine["architecture_source_sha256"]
        assert b"llama_model_hy_v3::load_arch_tensors" in cpp
        print("OK pinned llama.cpp hy_v3 architecture source")

    print("PASS metadata preflight; NO full-file integrity, binary-load or GPU verification")


def verify_local_gguf(lock: dict, filename: Path) -> None:
    gguf = lock["gguf"]
    assert filename.is_file(), "Local GGUF file not found"
    actual_size = filename.stat().st_size
    assert actual_size == gguf["size_bytes"], f"GGUF byte length mismatch: {actual_size}"
    with filename.open("rb") as file:
        header = file.read(8192)
        assert gguf_header_from_prefix(header) == gguf["header"]
        file.seek(0)
        sha256 = hashlib.file_digest(file, "sha256").hexdigest()
    assert sha256 == gguf["sha256_from_huggingface_metadata"], "Local GGUF SHA256 mismatch"
    print("PASS full local GGUF SHA256 verified (still no GPU load test)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=LOCK_PATH)
    parser.add_argument("--online", action="store_true",
                        help="Check public pinned metadata and read at most 8 KiB of GGUF")
    parser.add_argument("--deep-header", action="store_true",
                        help="With --online, also inspect Q8_0 GGUF metadata (8 MiB maximum)")
    parser.add_argument("--local-gguf", type=Path,
                        help="Verify full SHA256 of an already downloaded model file")
    args = parser.parse_args()
    lock = load_lock(args.lock)
    print("OK offline lock consistency; GPU readiness:", lock["verification"]["ready_for_real_inference"])
    if args.deep_header and not args.online:
        parser.error("--deep-header requires --online")
    if args.online:
        verify_online(lock, deep_header=args.deep_header)
    if args.local_gguf:
        verify_local_gguf(lock, args.local_gguf)
    if not args.online and args.local_gguf is None:
        print("Use --online for remote preflight; --local-gguf for a full-file hash check")


if __name__ == "__main__":
    main()
