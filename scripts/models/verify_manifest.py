"""Verify immutable four-worker GGUF metadata (no model download, no GPU).

  python scripts/models/verify_manifest.py
  python scripts/models/verify_manifest.py --online
"""
import argparse
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from multilingual_translation_ai_inference.resource_names import (
    MODAL_GPU_INFERENCE_CLASS_NAMES,
    MODAL_GPU_INFERENCE_FUNCTION_NAMES,
    MODAL_GPU_WEIGHT_VOLUME_NAMES,
)

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "models/four_l40s_workers_q8_0_manifest.json"
EXPECTED_KEYS = ("hy_mt2_30b", "index_35b", "gemma4_31b_it", "qwen35_35b")


def load_manifest():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert tuple(data["models"]) == EXPECTED_KEYS
    weights = []
    functions = []
    for key, model in data["models"].items():
        assert model["quantization"] == "Q8_0"
        assert re.fullmatch(r"[a-f0-9]{40}", model["checkpoint_revision"])
        assert re.fullmatch(r"[a-f0-9]{40}", model["gguf_revision"])
        assert re.fullmatch(r"[a-f0-9]{64}", model["gguf_lfs_sha256"])
        assert model["gguf_size_bytes"] > 30_000_000_000
        assert "/" not in model["gguf_filename"] and model["gguf_filename"].endswith(".gguf")
        assert model["modal_volume_name"] == MODAL_GPU_WEIGHT_VOLUME_NAMES[key]
        assert model["modal_function_name"] == MODAL_GPU_INFERENCE_FUNCTION_NAMES[key]
        assert model["gpu"] == "L40S"
        assert model["min_containers"] == model["buffer_containers"] == 0
        assert model["max_containers"] == 1
        assert model["production_worker_registered"] is True
        assert model["deployed_modal_class_name"] == MODAL_GPU_INFERENCE_CLASS_NAMES[key]
        weights.append(model["modal_volume_name"])
        functions.append(model["modal_function_name"])
    assert len(set(weights)) == len(set(functions)) == 4
    # Independent GPU instances; 1 shared code repository.
    assert len(set(x["gguf_repository"] for x in data["models"].values())) == 4
    return data


def _json_from_hf(repo, revision):
    url = f"https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true"
    request = urllib.request.Request(
        url, headers={"User-Agent": "Multilingual-Translation-AI-Inference-Metadata-Check/1.0"}
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        body = response.read(2 * 1024 * 1024 + 1)
    if len(body) > 2 * 1024 * 1024:
        raise ValueError("Unexpected oversized HF model API response")
    return json.loads(body)


def verify_online(data):
    for key, spec in data["models"].items():
        checkpoint = _json_from_hf(spec["checkpoint"], spec["checkpoint_revision"])
        assert checkpoint["sha"] == spec["checkpoint_revision"]
        assert checkpoint["cardData"]["license"] == spec["license_on_model_cards"]
        assert checkpoint.get("gated", False) in (False, None)
        gguf = _json_from_hf(spec["gguf_repository"], spec["gguf_revision"])
        assert gguf["sha"] == spec["gguf_revision"]
        assert gguf["cardData"]["license"] == spec["license_on_model_cards"]
        candidates = [
            x for x in gguf["siblings"] if x["rfilename"] == spec["gguf_filename"]
        ]
        assert len(candidates) == 1
        match = candidates[0]
        assert match["size"] == spec["gguf_size_bytes"]
        assert match["lfs"]["size"] == spec["gguf_size_bytes"]
        assert match["lfs"]["sha256"] == spec["gguf_lfs_sha256"]
        print("OK", key, "pinned revision, file, size, LFS SHA256, license")
    print("PASS: four pinned metadata records. No full GGUF download or GPU load.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--online", action="store_true")
    args = parser.parse_args()
    manifest = load_manifest()
    total = sum(s["gguf_size_bytes"] for s in manifest["models"].values())
    print("Validated 4 independent L40S worker resources; total Q8 size:",
          round(total / 1024**3, 3), "GiB")
    if args.online:
        verify_online(manifest)
    else:
        print("CPU offline validation only. Add --online for pinned HF source comparison.")


if __name__ == "__main__":
    main()
