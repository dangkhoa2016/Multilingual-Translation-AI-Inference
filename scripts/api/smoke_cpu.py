"""Manual, CPU-only deployed Modal smoke test. Never prints API credentials or translation text.

Run:
  set -a; source .env; set +a
  python scripts/api/smoke_cpu.py --base-url https://YOUR_MODAL_ENDPOINT
"""

import argparse
import os
import time
from uuid import uuid4

import httpx

MODELS = ["hy_mt2_30b", "index_35b", "gemma4_31b_it", "qwen35_35b"]


def check_response(response: httpx.Response, expected: int, name: str) -> dict:
    if response.status_code != expected:
        raise AssertionError(f"{name}: expected HTTP {expected}, got {response.status_code}")
    return response.json()


def await_completed(client: httpx.Client, base_url: str, headers: dict, job_id: str,
                    expected_runs: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check_response(
            client.get(f"{base_url}/v1/jobs/{job_id}", headers=headers),
            200, "poll job",
        )
        runs = result.get("runs", [])
        states = [run.get("status") for run in runs]
        if len(runs) != expected_runs:
            raise AssertionError(f"Expected {expected_runs} runs, got {len(runs)}")
        if all(state == "completed" for state in states):
            if not all(run.get("is_mock_result") is True for run in runs):
                raise AssertionError("One or more results lack is_mock_result=true")
            if not all(
                (run.get("translation_text") or "").startswith(
                    "[MOCK ONLY — NOT A TRANSLATION"
                )
                for run in runs
            ):
                raise AssertionError("Mock disclaimer missing")
            print(f"job completed: {expected_runs} mock runs, all flagged explicitly")
            return
        if any(state in ("failed", "dispatch_uncertain") for state in states):
            raise AssertionError(f"Job ended with an unexpected run state: {states}")
        time.sleep(2)
    raise TimeoutError(f"Job did not complete after {timeout} seconds")


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test deployed Modal CPU mock API")
    parser.add_argument("--base-url", required=True, help="HTTPS base URL of the Modal API")
    parser.add_argument("--max-wait-seconds", type=float, default=120)
    args = parser.parse_args()
    if not args.base_url.startswith("https://"):
        raise SystemExit("HTTPS base URL required")
    token = os.environ.get("TRANSLATION_API_BEARER_TOKEN")
    if not token:
        raise SystemExit("Load TRANSLATION_API_BEARER_TOKEN from .env before testing")
    base_url = args.base_url.rstrip("/")
    auth = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=90, follow_redirects=False) as client:
        health = check_response(client.get(f"{base_url}/health"), 200, "health")
        assert health["inference_enabled"] is False
        check_response(client.get(f"{base_url}/v1/models"), 401, "unauthorized models")
        registry = check_response(
            client.get(f"{base_url}/v1/models", headers=auth), 200, "authorized models"
        )
        assert len(registry["models"]) == 4
        print("health and bearer authentication passed; 4 models registered")

        payload = {
            "model": MODELS[0],
            "source_language": "en",
            "target_language": "vi",
            "text": "Modal CPU-only asynchronous translation test.",
        }
        idempotency = {"Idempotency-Key": "cpu-smoke-" + uuid4().hex}
        headers = {**auth, **idempotency}
        endpoint = f"{base_url}/v1/jobs/translations"
        first = check_response(client.post(endpoint, json=payload, headers=headers), 202,
                               "create translation")
        duplicate = check_response(client.post(endpoint, json=payload, headers=headers), 202,
                                   "repeated translation")
        assert duplicate["job_id"] == first["job_id"], "Idempotency did not reuse job"
        conflicting = {**payload, "text": "A different text with the same key"}
        check_response(client.post(endpoint, json=conflicting, headers=headers), 409,
                       "idempotency conflict")
        await_completed(client, base_url, auth, first["job_id"], 1, args.max_wait_seconds)
        print("translation and idempotency passed")

        benchmark = {
            "models": MODELS,
            "source_language": "en",
            "target_language": "vi",
            "text": "A multilingual benchmark smoke test.",
        }
        benchmark_headers = {**auth, "Idempotency-Key": "benchmark-smoke-" + uuid4().hex}
        result = check_response(
            client.post(f"{base_url}/v1/jobs/benchmarks", json=benchmark,
                        headers=benchmark_headers), 202, "create benchmark"
        )
        await_completed(client, base_url, auth, result["job_id"], 4, args.max_wait_seconds)
        print("four-model CPU mock benchmark passed (NOT actual translations)")
    print("PASS: Modal CPU gateway, spawn, PostgreSQL, idempotency, and polling")


if __name__ == "__main__":
    main()
