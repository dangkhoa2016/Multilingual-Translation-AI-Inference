#!/usr/bin/env python3
"""Inspect public Hugging Face metadata. Never download model weights.

Usage:
    pip install huggingface_hub
    python scripts/verify_hf_metadata.py --output model-lock.candidate.json

This produces a *candidate* lock only. Validate SHA256 after actual download.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MODELS = {
    "hy_mt2_30b": {
        "checkpoint": "tencent/Hy-MT2-30B-A3B",
        "gguf_repo": "tencent/Hy-MT2-30B-A3B-GGUF",
        "gguf_file": "Hy-MT2-30B-A3B-Q8_0.gguf",
    },
    "index_35b": {
        "checkpoint": "IndexTeam/Index-Translate-35B-A3B-preview",
        "gguf_repo": "IndexTeam/Index-Translate-35B-A3B-preview-GGUF",
        "gguf_file": "Index-Translate-35B-A3B-preview.Q8_0.gguf",
    },
    "gemma4_31b_it": {
        "checkpoint": "google/gemma-4-31B-it",
        "gguf_repo": "unsloth/gemma-4-31B-it-GGUF",
        "gguf_file": "gemma-4-31B-it-Q8_0.gguf",
    },
    "qwen35_35b": {
        "checkpoint": "Qwen/Qwen3.5-35B-A3B",
        "gguf_repo": "unsloth/Qwen3.5-35B-A3B-GGUF",
        "gguf_file": "Qwen3.5-35B-A3B-Q8_0.gguf",
    },
}


def _get_lfs_sha256(lfs: Any) -> str | None:
    """Support both old dicts and current huggingface_hub BlobLfsInfo."""
    if not lfs:
        return None
    value = lfs.get("sha256") if isinstance(lfs, dict) else getattr(lfs, "sha256", None)
    if isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in value):
        return value.lower()
    return None


def inspect_one(api: Any, model_key: str, spec: dict[str, str]) -> dict[str, Any]:
    """Never read file bytes. Verify both source and GGUF revisions with metadata."""
    source = api.model_info(spec["checkpoint"], files_metadata=False)
    gguf = api.model_info(spec["gguf_repo"], files_metadata=True)
    source_sha = getattr(source, "sha", None)
    gguf_sha = getattr(gguf, "sha", None)
    if not source_sha or not gguf_sha:
        raise ValueError(f"Missing source/GGUF commit SHA for {model_key}")

    # Lock the listed commit while reading the tree: avoid changes to main during inspection.
    files = api.list_repo_tree(spec["gguf_repo"], revision=gguf_sha, recursive=True, expand=True)
    target = next((item for item in files if getattr(item, "path", "") == spec["gguf_file"]), None)
    if target is None:
        raise ValueError(f"GGUF filename not found at pinned revision: {spec['gguf_repo']} / {spec['gguf_file']}")

    gguf_license = getattr(gguf, "card_data", None)
    gguf_license = (gguf_license or {}).get("license") if isinstance(gguf_license, dict) else getattr(gguf_license, "license", None)
    source_license = getattr(source, "card_data", None)
    source_license = (source_license or {}).get("license") if isinstance(source_license, dict) else getattr(source_license, "license", None)
    file_sha256 = _get_lfs_sha256(getattr(target, "lfs", None))

    return {
        "model_key": model_key,
        "checkpoint": {"repo": spec["checkpoint"], "revision": source_sha, "license_metadata": source_license},
        "gguf": {
            "repo": spec["gguf_repo"],
            "revision": gguf_sha,
            "file": spec["gguf_file"],
            "quant": "Q8_0",
            "size_bytes": getattr(target, "size", None),
            "sha256_from_hf_metadata": file_sha256,
            "license_metadata": gguf_license,
        },
        "verified_content_hash_on_downloaded_file": False,
        "gpu_smoke_passed": False,
        "ready_for_gpu_deploy": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("model-lock.candidate.json"))
    args = parser.parse_args()

    try:
        from huggingface_hub import HfApi
    except ImportError as exc:
        parser.error(f"Missing dependency: {exc}; install huggingface_hub")

    api = HfApi()
    result = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "metadata-only, no weight downloads or GPU verification",
        "models": {},
        "errors": {},
    }
    for model_key, spec in MODELS.items():
        try:
            model = inspect_one(api, model_key, spec)
            result["models"][model_key] = model
            hash_status = "SHA256(metadata) available" if model["gguf"]["sha256_from_hf_metadata"] else "SHA256(metadata) unavailable"
            print(f"OK {model_key}: {model['gguf']['revision'][:12]} — {hash_status}")
        except Exception as exc:
            result["errors"][model_key] = f"{type(exc).__name__}: {exc}"
            print(f"ERROR {model_key}: {exc}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Candidate lock written: {args.output}")
    return 1 if result["errors"] or len(result["models"]) != len(MODELS) else 0


if __name__ == "__main__":
    raise SystemExit(main())
