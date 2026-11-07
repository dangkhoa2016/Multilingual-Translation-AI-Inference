"""Opt-in, bounded real boundary/concurrency live API tests (never automatic retry).

Purpose:
* 1000 Unicode code points (multibyte UTF-8) -> four real GPU models, one job.
* 1001 code points, whitespace-only, invalid languages -> HTTP 422, no GPU job.
* Optional: two unique jobs simultaneously targeting one L40S worker.

No credentials or raw translations are logged or persisted to the report.
GPU executions are billed. Dry-run by default; --run-boundary / --run-concurrency
are separate explicit switches and each runs at most one batch.

  set -a; source .env; set +a
  PYTHONPATH=src python scripts/api_reliability_smoke.py
  PYTHONPATH=src python scripts/api_reliability_smoke.py --base-url HTTPS_URL --run-boundary
  PYTHONPATH=src python scripts/api_reliability_smoke.py --base-url HTTPS_URL --run-concurrency
"""
import argparse
import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from translation_ai_inference.model_registry import MODEL_REGISTRY

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIRECTORY = ROOT / "reports"
MODELS = tuple(MODEL_REGISTRY)
START = (
    "At dawn, the archivist opened a wooden chest. It held a silver compass, "
    "a blue notebook, a map, and a letter. The workers had closed the bridge "
    "for repairs; nobody was allowed to replace the silver compass with "
    "a copper compass. The caretaker wrote that the bridge would reopen "
    "only after the final inspection. The children waited outside the "
    "old library. Café visitors agreed to keep the letter safe.\n\n"
)
# Use the whole bounded text in POST, preserve multi-paragraph structure,
# and include non-ASCII code points (the UTF-8 byte count must exceed 1000).
BOUNDARY_TEXT = ((START * 3)[:999] + ".")
CONCURRENT_TEXTS = (
    "The lighthouse keeper checked the silver compass before sunrise.",
    "The railway engineer kept the blue notebook and repaired the bridge.",
)


def validate_fixture() -> None:
    assert len(BOUNDARY_TEXT) == 1000
    assert len(BOUNDARY_TEXT.encode("utf-8")) > 1000
    assert "\n\n" in BOUNDARY_TEXT
    assert "silver compass" in BOUNDARY_TEXT
    assert len(BOUNDARY_TEXT + "x") == 1001
    assert len(MODELS) == 4
    assert len(set(CONCURRENT_TEXTS)) == 2


def request_payload(text: str, *, models=None, model=None) -> dict:
    result = {
        "source_language": "en", "target_language": "vi", "text": text,
        "options": {"preserve_formatting": True},
    }
    if models is not None:
        result["models"] = list(models)
    if model is not None:
        result["model"] = model
    return result


def expected_code(resp: httpx.Response, code: int, *, context: str):
    if resp.status_code != code:
        raise AssertionError(f"{context}: wanted HTTP {code}, saw {resp.status_code}")
    return resp.json()


def require_live_gpu(client: httpx.Client, base_url: str, auth: dict) -> None:
    health = expected_code(client.get(base_url + "/health"), 200, context="health")
    if health.get("inference_enabled") is not True or health.get("phase") != "gpu":
        raise AssertionError("GPU mode is not enabled; refusing to submit jobs")
    expected_code(client.get(base_url + "/v1/models"), 401, context="unauthenticated list")
    registry = expected_code(client.get(base_url + "/v1/models", headers=auth),
                             200, context="protected model list")["models"]
    if {entry["key"] for entry in registry} != set(MODELS):
        raise AssertionError("Gateway model registry differs from pinned four-model list")
    if not all(entry["enabled"] and entry["runtime_verified"] for entry in registry):
        raise AssertionError("Gateway not reporting all four GPU models available")


def poll_job(client: httpx.Client, base_url: str, auth: dict,
             job_id: str, *, deadline: float) -> tuple[dict, int]:
    iterations = 0
    last = None
    while time.monotonic() < deadline:
        data = expected_code(
            client.get(base_url + f"/v1/jobs/{job_id}", headers=auth),
            200, context="poll result",
        )
        iterations += 1
        last = data
        if data["status"] in {
            "completed", "failed", "partial_failed",
            "dispatch_uncertain", "execution_uncertain",
        }:
            break
        if data["runs"] and all(run["status"] in {
            "completed", "failed", "dispatch_uncertain", "execution_uncertain",
        } for run in data["runs"]):
            break
        time.sleep(3)
    if last is None:
        raise TimeoutError("No API response received during polling")
    return last, iterations


def sanitized_run(run: dict) -> dict:
    translated = run.get("translation_text")
    return {
        "model": run.get("model"),
        "status": run.get("status"),
        "is_mock_result": run.get("is_mock_result"),
        "has_nonempty_output": isinstance(translated, str) and bool(translated.strip()),
        "translation_characters": len(translated) if isinstance(translated, str) else None,
        "translation_sha256": hashlib.sha256(translated.encode("utf-8")).hexdigest()
        if isinstance(translated, str) else None,
        "error_code": run.get("error_code"),
        "attempt_no": run.get("attempt_no"),
    }


def write_report(filename: str, report: dict):
    REPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    target = REPORT_DIRECTORY / filename
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Report:", str(target))
    print("Outcome:", report["status"])


def negative_input_tests(client, base_url, auth):
    endpoint = base_url + "/v1/jobs/translations"
    checks = [
        ("1001_codepoints", request_payload(BOUNDARY_TEXT + "x", model=MODELS[0])),
        ("empty_whitespace", request_payload("   ", model=MODELS[0])),
        ("same_language", {
            **request_payload("Hello", model=MODELS[0]),
            "source_language": "en", "target_language": "en",
        }),
        ("unknown_language", {
            **request_payload("Hello", model=MODELS[0]),
            "target_language": "xx",
        }),
    ]
    outcomes = {}
    for name, payload in checks:
        response = client.post(
            endpoint, json=payload,
            headers={**auth, "Idempotency-Key": "p6-rejected-" + uuid4().hex},
        )
        expected_code(response, 422, context=name)
        outcomes[name] = response.status_code
    return outcomes


def run_boundary(client, base_url, auth, wait_seconds):
    started = time.monotonic()
    checks = negative_input_tests(client, base_url, auth)
    path = base_url + "/v1/jobs/benchmarks"
    payload = request_payload(BOUNDARY_TEXT, models=MODELS)
    headers = {**auth, "Idempotency-Key": "p6-boundary-" + uuid4().hex}
    response = client.post(path, json=payload, headers=headers)
    submitted = expected_code(response, 202, context="1000-codepoint benchmark")
    job_id = submitted["job_id"]
    replay = expected_code(client.post(path, json=payload, headers=headers),
                           202, context="idempotent replay")
    if replay["job_id"] != job_id:
        raise AssertionError("Idempotent replay created a new benchmark")
    conflict = client.post(
        path, json={**payload, "text": BOUNDARY_TEXT[:-1] + "!"},
        headers=headers,
    )
    expected_code(conflict, 409, context="conflicting idempotency payload")
    data, polls = poll_job(client, base_url, auth, job_id,
                           deadline=time.monotonic() + wait_seconds)
    runs = [sanitized_run(r) for r in data["runs"]]
    passed = (
        data["status"] == "completed"
        and len(runs) == 4
        and {r["model"] for r in runs} == set(MODELS)
        and all(r["status"] == "completed"
                and r["is_mock_result"] is False
                and r["has_nonempty_output"]
                and r["attempt_no"] == 1 for r in runs)
    )
    report = {
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if passed else "failed_or_incomplete",
        "scope": "1000 Unicode codepoint real HTTP benchmark and input rejection gates",
        "input_codepoints": len(BOUNDARY_TEXT),
        "input_utf8_bytes": len(BOUNDARY_TEXT.encode("utf-8")),
        "four_models": list(MODELS),
        "rejected_inputs_http_422": checks,
        "idempotent_job_reused": replay["job_id"] == job_id,
        "conflicting_payload_http_409": conflict.status_code,
        "job_id": job_id, "parent_job_status": data["status"],
        "poll_requests": polls,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "runs": runs,
        "note": "No translation quality scoring; no automatic retry of uncertain runs.",
    }
    write_report("unicode_input_boundary.json", report)
    if not passed:
        raise AssertionError("1000 Unicode-codepoint four-model inference failed")


def _submit_one(client, base_url, headers, text):
    started = time.monotonic()
    response = client.post(
        base_url + "/v1/jobs/translations",
        headers=headers,
        json=request_payload(text, model=MODELS[0]),
    )
    data = expected_code(response, 202, context="concurrent POST")
    return data["job_id"], time.monotonic() - started


def run_concurrency(client, base_url, auth, wait_seconds):
    started = time.monotonic()
    headers = [
        {**auth, "Idempotency-Key": "p6-same-model-concurrency-" + uuid4().hex}
        for _ in CONCURRENT_TEXTS
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_submit_one, client, base_url, headers[index], text)
            for index, text in enumerate(CONCURRENT_TEXTS)
        ]
        submitted = [f.result(timeout=65) for f in futures]
    ids = [s[0] for s in submitted]
    if len(set(ids)) != 2:
        raise AssertionError("Two different idempotency keys produced the same job")
    all_data = {}
    deadline = time.monotonic() + wait_seconds
    polls = 0
    while time.monotonic() < deadline:
        for job_id in ids:
            if job_id not in all_data or all_data[job_id]["status"] not in {
                "completed", "failed", "dispatch_uncertain", "execution_uncertain",
            }:
                data = expected_code(
                    client.get(base_url + "/v1/jobs/" + job_id, headers=auth),
                    200, context="concurrent poll",
                )
                polls += 1
                all_data[job_id] = data
        if len(all_data) == 2 and all(
            data["status"] == "completed"
            for data in all_data.values()
        ):
            break
        if any(data["status"] in {
            "failed", "dispatch_uncertain", "execution_uncertain",
        } for data in all_data.values()):
            break
        time.sleep(3)
    run_rows = [sanitized_run(all_data[job_id]["runs"][0]) for job_id in ids
                if job_id in all_data and all_data[job_id]["runs"]]
    passed = (
        len(run_rows) == 2
        and all(row["model"] == MODELS[0] and row["status"] == "completed"
                and row["is_mock_result"] is False
                and row["has_nonempty_output"]
                and row["attempt_no"] == 1 for row in run_rows)
    )
    report = {
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if passed else "failed_or_incomplete",
        "scope": "Two independent concurrent POST jobs to the same single-container L40S model",
        "gpu_model": MODELS[0], "number_of_jobs": 2,
        "unique_job_ids": len(set(ids)),
        "post_latencies_seconds": [round(r[1], 3) for r in submitted],
        "job_ids": ids,
        "poll_requests": polls,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "runs": run_rows,
        "note": "Both requests were concurrent at the API; GPU processing may be queued "
                "on max_containers=1. No claim of GPU-parallel execution for the same model.",
    }
    write_report("concurrent_model_jobs.json", report)
    if not passed:
        raise AssertionError("Two independent jobs to the same GPU worker did not both finish")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("TRANSLATION_GATEWAY_BASE_URL"))
    parser.add_argument("--run-boundary", action="store_true")
    parser.add_argument("--run-concurrency", action="store_true")
    parser.add_argument("--max-wait-seconds", type=int, default=360)
    args = parser.parse_args()
    validate_fixture()
    print("Fixture: exactly 1000 Unicode code points,", len(BOUNDARY_TEXT.encode("utf-8")),
          "UTF-8 bytes, 4 models; negative 1001-codepoint rejection.")
    if not args.run_boundary and not args.run_concurrency:
        print("CPU-only dry-run; use --run-boundary or --run-concurrency for billable GPU tests.")
        return
    base_url = (args.base_url or "").rstrip("/")
    if not base_url.startswith("https://"):
        raise ValueError("HTTPS gateway --base-url required")
    token = os.environ.get("TRANSLATION_API_BEARER_TOKEN")
    if not token:
        raise ValueError("TRANSLATION_API_BEARER_TOKEN missing")
    if args.max_wait_seconds < 60 or args.max_wait_seconds > 900:
        raise ValueError("Max wait seconds should be in [60, 900]")
    auth = {"Authorization": "Bearer " + token}
    with httpx.Client(timeout=45, follow_redirects=False) as client:
        require_live_gpu(client, base_url, auth)
        if args.run_boundary:
            run_boundary(client, base_url, auth, args.max_wait_seconds)
        if args.run_concurrency:
            run_concurrency(client, base_url, auth, args.max_wait_seconds)


if __name__ == "__main__":
    main()
