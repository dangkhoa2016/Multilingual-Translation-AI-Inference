"""Bounded GPU scheduling proof: four distinct L40S functions in one Modal App.

No models, volumes, secrets or production routes are mounted. Each independently
scalable function reserves 1 L40S for at most 25 seconds and returns GPU identity.
Default invocation only validates topology without GPU allocation.

  modal run --profile YOUR_PROFILE scripts/models/probe_gpu_capacity.py
  modal run --profile YOUR_PROFILE scripts/models/probe_gpu_capacity.py --run
"""
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import modal

from multilingual_translation_ai_inference.resource_names import MODAL_GPU_INFERENCE_FUNCTION_NAMES

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/four_gpu_capacity.json"
MODEL_KEYS = ("hy_mt2_30b", "index_35b", "gemma4_31b_it", "qwen35_35b")
HOLD_SECONDS = 22
app = modal.App("multilingual-translation-ai-inference-four-l40s-capacity-probe")
image = modal.Image.debian_slim(python_version="3.12").add_local_python_source(
    "multilingual_translation_ai_inference"
)


def inspect_gpu(model_key: str) -> dict:
    import socket

    started = time.time()
    info = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=name,uuid,memory.total", "--format=csv,noheader,nounits"],
        text=True, timeout=20,
    ).strip()
    lines = info.splitlines()
    if len(lines) != 1:
        raise RuntimeError("Expected exactly one GPU per worker")
    parts = [value.strip() for value in lines[0].split(",")]
    if len(parts) != 3 or "L40S" not in parts[0] or int(parts[2]) < 46000:
        raise RuntimeError(f"Expected NVIDIA L40S >= 46000 MiB, found {info}")
    # Hold the GPU long enough to make actual overlapping reservations measurable.
    time.sleep(HOLD_SECONDS)
    finished = time.time()
    return {
        "model_key": model_key,
        "gpu_name": parts[0],
        "gpu_uuid": parts[1],
        "gpu_memory_mib": int(parts[2]),
        "container_hostname": socket.gethostname(),
        "start_unix_seconds": started,
        "end_unix_seconds": finished,
        "hold_seconds": HOLD_SECONDS,
    }


GPU_KWARGS = {
    "gpu": "L40S",
    "image": image,
    "cpu": 1,
    "memory": 512,
    "timeout": 120,
    "min_containers": 0,
    "buffer_containers": 0,
    "max_containers": 1,
    "scaledown_window": 5,
}


@app.function(name=MODAL_GPU_INFERENCE_FUNCTION_NAMES["hy_mt2_30b"] + "_capacity_probe", **GPU_KWARGS)
def hy_mt2_capacity_probe() -> dict:
    return inspect_gpu("hy_mt2_30b")


@app.function(name=MODAL_GPU_INFERENCE_FUNCTION_NAMES["index_35b"] + "_capacity_probe", **GPU_KWARGS)
def index_capacity_probe() -> dict:
    return inspect_gpu("index_35b")


@app.function(name=MODAL_GPU_INFERENCE_FUNCTION_NAMES["gemma4_31b_it"] + "_capacity_probe", **GPU_KWARGS)
def gemma4_capacity_probe() -> dict:
    return inspect_gpu("gemma4_31b_it")


@app.function(name=MODAL_GPU_INFERENCE_FUNCTION_NAMES["qwen35_35b"] + "_capacity_probe", **GPU_KWARGS)
def qwen35_capacity_probe() -> dict:
    return inspect_gpu("qwen35_35b")


def peak_concurrent_intervals(records: list[dict]) -> int:
    events = []
    for entry in records:
        events.extend([(entry["start_unix_seconds"], 1), (entry["end_unix_seconds"], -1)])
    # End is exclusive. Evaluate release events before acquisition at same instant.
    events.sort(key=lambda e: (e[0], e[1]))
    current = maximum = 0
    for _, delta in events:
        current += delta
        maximum = max(maximum, current)
    return maximum


@app.local_entrypoint()
def main(run: bool = False):
    print("Four distinct GPU workers:", ", ".join(MODEL_KEYS))
    print("L40S each; max_containers=1 per worker, min=buffer=0")
    print("Maximum deliberate reservation if all 4 run:", HOLD_SECONDS, "seconds per GPU")
    if not run:
        print("CPU-only dry run complete. Add --run to allocate four billable L40S.")
        return
    calls = [
        hy_mt2_capacity_probe.spawn(),
        index_capacity_probe.spawn(),
        gemma4_capacity_probe.spawn(),
        qwen35_capacity_probe.spawn(),
    ]
    # All four jobs submitted before waiting for any individual result.
    results = modal.FunctionCall.gather(*calls)
    highest = peak_concurrent_intervals(results)
    distinct = len({x["gpu_uuid"] for x in results})
    successful = highest == 4 and distinct == 4
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "four_concurrent_l40s_verified" if successful else "concurrency_not_verified",
        "scope": "CUDA scheduling and GPU identity only; NO model weights loaded",
        "max_concurrent_gpu_reservations_observed": highest,
        "unique_gpu_uuid_count": distinct,
        "instances": results,
        "approx_minimum_gpu_reservation_seconds": HOLD_SECONDS * 4,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "simultaneous": highest,
        "distinct_gpus": distinct,
        "gpu_names": [x["gpu_name"] for x in results],
        "report": str(REPORT),
    }, ensure_ascii=False, indent=2))
    if not successful:
        raise RuntimeError("Four concurrent L40S reservations not demonstrated")
