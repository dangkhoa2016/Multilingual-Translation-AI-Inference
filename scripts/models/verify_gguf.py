#!/usr/bin/env python3
"""Validate four pinned GGUF models using their shared manifest.

No model weights or GPUs are required for the default offline validation.
Online metadata validation is optional. Deep header validation is available
for the model with a recorded GGUF header in the shared manifest.

  python -m scripts.models.verify_gguf
  python -m scripts.models.verify_gguf --online
  python -m scripts.models.verify_gguf --model hy_mt2_30b --deep-header --online
  python -m scripts.models.verify_gguf --model index_35b --local-gguf /path/model.gguf
"""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

MANIFEST_PATH = (
    Path(__file__).resolve().parents[2] / "models/four_l40s_workers_q8_0_manifest.json"
)


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert set(data["models"]) == {"hy_mt2_30b", "index_35b", "gemma4_31b_it", "qwen35_35b"}
    for model in data["models"].values():
        assert model["quantization"] == "Q8_0"
        assert re.fullmatch(r"[0-9a-f]{40}", model["checkpoint_revision"])
        assert re.fullmatch(r"[0-9a-f]{40}", model["gguf_revision"])
        assert re.fullmatch(r"[0-9a-f]{64}", model["gguf_lfs_sha256"])
        assert model["gguf_size_bytes"] > 30_000_000_000
    spec = data["models"]["hy_mt2_30b"]
    assert spec["source_architecture"] == "hy_v3"
    assert spec["gguf_header"]["architecture"] == "hy_v3"
    assert spec["quantization"] == "Q8_0"
    assert spec["gguf_size_bytes"] > 30_000_000_000
    for revision in ("checkpoint_revision", "gguf_revision"):
        assert re.fullmatch(r"[0-9a-f]{40}", spec[revision])
    assert re.fullmatch(r"[0-9a-f]{40}", data["llama_cpp_revision_hy_mt2_proven"])
    assert re.fullmatch(r"[0-9a-f]{64}", spec["gguf_lfs_sha256"])
    assert re.fullmatch(r"[0-9a-f]{64}", spec["llama_cpp_architecture_source_sha256"])
    assert all(re.fullmatch(r"[0-9a-f]{64}", h)
               for h in spec["source_small_file_sha256"].values())
    assert spec["gguf_metadata_file_type"] == 7
    assert spec["gguf_header"]["magic"] == "GGUF"
    assert spec["gguf_header"]["version"] == 3
    assert spec["gguf_header"]["tensor_count"] > 0
    assert spec["gguf_header"]["metadata_count"] > 0
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


def verify_online(manifest: dict, deep_header: bool = False) -> None:
    import httpx

    spec = manifest["models"]["hy_mt2_30b"]
    src = {
        "repository": spec["checkpoint"],
        "revision": spec["checkpoint_revision"],
        "license": spec["license_on_model_cards"],
        "architecture": spec["source_architecture"],
        "small_file_sha256": spec["source_small_file_sha256"],
    }
    gguf = {
        "repository": spec["gguf_repository"],
        "revision": spec["gguf_revision"],
        "file": spec["gguf_filename"],
        "size_bytes": spec["gguf_size_bytes"],
        "sha256_from_huggingface_metadata": spec["gguf_lfs_sha256"],
        "license": spec["license_on_model_cards"],
        "header": spec["gguf_header"],
        "metadata_file_type": spec["gguf_metadata_file_type"],
    }
    engine = {
        "repository": "ggml-org/llama.cpp",
        "revision": manifest["llama_cpp_revision_hy_mt2_proven"],
        "architecture_source": spec["llama_cpp_architecture_source"],
        "architecture_source_sha256": spec["llama_cpp_architecture_source_sha256"],
    }
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


def verify_local_gguf(spec: dict, filename: Path) -> None:
    assert filename.is_file(), "Local GGUF file not found"
    actual_size = filename.stat().st_size
    assert actual_size == spec["gguf_size_bytes"], f"GGUF byte length mismatch: {actual_size}"
    with filename.open("rb") as file:
        header = file.read(8192)
        if "gguf_header" in spec:
            assert gguf_header_from_prefix(header) == spec["gguf_header"]
        else:
            assert header[:4] == b"GGUF", "Invalid GGUF file magic"
        file.seek(0)
        sha256 = hashlib.file_digest(file, "sha256").hexdigest()
    assert sha256 == spec["gguf_lfs_sha256"], "Local GGUF SHA256 mismatch"
    print("PASS full local GGUF SHA256 verified (still no GPU load test)")


def verify_online_selected(manifest: dict, model_key: str, deep_header: bool) -> None:
    """Check the selected model without downloading its full GGUF file."""
    if model_key == "hy_mt2_30b":
        verify_online(manifest, deep_header=deep_header)
        return
    from scripts.models.verify_manifest import _json_from_hf

    spec = manifest["models"][model_key]
    checkpoint = _json_from_hf(spec["checkpoint"], spec["checkpoint_revision"])
    gguf = _json_from_hf(spec["gguf_repository"], spec["gguf_revision"])
    assert checkpoint["sha"] == spec["checkpoint_revision"]
    assert gguf["sha"] == spec["gguf_revision"]
    assert checkpoint["cardData"]["license"] == spec["license_on_model_cards"]
    assert gguf["cardData"]["license"] == spec["license_on_model_cards"]
    candidates = [
        item for item in gguf["siblings"] if item["rfilename"] == spec["gguf_filename"]
    ]
    assert len(candidates) == 1
    assert candidates[0]["size"] == spec["gguf_size_bytes"]
    assert candidates[0]["lfs"]["sha256"] == spec["gguf_lfs_sha256"]
    print("PASS pinned online metadata:", model_key)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--model", choices=("hy_mt2_30b", "index_35b", "gemma4_31b_it", "qwen35_35b"))
    parser.add_argument("--online", action="store_true",
                        help="Check pinned public metadata without fetching full weights")
    parser.add_argument("--deep-header", action="store_true",
                        help="For Hy-MT2 online checks, read a bounded 8 MiB GGUF header")
    parser.add_argument("--local-gguf", type=Path,
                        help="Check file size and full SHA256 of an already downloaded model")
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    print("OK pinned four-model metadata in shared manifest")
    if args.deep_header and (not args.online or args.model != "hy_mt2_30b"):
        parser.error("--deep-header requires --model hy_mt2_30b --online")
    if args.local_gguf and not args.model:
        parser.error("--local-gguf requires --model to select the expected checksum")
    if args.online:
        if args.model:
            verify_online_selected(manifest, args.model, args.deep_header)
        else:
            from scripts.models.verify_manifest import verify_online
            verify_online(manifest)
    if args.local_gguf:
        verify_local_gguf(manifest["models"][args.model], args.local_gguf)
    if not args.online and args.local_gguf is None:
        print("Use --online for pinned metadata or --model KEY --local-gguf for full SHA256")


if __name__ == "__main__":
    main()
