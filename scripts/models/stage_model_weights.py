"""CPU-only checksum-verified weight staging for all four model backends.

One model and one Volume per invocation; no download to Codespaces or GPU.
No staging without explicit --stage and --model.

  modal run --profile YOUR_MODAL_PROFILE scripts/models/stage_model_weights.py
  modal run --profile YOUR_MODAL_PROFILE scripts/models/stage_model_weights.py \
      --model index_35b --stage
"""
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import modal

from multilingual_translation_ai_inference.resource_names import (
    MODAL_GPU_WEIGHT_VOLUME_NAMES,
    MODAL_HUGGINGFACE_DOWNLOAD_SECRET_NAME,
)

IMAGE_MANIFEST = "/opt/four_l40s_workers_q8_0_manifest.json"
# File-mode Modal entrypoints are imported as /root/stage_model_weights.py.
# Only the local process has the repository layout; remote tasks use the
# manifest explicitly mounted into their image.
MANIFEST = (Path(__file__).resolve().parents[2] / "models/four_l40s_workers_q8_0_manifest.json"
            if modal.is_local() else Path(IMAGE_MANIFEST))
VOL_ROOT = Path("/weights")
def marker_filename(model_key: str) -> str:
    """Preserve the marker layout already expected by the deployed runtimes."""
    return "hy_mt2_q8_0_verified.json" if model_key == "hy_mt2_30b" else "verified_gguf_q8_0.json"
app = modal.App("multilingual-translation-ai-inference-staging-q8-0-weights")
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("huggingface_hub==1.33.0", "hf_xet==1.8.0")
    .env({"HF_XET_HIGH_PERFORMANCE": "1", "HF_HUB_DISABLE_PROGRESS_BARS": "1"})
    .add_local_python_source("multilingual_translation_ai_inference")
)
if modal.is_local():
    image = image.add_local_file(MANIFEST, IMAGE_MANIFEST)
VOLUMES = {
    key: modal.Volume.from_name(name)
    for key, name in MODAL_GPU_WEIGHT_VOLUME_NAMES.items()
}
WORKERS = tuple(VOLUMES)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=8 * 1024 * 1024) as fp:
        for block in iter(lambda: fp.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def perform_cpu_staging(model_key: str) -> dict:
    from huggingface_hub import hf_hub_download

    specs = json.loads(Path(IMAGE_MANIFEST).read_text())["models"]
    if model_key not in WORKERS:
        raise ValueError("Unknown model key")
    spec = specs[model_key]
    output = VOL_ROOT / spec["gguf_filename"]
    marker_path = VOL_ROOT / marker_filename(model_key)
    sha = spec["gguf_lfs_sha256"]
    expected_size = spec["gguf_size_bytes"]
    if marker_path.exists() and output.exists():
        marker = json.loads(marker_path.read_text())
        if (marker.get("sha256_verified_locally") == sha and
                marker.get("repo_revision") == spec["gguf_revision"] and
                output.stat().st_size == expected_size):
            print("Existing verified file: recomputing full local SHA256", flush=True)
            if sha256_file(output) == sha:
                return {"status": "already_verified", "model": model_key,
                        "bytes": expected_size, "sha256": sha}
        marker_path.unlink(missing_ok=True)
    started = time.monotonic()
    print("Downloading:", model_key, spec["gguf_filename"],
          "bytes:", expected_size, "CPU-only", flush=True)
    result = hf_hub_download(
        repo_id=spec["gguf_repository"],
        revision=spec["gguf_revision"],
        filename=spec["gguf_filename"],
        local_dir=str(VOL_ROOT),
        token=True,  # Require the HF_TOKEN supplied only to CPU staging.
    )
    saved = Path(result)
    if saved.resolve() != output.resolve():
        raise RuntimeError("Downloaded file outside expected weight path")
    if output.stat().st_size != expected_size:
        raise RuntimeError("Downloaded weight length mismatch")
    actual = sha256_file(output)
    if actual != sha:
        raise RuntimeError("Downloaded weight SHA256 mismatch; refusing to commit")
    marker_path.write_text(json.dumps({
        "schema_version": 1,
        "model_key": model_key,
        "gguf_repository": spec["gguf_repository"],
        "repo_revision": spec["gguf_revision"],
        "file_name": spec["gguf_filename"],
        "bytes": expected_size,
        "sha256_verified_locally": actual,
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
    }, indent=2) + "\n")
    VOLUMES[model_key].commit()
    return {"status": "verified_and_committed", "model": model_key,
            "bytes": expected_size, "sha256": actual,
            "download_verify_seconds": round(time.monotonic() - started, 3)}


HUGGINGFACE_DOWNLOAD_SECRET = modal.Secret.from_name(
    MODAL_HUGGINGFACE_DOWNLOAD_SECRET_NAME, required_keys=["HF_TOKEN"]
)

CPU_ARGS = {
    "image": image,
    "secrets": [HUGGINGFACE_DOWNLOAD_SECRET],
    "cpu": 4,
    "memory": 8192,
    "timeout": 3600,
    "min_containers": 0,
    "buffer_containers": 0,
    "max_containers": 1,
}


@app.function(volumes={"/weights": VOLUMES["hy_mt2_30b"]}, **CPU_ARGS)
def stage_hy_mt2() -> dict:
    return perform_cpu_staging("hy_mt2_30b")


@app.function(volumes={"/weights": VOLUMES["index_35b"]}, **CPU_ARGS)
def stage_index() -> dict:
    return perform_cpu_staging("index_35b")


@app.function(volumes={"/weights": VOLUMES["gemma4_31b_it"]}, **CPU_ARGS)
def stage_gemma() -> dict:
    return perform_cpu_staging("gemma4_31b_it")


@app.function(volumes={"/weights": VOLUMES["qwen35_35b"]}, **CPU_ARGS)
def stage_qwen() -> dict:
    return perform_cpu_staging("qwen35_35b")


@app.local_entrypoint()
def main(model: str = "", stage: bool = False):
    if not model:
        if stage:
            raise ValueError("Select one model with --model before using --stage")
        print("Available model keys:", ", ".join(WORKERS))
        print("Select --model KEY and optionally --stage for CPU-only staging")
        return
    if model not in WORKERS:
        raise ValueError("Unknown model key")
    spec = json.loads(MANIFEST.read_text())["models"][model]
    print("Selected", model, spec["gguf_size_bytes"], "bytes", "Volume", spec["modal_volume_name"])
    print("Persistent Volume storage is billed independently from GPU usage.")
    if not stage:
        print("No paid CPU download started. Add --stage to run.")
        return
    function = {
        "hy_mt2_30b": stage_hy_mt2,
        "index_35b": stage_index,
        "gemma4_31b_it": stage_gemma,
        "qwen35_35b": stage_qwen,
    }[model]
    result = function.remote()
    print(json.dumps(result, indent=2))
