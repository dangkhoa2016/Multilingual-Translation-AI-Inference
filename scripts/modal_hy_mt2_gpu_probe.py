"""One-shot, low-cost GPU entitlement and memory probe for the Hy-MT2 smoke.

Does NOT mount weights, create volumes, download model files, or deploy the API.
Use: modal run --profile YOUR_MODAL_PROFILE scripts/modal_hy_mt2_gpu_probe.py
"""
import json
import subprocess

import modal

app = modal.App("translation-ai-inference-hy-mt2-p3-gpu-probe")


@app.function(
    gpu="L40S",
    image=modal.Image.debian_slim(python_version="3.12"),
    cpu=1.0,
    memory=512,
    min_containers=0,
    buffer_containers=0,
    max_containers=1,
    timeout=90,
)
def gpu_probe() -> dict:
    command = [
        "nvidia-smi", "--query-gpu=name,memory.total,memory.free,compute_cap,driver_version",
        "--format=csv,noheader,nounits",
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=25)
    lines = [row.strip() for row in result.stdout.splitlines() if row.strip()]
    if len(lines) != 1:
        raise RuntimeError("Expected exactly one GPU")
    parts = [value.strip() for value in lines[0].split(",")]
    if len(parts) != 5 or "L40S" not in parts[0]:
        raise RuntimeError("Not a single NVIDIA L40S: " + repr(lines))
    return {
        "gpu_name": parts[0],
        "memory_total_mib": int(parts[1]),
        "memory_free_mib": int(parts[2]),
        "compute_capability": parts[3],
        "driver_version": parts[4],
    }


@app.local_entrypoint()
def main() -> None:
    print("GPU probe only, no model or Volume attached")
    result = gpu_probe.remote()
    print(json.dumps(result, indent=2))
