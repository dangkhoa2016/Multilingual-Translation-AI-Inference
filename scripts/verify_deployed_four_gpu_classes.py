"""Explicit deployed-class readiness smoke: four model GPUs, real pinned Volumes.

No HTTP URL, PostgreSQL job or credentials are passed to a GPU. The Modal
account's authenticated CLI profile is required. --run starts paid GPUs.
By default, print expected classes without requesting any GPU.

  python scripts/verify_deployed_four_gpu_classes.py
  python scripts/verify_deployed_four_gpu_classes.py --run
"""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import modal

from translation_ai_inference.resource_names import (
    MODAL_APP_NAME,
    MODAL_GPU_INFERENCE_CLASS_NAMES,
)

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "reports/deployed_gpu_readiness.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Allocate 4 billable L40S GPUs")
    args = parser.parse_args()
    print("App:", MODAL_APP_NAME)
    for key, cls_name in MODAL_GPU_INFERENCE_CLASS_NAMES.items():
        print("Model:", key, "deployed Modal class:", cls_name)
    if not args.run:
        print("Dry run only; add --run to allocate GPUs.")
        return
    started = time.monotonic()
    calls = {}
    for model, cls_name in MODAL_GPU_INFERENCE_CLASS_NAMES.items():
        gpu_class = modal.Cls.from_name(MODAL_APP_NAME, cls_name)
        calls[model] = gpu_class().readiness.spawn()
    results, errors = {}, {}
    for model, call in calls.items():
        try:
            results[model] = call.get(timeout=450)
        except Exception as exc:
            errors[model] = {
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:350],
            }
    correct = (
        not errors
        and set(results) == set(MODAL_GPU_INFERENCE_CLASS_NAMES)
        and len({x["gpu_uuid"] for x in results.values()}) == 4
        and all(x["model"] == key and x["model_loaded"] is True
                and "L40S" in x["gpu"] for key, x in results.items())
    )
    report = {
        "tested_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "four_deployed_gpu_classes_ready" if correct else "readiness_failed",
        "scope": "Deployed GPU Cls model load and health, not translation job dispatch",
        "app_name": MODAL_APP_NAME,
        "elapsed_rpc_seconds": round(time.monotonic() - started, 3),
        "results": results,
        "errors": errors,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "status": report["status"],
        "ready_models": sorted(results),
        "distinct_gpu_uuids": len({x["gpu_uuid"] for x in results.values()}),
        "error_models": sorted(errors),
        "report": str(REPORT_PATH),
    }, indent=2))
    if not correct:
        raise SystemExit("Deployed GPU class readiness verification failed")


if __name__ == "__main__":
    main()
