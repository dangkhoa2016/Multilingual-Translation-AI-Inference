"""Bounded Modal GPU container reuse probe, never a public HTTP endpoint.

This requests the deployed Hy-MT2 worker's *readiness* twice in quick
succession, compares model identity/GPU UUID, and records call durations.
It does NOT translate source text or create PostgreSQL jobs.

The first call MAY be cold, but the probe cannot guarantee a cold start;
its timing alone is not evidence of model load latency. The second call
tests warm reuse if both calls land on the same GPU UUID.

Only the equality result is saved; raw device identifiers stay in memory.
The runtime summary is private and never overwrites archived reports/ evidence.

  PYTHONPATH=src python scripts/api/container_reuse.py
  PYTHONPATH=src python scripts/api/container_reuse.py --run
"""
import argparse
import time
from datetime import datetime, timezone

import modal

from multilingual_translation_ai_inference.resource_names import (
    MODAL_APP_NAME,
    MODAL_GPU_INFERENCE_CLASS_NAMES,
)

if __package__:
    from .smoke_gpu import save_private_report
else:
    from smoke_gpu import save_private_report

MODEL_KEY = "hy_mt2_30b"


def validate_readiness(data: dict) -> None:
    if (data.get("model") != MODEL_KEY or data.get("model_loaded") is not True
            or data.get("single_GPU") is not True or "L40S" not in data.get("gpu", "")
            or not data.get("gpu_uuid") or data.get("ready_seconds", -1) <= 0):
        raise RuntimeError("Deployed Hy-MT2 class returned invalid readiness")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    name = MODAL_GPU_INFERENCE_CLASS_NAMES[MODEL_KEY]
    print("App:", MODAL_APP_NAME, "GPU Class:", name)
    if not args.run:
        print("No GPUs started. Add --run to request paid readiness twice.")
        return

    worker = modal.Cls.from_name(MODAL_APP_NAME, name)()
    measurements = []
    for idx in range(2):
        started = time.perf_counter()
        ready = worker.readiness.remote()
        latency = round(time.perf_counter() - started, 3)
        validate_readiness(ready)
        measurements.append({
            "call": idx + 1, "rpc_wall_seconds": latency,
            "model": ready["model"], "gpu_uuid": ready["gpu_uuid"],
            "model_initialization_seconds": ready["ready_seconds"],
            "sampled_vram_mib": ready["sampled_vram_mib"],
        })
        print(f"readiness #{idx + 1} passed; RPC {latency}s")
    same_gpu = measurements[0].pop("gpu_uuid") == measurements[1].pop("gpu_uuid")
    report = {
        "tested_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Two sequential deployed class readiness RPC calls, not inference throughput",
        "status": "two_readiness_calls_passed",
        "same_gpu_uuid": same_gpu,
        "warm_container_reuse_observed": same_gpu,
        "first_call_cold_start_guaranteed": False,
        "measurements": measurements,
        "note": "The first call can already be warm. Same GPU UUID on immediate "
                "sequential calls supports reuse but does not guarantee future routing.",
    }
    report_path = save_private_report(report, filename="gpu_container_reuse.json")
    print("Same L40S GPU UUID:", same_gpu)
    print("Report:", report_path)


if __name__ == "__main__":
    main()
