"""Opt-in four-model real GPU job integration test using production DB and Modal.

This is NOT a public API submission; the active gateway remains mock-only.
It writes one identifiable benchmark test job into the existing PostgreSQL DB
and sends four claimed runs to the deployed GPU classes using the production
ModalGpuDispatcher. Polls status via the same authenticated API GET route.
The resulting text is not printed or committed, only verified as nonmock.

Run after sourcing your existing .env (do not echo its credentials):
  set -a; source .env; set +a
  PYTHONPATH=src python scripts/api/smoke_dispatch.py
  PYTHONPATH=src python scripts/api/smoke_dispatch.py --run --base-url HTTPS_GATEWAY

Runtime summaries use unique restricted directories outside Git and omit live
job/device identifiers. Archived JSON evidence remains unchanged.

"""
import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from multilingual_translation_ai_inference.database import make_engine, make_session_factory
from multilingual_translation_ai_inference.dispatcher import ModalGpuDispatcher, dispatch_queued_runs
from multilingual_translation_ai_inference.model_registry import MODEL_REGISTRY
from multilingual_translation_ai_inference.private_reports import save_private_report
from multilingual_translation_ai_inference.repository import JobRepository, summarize_run_states
from multilingual_translation_ai_inference.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
PARAGRAPH = (
    "At dawn, the village archivist opened a wooden box containing a silver "
    "compass, a blue notebook, and a letter dated 17 October. The letter said "
    "that the bridge remained closed until repairs finished. Nobody was "
    "allowed to replace the wooden lantern with a blue notebook. "
)
SOURCE = (PARAGRAPH * 3 + "The caretaker, Lam, checked everything twice.").strip()


def check_gateway_read(auth_token: str, job_id: str, base_url: str) -> dict:
    req = urllib.request.Request(
        base_url + f"/v1/jobs/{job_id}",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    with urllib.request.urlopen(req, timeout=35) as response:
        if response.status != 200:
            raise RuntimeError("Gateway GET did not return HTTP 200")
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("TRANSLATION_GATEWAY_BASE_URL"),
                        help="HTTPS URL of your currently deployed CPU gateway")
    parser.add_argument("--run", action="store_true", help="Submit 4 real GPU inference jobs")
    parser.add_argument("--max-wait-seconds", type=int, default=300)
    args = parser.parse_args()
    print("Four-model PostgreSQL/Modal integration, input code points:", len(SOURCE))
    print("Mode: explicit GPU job smoke; existing CPU gateway dispatcher NOT modified")
    if not args.run:
        print("Dry-run only. Add --run after loading the existing .env.")
        return
    base_url = (args.base_url or "").rstrip("/")
    if not base_url.startswith("https://"):
        raise RuntimeError("Set --base-url or TRANSLATION_GATEWAY_BASE_URL to the HTTPS gateway")
    if args.max_wait_seconds < 60:
        raise ValueError("Test timeout must be >=60 seconds")
    settings = Settings.from_environment()
    # Fail closed: script is testing a mock-only deployment before activation.
    if settings.dispatcher_mode == "modal-gpu":
        raise RuntimeError("Isolated smoke requires local .env not to enable modal-gpu")
    health_req = urllib.request.Request(base_url + "/health")
    with urllib.request.urlopen(health_req, timeout=35) as response:
        health = json.load(response)
    if health.get("inference_enabled") is not False:
        raise RuntimeError("Deployed gateway is not in mock-only mode")
    models_req = urllib.request.Request(
        base_url + "/v1/models",
        headers={"Authorization": f"Bearer {settings.api_bearer_token}"},
    )
    with urllib.request.urlopen(models_req, timeout=35) as response:
        api_models = json.load(response)
    if set(x["key"] for x in api_models["models"]) != set(MODEL_REGISTRY):
        raise RuntimeError("Deployed gateway model registry does not match")
    engine = make_engine(settings.database_url)
    repo = JobRepository(make_session_factory(engine))
    started_at = time.monotonic()
    try:
        owner = settings.request_owner
        body = {
            "source_language": "en",
            "target_language": "vi",
            "text": SOURCE,
            "options": {"preserve_formatting": True},
        }
        models = list(MODEL_REGISTRY)
        key = "four-l40s-gpu-integration-" + uuid4().hex
        job_id = repo.submit(
            owner=owner, idempotency_key=key, kind="benchmark",
            payload=body, model_keys=models,
            max_jobs_per_minute=settings.max_jobs_per_minute,
            max_jobs_per_day=settings.max_jobs_per_day,
            max_model_runs_per_day=settings.max_model_runs_per_day,
            max_pending_jobs_per_owner=settings.max_pending_jobs_per_owner,
            max_pending_runs_per_model=settings.max_pending_runs_per_model,
        )
        assert repo.submit(
            owner=owner, idempotency_key=key, kind="benchmark",
            payload=body, model_keys=models,
            max_jobs_per_minute=settings.max_jobs_per_minute,
            max_jobs_per_day=settings.max_jobs_per_day,
            max_model_runs_per_day=settings.max_model_runs_per_day,
            max_pending_jobs_per_owner=settings.max_pending_jobs_per_owner,
            max_pending_runs_per_model=settings.max_pending_runs_per_model,
        ) == job_id
        print("Database created one idempotent benchmark, dispatching four GPU runs")
        dispatch_queued_runs(repo, ModalGpuDispatcher(), job_id, owner)
        deadline = time.monotonic() + args.max_wait_seconds
        latest = None
        while time.monotonic() < deadline:
            job = repo.get(job_id, owner)
            latest = {r.model_key: r.status for r in job.runs}
            if all(s in ("completed", "failed", "dispatch_uncertain", "execution_uncertain")
                   for s in latest.values()):
                break
            time.sleep(4)
        job = repo.get(job_id, owner)
        runs = job.runs
        results = [{
            "model": run.model_key,
            "status": run.status,
            "is_mock_result": run.result.is_mock_result if run.result else None,
            "nonempty_translation": bool(run.result and run.result.translation_text.strip()),
            "translation_codepoints": len(run.result.translation_text) if run.result else 0,
            "translation_sha256": hashlib.sha256(
                run.result.translation_text.encode("utf-8")).hexdigest() if run.result else None,
            "input_tokens": run.result.input_tokens if run.result else None,
            "output_tokens": run.result.output_tokens if run.result else None,
            "error_code": run.error_code,
        } for run in runs]
        gateway = check_gateway_read(settings.api_bearer_token, job_id, base_url)
        api_states = {run["model"]: run["status"] for run in gateway["runs"]}
        all_ok = (
            len(runs) == 4
            and all(r["status"] == "completed" and r["is_mock_result"] is False
                    and r["nonempty_translation"] for r in results)
            and api_states == latest
            and gateway["status"] == "completed"
            and summarize_run_states(runs) == "completed"
        )
        output = {
            "tested_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "four_real_gpu_jobs_persisted_and_read_by_gateway" if all_ok else "incomplete_or_failed",
            "scope": "PostgreSQL async jobs, exact Modal GPU class dispatch and authenticated gateway GET; no public GPU submission mode",
            "model_count": 4,
            "source_language": "en",
            "target_language": "vi",
            "input_codepoints": len(SOURCE),
            "elapsed_seconds": round(time.monotonic() - started_at, 3),
            "results": results,
            "api_states": api_states,
        }
        report_path = save_private_report(output, filename="postgresql_gpu_jobs.json", repository_root=ROOT)
        print(json.dumps({
            "status": output["status"],
            "model_statuses": {r["model"]: r["status"] for r in results},
            "all_nonmock": all(r["is_mock_result"] is False for r in results),
            "elapsed_seconds": output["elapsed_seconds"],
            "report": str(report_path),
        }, indent=2))
        if not all_ok:
            raise RuntimeError("Four-model real GPU PostgreSQL integration did not pass")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
