"""Authenticated real-GPU API smoke; no token or translated content is logged.

Required environment: TRANSLATION_API_BEARER_TOKEN (load existing .env).
Run without --run to inspect; --run makes one billable GPU request.
--all-models runs a 4-GPU benchmark through POST /v1/jobs/benchmarks.

  set -a; source .env; set +a
  python scripts/api/smoke_gpu.py
  python scripts/api/smoke_gpu.py --run --base-url HTTPS_GATEWAY
  python scripts/api/smoke_gpu.py --run --all-models --base-url HTTPS_GATEWAY
"""
import argparse
import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from multilingual_translation_ai_inference.model_registry import MODEL_REGISTRY
from multilingual_translation_ai_inference.private_reports import save_private_report as _save_private_report

ROOT = Path(__file__).resolve().parents[2]
MODELS = tuple(MODEL_REGISTRY)
SHORT_TEXT = "The little fox crossed the wooden bridge at sunrise."
LONG_TEXT = (
    "In October the archivist opened a chest containing a wooden lantern, a "
    "small map and a notebook. The bridge was closed, and the workers were "
    "not allowed to replace the wooden lantern with a blue notebook. "
    "They left the notebook inside the old wooden house. "
) * 3


def save_private_report(report: dict, *, temp_parent: str | None = None,
                        filename: str | None = None) -> Path:
    name = filename if filename is not None else (
        "gpu_api_four_model_benchmark.json" if report["all_models"] else "gpu_api_translation.json"
    )
    return _save_private_report(report, filename=name, repository_root=ROOT,
                                temp_parent=temp_parent or tempfile.gettempdir())

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("TRANSLATION_GATEWAY_BASE_URL"),
                        help="HTTPS URL of your currently deployed CPU gateway")
    parser.add_argument("--run", action="store_true", help="Submit real GPU request")
    parser.add_argument("--all-models", action="store_true", help="Route to all 4 GPUs")
    parser.add_argument("--max-wait-seconds", type=int, default=300)
    args = parser.parse_args()
    print("Authenticated Modal gateway GPU smoke, 4 registered model keys.")
    if not args.run:
        print("Dry-run only. --run enables one real paid GPU request.")
        return
    base_url = (args.base_url or "").rstrip("/")
    if not base_url.startswith("https://"):
        raise RuntimeError("Set --base-url or TRANSLATION_GATEWAY_BASE_URL to the HTTPS gateway")
    token = os.environ.get("TRANSLATION_API_BEARER_TOKEN")
    if not token:
        raise RuntimeError("Bearer token missing in environment")
    if args.max_wait_seconds < 60:
        raise ValueError("max-wait-seconds must be >=60")
    auth = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=40, follow_redirects=False) as client:
        health = client.get(base_url + "/health")
        health.raise_for_status()
        h = health.json()
        if h.get("inference_enabled") is not True or h.get("phase") != "gpu":
            raise RuntimeError("Production GPU dispatch is not enabled")
        unauthorized = client.get(base_url + "/v1/models")
        if unauthorized.status_code != 401:
            raise RuntimeError("Public models endpoint is not protected")
        models_result = client.get(base_url + "/v1/models", headers=auth)
        models_result.raise_for_status()
        models = models_result.json()["models"]
        if (set(m["key"] for m in models) != set(MODELS)
                or not all(m["enabled"] and m["runtime_verified"] for m in models)):
            raise RuntimeError("Published real model registry is not fully active")
        start = time.monotonic()
        all_models = args.all_models
        payload = {
            "source_language": "en", "target_language": "vi",
            "text": LONG_TEXT if all_models else SHORT_TEXT,
            "options": {"preserve_formatting": True},
        }
        if all_models:
            payload["models"] = list(MODELS)
            path = "/v1/jobs/benchmarks"
        else:
            payload["model"] = "hy_mt2_30b"
            path = "/v1/jobs/translations"
        key = "real-gpu-api-smoke-" + uuid4().hex
        idempotent = {**auth, "Idempotency-Key": key}
        response = client.post(base_url + path, json=payload, headers=idempotent)
        if response.status_code != 202:
            raise RuntimeError(f"GPU job POST returned unexpected HTTP {response.status_code}")
        job_id = response.json()["job_id"]
        repeated = client.post(base_url + path, json=payload, headers=idempotent)
        if repeated.status_code != 202 or repeated.json()["job_id"] != job_id:
            raise RuntimeError("Idempotency repeated POST did not reuse existing job")
        deadline = time.monotonic() + args.max_wait_seconds
        runs = []
        latest_status = None
        while time.monotonic() < deadline:
            response = client.get(base_url + "/v1/jobs/" + job_id, headers=auth)
            response.raise_for_status()
            data = response.json()
            runs = data["runs"]
            latest_status = data["status"]
            if all(r["status"] in ("completed", "failed", "dispatch_uncertain",
                                  "execution_uncertain") for r in runs):
                break
            time.sleep(3)
        expected = 4 if all_models else 1
        passed = (
            len(runs) == expected and latest_status == "completed"
            and all(r["status"] == "completed" and
                    r["is_mock_result"] is False and
                    isinstance(r["translation_text"], str) and
                    r["translation_text"].strip() for r in runs)
        )
        report = {
            "tested_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "real_gpu_api_passed" if passed else "real_gpu_api_failed",
            "scope": "Real production POST -> Modal GPU -> PostgreSQL -> authenticated GET",
            "all_models": all_models,
            "input_codepoints": len(payload["text"]),
            "elapsed_seconds": round(time.monotonic() - start, 3),
            "runs": [{
                "model": r["model"],
                "status": r["status"],
                "is_mock_result": r["is_mock_result"],
                "translation_codepoints": len(r["translation_text"] or ""),
                "translation_sha256": hashlib.sha256(
                    (r["translation_text"] or "").encode("utf-8")).hexdigest(),
                "error_code": r["error_code"],
            } for r in runs],
        }
        path = save_private_report(report)
        print(json.dumps({
            "status": report["status"],
            "runs": {x["model"]: x["status"] for x in report["runs"]},
            "elapsed_seconds": report["elapsed_seconds"],
            "report": str(path),
        }, indent=2))
        if not passed:
            raise RuntimeError("Real GPU API smoke did not pass")


if __name__ == "__main__":
    main()
