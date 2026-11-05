"""Explicit deployed-class readiness smoke: four model GPUs, real pinned Volumes.

No HTTP URL, PostgreSQL job or credentials are passed to a GPU. The Modal
account's authenticated CLI profile is required. --run starts paid GPUs.
By default, print expected classes without requesting any GPU.

  python scripts/deployment/verify_gpu_workers.py
  python scripts/deployment/verify_gpu_workers.py --run

Runtime summaries use unique restricted directories outside Git and omit live
job/device identifiers. Archived JSON evidence remains unchanged.

"""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import modal

from multilingual_translation_ai_inference.private_reports import save_private_report
from multilingual_translation_ai_inference.resource_names import (
    MODAL_APP_NAME,
    MODAL_GPU_INFERENCE_CLASS_NAMES,
)

ROOT = Path(__file__).resolve().parents[2]


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
        except Exception:
            errors[model] = {"error_code": "READINESS_RPC_FAILED"}
    correct = (
        not errors
        and set(results) == set(MODAL_GPU_INFERENCE_CLASS_NAMES)
        and len({x["gpu_uuid"] for x in results.values()}) == 4
        and all(x["model"] == key and x["model_loaded"] is True
                and "L40S" in x["gpu"] for key, x in results.items())
    )
    # Use GPU identities only for the in-memory distinctness check.
    # Whitelist summary fields instead of serializing arbitrary worker payloads.
    safe_results = {
        model: {"model_matches": value.get("model") == model,
                "model_loaded": value.get("model_loaded") is True,
                "gpu_is_l40s": "L40S" in value.get("gpu", "")}
        for model, value in results.items()
    }
    report = {
        "tested_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "four_deployed_gpu_classes_ready" if correct else "readiness_failed",
        "scope": "Deployed GPU Cls model load and health, not translation job dispatch",
        "app_name": MODAL_APP_NAME,
        "elapsed_rpc_seconds": round(time.monotonic() - started, 3),
        "results": safe_results,
        "distinct_gpu_count": len({x["gpu_uuid"] for x in results.values()}),
        "errors": errors,
    }
    report_path = save_private_report(report, filename="deployed_gpu_readiness.json", repository_root=ROOT)
    print(json.dumps({
        "status": report["status"],
        "ready_models": sorted(results),
        "distinct_gpu_uuids": len({x["gpu_uuid"] for x in results.values()}),
        "error_models": sorted(errors),
        "report": str(report_path),
    }, indent=2))
    if not correct:
        raise SystemExit("Deployed GPU class readiness verification failed")


if __name__ == "__main__":
    main()
