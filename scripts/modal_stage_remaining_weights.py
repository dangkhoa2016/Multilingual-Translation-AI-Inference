"""Opt-in CPU-only pinned GGUF staging for Index, Gemma 4 and Qwen3.5.

One model/Volume per invocation; never downloads to Codespaces, never uses GPUs.
No staging without explicit --stage and --model.

  modal run --profile YOUR_MODAL_PROFILE scripts/modal_stage_remaining_weights.py
  modal run --profile YOUR_MODAL_PROFILE scripts/modal_stage_remaining_weights.py \
      --model index_35b --stage
"""
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "models/four_l40s_workers_q8_0_manifest.json"
VOL_ROOT = Path("/weights")
MARKER = "verified_gguf_q8_0.json"
IMAGE_MANIFEST = "/opt/four_l40s_workers_q8_0_manifest.json"
app = modal.App("translation-ai-inference-staging-q8-0-weights")
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("huggingface_hub==1.33.0", "hf_xet==1.8.0")
    .env({"HF_XET_HIGH_PERFORMANCE": "1", "HF_HUB_DISABLE_PROGRESS_BARS": "1"})
    .add_local_file(MANIFEST, IMAGE_MANIFEST)
)
VOLUMES = {
    "index_35b": modal.Volume.from_name(
        "translation-ai-inference-index-35b-a3b-preview-gguf-weights"),
    "gemma4_31b_it": modal.Volume.from_name(
        "translation-ai-inference-gemma-4-31b-it-gguf-weights"),
    "qwen35_35b": modal.Volume.from_name(
        "translation-ai-inference-qwen-3-5-35b-a3b-gguf-weights"),
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
        raise ValueError("Only three previously unstaged GGUF files allowed")
    spec = specs[model_key]
    output = VOL_ROOT / spec["gguf_filename"]
    marker_path = VOL_ROOT / MARKER
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


CPU_ARGS = {
    "image": image,
    "cpu": 4,
    "memory": 8192,
    "timeout": 3600,
    "min_containers": 0,
    "buffer_containers": 0,
    "max_containers": 1,
}


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
def main(model: str = "index_35b", stage: bool = False):
    if model not in WORKERS:
        raise ValueError("Unknown model key")
    spec = json.loads(MANIFEST.read_text())["models"][model]
    print("Selected", model, spec["gguf_size_bytes"], "bytes", "Volume", spec["modal_volume_name"])
    print("Persistent Volume storage is billed independently from GPU usage.")
    if not stage:
        print("No paid CPU download started. Add --stage to run.")
        return
    function = {
        "index_35b": stage_index,
        "gemma4_31b_it": stage_gemma,
        "qwen35_35b": stage_qwen,
    }[model]
    result = function.remote()
    print(json.dumps(result, indent=2))
