"""Explicitly switch deployed Modal GPU dispatch, retaining the existing bearer token.

Requires current API token from an untracked local .env and HTTPS gateway URL.
Does not put token values in shell arguments or commit them.

  set -a; source .env; set +a
  python scripts/set_modal_dispatch_mode.py --to-gpu
  python scripts/set_modal_dispatch_mode.py --to-gpu --apply --base-url HTTPS_GATEWAY
  python scripts/set_modal_dispatch_mode.py --to-mock --apply --base-url HTTPS_GATEWAY

Optional --profile selects an authenticated Modal CLI profile; otherwise use the
currently active profile. --base-url can also come from
TRANSLATION_GATEWAY_BASE_URL in the environment.
"""
import argparse
import json
import os
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from translation_ai_inference.gpu_budget import configured_estimate
from translation_ai_inference.resource_names import (
    MODAL_API_AUTH_SECRET_NAME,
    MODAL_APP_NAME,
)

APP_SOURCE = Path(__file__).resolve().parents[1] / "modal_app.py"


def _health(base_url):
    with urllib.request.urlopen(base_url + "/health", timeout=30) as response:
        return json.load(response)


def _check_authenticated(base_url, token):
    request = urllib.request.Request(
        base_url + "/v1/models", headers={"Authorization": "Bearer " + token},
    )
    with urllib.request.urlopen(request, timeout=35) as response:
        if response.status != 200 or len(json.load(response)["models"]) != 4:
            raise RuntimeError("Existing API auth smoke failed")


def _run_modal(args, token, profile):
    profile_args = ["--profile", profile] if profile else []
    result = subprocess.run(
        [str(APP_SOURCE.parent / ".venv" / "bin" / "modal"), *args, *profile_args],
        cwd=APP_SOURCE.parent,
        capture_output=True, text=True, timeout=300, check=False,
    )
    if result.returncode:
        # Redact even accidental token echo on a CLI failure.
        message = (result.stderr + result.stdout).replace(token, "[REDACTED]")
        raise RuntimeError("Modal CLI command failed: " + message[-1500:])


def _apply_secret(mode, token, profile):
    # If the operator chooses an estimated admission limit, validate and
    # preserve BOTH fields when this script replaces the API Secret.
    per_run_raw = os.environ.get("TRANSLATION_ESTIMATED_GPU_USD_PER_RUN")
    per_day_raw = os.environ.get("TRANSLATION_MAX_ESTIMATED_GPU_USD_PER_DAY")
    configured_estimate(per_run_raw, per_day_raw)
    variables = {
        "TRANSLATION_API_BEARER_TOKEN": token,
        "TRANSLATION_DISPATCHER_MODE": mode,
    }
    if per_run_raw is not None:
        variables.update({
            "TRANSLATION_ESTIMATED_GPU_USD_PER_RUN": per_run_raw,
            "TRANSLATION_MAX_ESTIMATED_GPU_USD_PER_DAY": per_day_raw,
        })
    elif mode == "modal-gpu":
        print("WARNING: estimated GPU USD admission budget is not configured")
    with tempfile.TemporaryDirectory(prefix="gpu-dispatch-", dir="/tmp") as parent:
        path = Path(parent) / "auth.json"
        path.write_text(json.dumps(variables), encoding="utf-8")
        path.chmod(0o600)
        _run_modal([
            "secret", "create", MODAL_API_AUTH_SECRET_NAME,
            "--from-json", str(path), "--force",
        ], token, profile)
    print("API auth Secret mode updated; credentials were not displayed")


def _redeploy(token, profile):
    _run_modal([
        "deploy", "--strategy", "recreate", str(APP_SOURCE),
    ], token, profile)
    # Secret changes affect only new containers. A code-identical deployment
    # can be a no-op; rollover prevents old mock/GPU modes from coexisting.
    _run_modal([
        "app", "rollover", MODAL_APP_NAME,
        "--strategy", "recreate",
    ], token, profile)
    print("Modal App redeployed and old Secret-bearing containers replaced")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--to-gpu", action="store_true")
    target.add_argument("--to-mock", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--base-url", default=os.environ.get("TRANSLATION_GATEWAY_BASE_URL"),
                        help="HTTPS URL of the authenticated deployed CPU gateway")
    parser.add_argument("--profile", default=os.environ.get("TRANSLATION_MODAL_PROFILE"),
                        help="Modal CLI profile; defaults to the selected local profile")
    args = parser.parse_args()
    desired = "modal-gpu" if args.to_gpu else "modal-cpu-mock"
    print("Target dispatcher mode:", desired)
    if not args.apply:
        print("Dry run only. Add --apply and --base-url to modify the deployment.")
        return
    base_url = (args.base_url or "").rstrip("/")
    if not base_url.startswith("https://"):
        raise RuntimeError("Missing HTTPS gateway URL")
    token = os.environ.get("TRANSLATION_API_BEARER_TOKEN", "")
    if not token or token.lower() in ("changeme", "replace-me"):
        raise RuntimeError("Existing API token missing")
    _check_authenticated(base_url, token)
    previous = _health(base_url)
    if args.to_gpu and previous.get("inference_enabled") is not False:
        raise RuntimeError("Gateway is not in the required mock-only preflight mode")
    if args.to_gpu:
        print("Gateway confirmed mock-only before GPU activation")
    changed = False
    try:
        _apply_secret(desired, token, args.profile)
        changed = True
        _redeploy(token, args.profile)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                health = _health(base_url)
                if health.get("inference_enabled") is (desired == "modal-gpu"):
                    _check_authenticated(base_url, token)
                    print("Verified live Gateway inference_enabled:", health["inference_enabled"])
                    return
            except (OSError, ValueError, RuntimeError):
                pass
            time.sleep(3)
        raise RuntimeError("Gateway health did not confirm desired dispatch mode")
    except Exception:
        # Return to known original mock mode if a GPU activation is uncertain.
        if changed and args.to_gpu and previous.get("inference_enabled") is False:
            print("GPU activation failed; attempting mock-mode rollback")
            try:
                _apply_secret("modal-cpu-mock", token, args.profile)
                _redeploy(token, args.profile)
                print("Rollback deployment invoked")
            except Exception:
                print("WARNING: rollback failed; manual operator inspection required")
        raise


if __name__ == "__main__":
    main()
