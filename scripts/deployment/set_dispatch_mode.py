"""Opt-in dispatcher switch using a single-key Modal Secret merge.

Default invocation is read-only. --apply changes only
TRANSLATION_DISPATCHER_MODE via modal.Secret.update(), then rolls over
containers. All other Secret variables remain unchanged. Recreate rollover
may interrupt in-flight requests; do not apply during active jobs.

  python scripts/deployment/set_dispatch_mode.py --to-mock
  python scripts/deployment/set_dispatch_mode.py --to-gpu --apply \
      --base-url https://YOUR_GATEWAY.modal.run --profile YOUR_MODAL_PROFILE
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from multilingual_translation_ai_inference.resource_names import (
    MODAL_API_AUTH_SECRET_NAME,
    MODAL_APP_NAME,
)


class _DenyRedirects(urllib.request.HTTPRedirectHandler):
    """Credential probes must never forward Authorization to another URL."""

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _credential_open(request, *, timeout):
    return urllib.request.build_opener(_DenyRedirects()).open(request, timeout=timeout)

ROOT = Path(__file__).resolve().parents[2]
MODES = {"modal-gpu", "modal-cpu-mock"}


def _health(base_url):
    with urllib.request.urlopen(base_url + "/health", timeout=30) as response:
        return json.load(response)


def _check_authenticated(base_url, token):
    # A deliberately invalid UUID returns 422 only after successful Bearer
    # authentication. Never POST a job or allocate GPU during this preflight.
    request = urllib.request.Request(
        base_url + "/v1/jobs/not-a-uuid",
        headers={"Authorization": "Bearer " + token},
    )
    try:
        with _credential_open(request, timeout=35):
            pass
    except urllib.error.HTTPError as error:
        if error.code == 422:
            return
    raise RuntimeError("Existing API authentication check failed")


def _run_safely(argv, *, profile=None, environment=None):
    env = os.environ.copy()
    if profile:
        env["MODAL_PROFILE"] = profile
    if environment:
        env["MODAL_ENVIRONMENT"] = environment
    result = subprocess.run(
        argv, cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=300, check=False,
    )
    if result.returncode:
        # Never disclose CLI output: diagnostics can accidentally contain credentials.
        raise RuntimeError("Modal command failed; output withheld to protect credentials")


def _update_mode(mode, *, profile=None, environment=None):
    """Merge one key into the existing Secret without replacing other fields."""
    if mode not in MODES:
        raise ValueError("Unsupported dispatcher mode")
    statement = (
        "import modal\n"
        f"modal.Secret.from_name({MODAL_API_AUTH_SECRET_NAME!r}, "
        f"environment_name={environment!r}).update("
        f"{{'TRANSLATION_DISPATCHER_MODE': {mode!r}}})"
    )
    _run_safely([sys.executable, "-c", statement],
                profile=profile, environment=environment)


def _rollover(*, profile=None, environment=None):
    cli = ROOT / ".venv" / "bin" / "modal"
    executable = str(cli) if cli.is_file() else "modal"
    _run_safely([
        executable, "app", "rollover", MODAL_APP_NAME,
        "--strategy", "recreate",
    ], profile=profile, environment=environment)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--to-gpu", action="store_true")
    target.add_argument("--to-mock", action="store_true")
    parser.add_argument("--apply", action="store_true",
                        help="Update the existing Secret and recreate running containers")
    parser.add_argument("--base-url", default=os.environ.get("TRANSLATION_GATEWAY_BASE_URL"))
    parser.add_argument("--profile", default=os.environ.get("TRANSLATION_MODAL_PROFILE"))
    parser.add_argument("--environment", default=os.environ.get("MODAL_ENVIRONMENT"))
    args = parser.parse_args()

    desired = "modal-gpu" if args.to_gpu else "modal-cpu-mock"
    print("Requested dispatcher mode:", desired)
    if not args.apply:
        print("Dry-run only. Use --apply for a live, potentially disruptive update.")
        return

    base_url = (args.base_url or "").rstrip("/")
    if not base_url.startswith("https://"):
        raise RuntimeError("A valid HTTPS gateway URL is required")
    token = os.environ.get("TRANSLATION_API_BEARER_TOKEN", "")
    if not token or token.lower() in {"changeme", "replace-me"}:
        raise RuntimeError("Current API Bearer token must be configured")

    _check_authenticated(base_url, token)
    previous = _health(base_url)
    if previous.get("status") != "ok" or not isinstance(previous.get("inference_enabled"), bool):
        raise RuntimeError("Gateway mode preflight did not return a valid response")
    old_mode = "modal-gpu" if previous["inference_enabled"] else "modal-cpu-mock"
    if desired == old_mode:
        print("Already in the requested mode; no Secret or container update")
        return
    if args.to_gpu and previous["inference_enabled"] is not False:
        raise RuntimeError("GPU activation requires a confirmed non-GPU gateway")

    print("Preflight passed. Only TRANSLATION_DISPATCHER_MODE will be updated.")
    try:
        _update_mode(desired, profile=args.profile, environment=args.environment)
        _rollover(profile=args.profile, environment=args.environment)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                health = _health(base_url)
                if health.get("inference_enabled") is (desired == "modal-gpu"):
                    _check_authenticated(base_url, token)
                    print("Gateway mode verified:", desired)
                    return
            except (OSError, ValueError, RuntimeError):
                pass
            time.sleep(3)
        raise RuntimeError("Gateway did not confirm the new dispatcher mode")
    except Exception:
        # A failed update call might have succeeded remotely before its response was lost.
        print("Switch was not confirmed; attempting to restore the previous mode")
        try:
            _update_mode(old_mode, profile=args.profile, environment=args.environment)
            _rollover(profile=args.profile, environment=args.environment)
            print("Previous mode restoration requested; inspect running jobs and health")
        except Exception:
            print("WARNING: restoration uncertain; operator inspection required")
        raise


if __name__ == "__main__":
    main()
