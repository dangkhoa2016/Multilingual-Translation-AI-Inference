"""One-time official Hy-MT2 Q8_0 weight staging into a Modal Volume.

CPU-only. Never stores weights in Codespaces. No GPU allocated.
Usage: modal run --profile YOUR_MODAL_PROFILE scripts/modal_hy_mt2_stage_weights.py
"""
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import modal

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK_LOCAL = PROJECT_ROOT / "models" / "hy_mt2_30b_q8_0.lock.json"
VOLUME_NAME = "translation-ai-inference-hy-mt2-30b-a3b-gguf-weights"
VOLUME_ROOT = Path("/weights")
VERIFIED_NAME = "hy_mt2_q8_0_verified.json"
app = modal.App("translation-ai-inference-hy-mt2-p3-stage-weights")
volume = modal.Volume.from_name(VOLUME_NAME)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("huggingface_hub==1.33.0", "hf_xet==1.8.0")
    .env({"HF_XET_HIGH_PERFORMANCE": "1", "HF_HUB_DISABLE_PROGRESS_BARS": "1"})
    .add_local_file(LOCK_LOCAL, "/opt/hy_mt2_lock.json")
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=8 * 1024 * 1024) as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@app.function(
    image=image,
    volumes={str(VOLUME_ROOT): volume},
    cpu=4,
    memory=4096,
    timeout=3600,
    min_containers=0,
    buffer_containers=0,
    max_containers=1,
)
def stage_weights() -> dict:
    """Download to the Volume only, verify entire SHA256, commit after success."""
    from huggingface_hub import hf_hub_download

    lock = json.loads(Path("/opt/hy_mt2_lock.json").read_text())
    gguf = lock["gguf"]
    assert lock["model_key"] == "hy_mt2_30b"
    assert not lock["verification"]["ready_for_real_inference"]
    expected_sha = gguf["sha256_from_huggingface_metadata"]
    expected_size = gguf["size_bytes"]
    target = VOLUME_ROOT / gguf["file"]
    marker = VOLUME_ROOT / VERIFIED_NAME
    if marker.exists():
        recorded = json.loads(marker.read_text())
        if (recorded.get("sha256_verified_locally") == expected_sha
                and recorded.get("repo_revision") == gguf["revision"]
                and target.exists() and target.stat().st_size == expected_size):
            print("Verified weights already present; rechecking entire hash before reuse.", flush=True)
            if file_sha256(target) == expected_sha:
                return {"status": "already_verified", "bytes": expected_size, "sha256": expected_sha}
        marker.unlink(missing_ok=True)
    print("CPU download started:", gguf["repository"], gguf["revision"], flush=True)
    started = time.monotonic()
    result = hf_hub_download(
        repo_id=gguf["repository"],
        revision=gguf["revision"],
        filename=gguf["file"],
        local_dir=str(VOLUME_ROOT),
    )
    path = Path(result)
    if path.resolve() != target.resolve():
        raise RuntimeError("Unexpected downloaded path")
    actual_size = path.stat().st_size
    print("Download completed, size:", actual_size, "seconds:", round(time.monotonic() - started, 2), flush=True)
    if actual_size != expected_size:
        raise RuntimeError(f"Size mismatch: expected {expected_size}, received {actual_size}")
    actual_sha = file_sha256(path)
    if actual_sha != expected_sha:
        raise RuntimeError("Full GGUF SHA256 mismatched the pinned official metadata")
    marker.write_text(json.dumps({
        "model": "hy_mt2_30b",
        "repo_revision": gguf["revision"],
        "file_name": gguf["file"],
        "bytes": actual_size,
        "sha256_verified_locally": actual_sha,
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
    }, indent=2) + "\n")
    volume.commit()
    return {
        "status": "verified_and_committed",
        "bytes": actual_size,
        "sha256": actual_sha,
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }


@app.local_entrypoint()
def main() -> None:
    print("Starting CPU-only pinned download; no GPU, one Hy-MT2 Volume.", flush=True)
    result = stage_weights.remote()
    print(json.dumps(result, indent=2))
