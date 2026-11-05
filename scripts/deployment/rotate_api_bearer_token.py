"""Opt-in rotation of the single-tenant Modal API Bearer token.

Dry-run is strictly local and performs no network, Secret writes or rollovers.
Apply verifies the old token against an authenticated GET, updates only one
Secret key, recreates existing containers and verifies the new credential.

Never supply tokens on the command line. Use separate owner-only dotenv files.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

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

TOKEN_NAME = "TRANSLATION_API_BEARER_TOKEN"
VALIDATION_ROUTE = "/v1/jobs/not-a-uuid"
MAX_VERIFICATION_SECONDS = 120


class RotationError(RuntimeError):
    """A sanitized token rotation error (no secret values in messages)."""


class RotationVerificationThrottled(RotationError):
    """New credential could not be confirmed because probes were throttled."""



def _read_private_token(path_string: str, *, new_file: bool) -> str:
    """Load one token from a regular owner-only file, with no interpolation."""
    path = Path(path_string).expanduser()
    try:
        file_stat = path.lstat()
    except OSError:
        raise RotationError("Cannot read the specified private token file") from None
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_mode & 0o077:
        raise RotationError("Token files must be regular files with 0600 permissions")
    try:
        # Explicitly disable ${ENV} interpolation and never print contents.
        values = dotenv_values(path, interpolate=False, verbose=False)
    except Exception:
        raise RotationError("Could not parse private token file") from None
    if new_file and set(values) != {TOKEN_NAME}:
        raise RotationError("The new-token file must contain only the API token key")
    value = values.get(TOKEN_NAME)
    if not isinstance(value, str) or not 16 <= len(value) <= 4096:
        raise RotationError("Bearer token must contain 16–4096 printable ASCII characters")
    if not all(33 <= ord(character) <= 126 for character in value):
        raise RotationError("Bearer token must not contain spaces or control characters")
    return value


def _http_status(base_url: str, token: str) -> int:
    """Use GET with invalid UUID: auth failure=401; valid auth=422; never GPU."""
    request = urllib.request.Request(
        base_url + VALIDATION_ROUTE,
        headers={"Authorization": "Bearer " + token},
        method="GET",
    )
    try:
        with _credential_open(request, timeout=20) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def _health(base_url: str) -> dict:
    with urllib.request.urlopen(base_url + "/health", timeout=20) as response:
        if response.status != 200:
            raise RotationError("Gateway health check failed")
        data = json.load(response)
        if not isinstance(data, dict) or data.get("status") != "ok":
            raise RotationError("Gateway health check failed")
        return data


def _update_token(token: str, *, profile: str, environment: str) -> None:
    """Merge one key in an existing Modal Secret, not replace its whole dict."""
    os.environ["MODAL_PROFILE"] = profile
    os.environ["MODAL_ENVIRONMENT"] = environment
    # The SDK is imported only on apply; dry-run cannot contact Modal.
    import modal

    secret = modal.Secret.from_name(
        MODAL_API_AUTH_SECRET_NAME,
        environment_name=environment,
        required_keys=[TOKEN_NAME],
    )
    secret.update({TOKEN_NAME: token})


def _rollover(*, profile: str, environment: str) -> None:
    """Terminate old containers so no old credential remains in a rolling pool."""
    command = [
        "modal", "app", "rollover", MODAL_APP_NAME,
        "--strategy", "recreate", "--profile", profile, "--env", environment,
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if result.returncode:
        # CLI output can contain credentials, paths or other private metadata.
        raise RotationError("Modal App rollover failed; CLI output withheld")


def _verify(base_url: str, *, old_token: str, new_token: str) -> bool:
    """Confirm new token; return False if revocation is obscured by throttling.

    A 429 is not proof of authentication success or token revocation. Never
    repeatedly probe the new token immediately before a throttled old-token
    probe: that can consume the entire per-peer request budget each time.
    """
    deadline = time.monotonic() + MAX_VERIFICATION_SECONDS
    new_token_throttles = 0
    while time.monotonic() < deadline:
        try:
            _health(base_url)
            new_status = _http_status(base_url, new_token)
            if new_status == 422:
                old_status = _http_status(base_url, old_token)
                if old_status == 401:
                    return True
                if old_status == 429:
                    # Wait briefly and retry ONLY the old token, without
                    # exhausting the budget with another new-token request.
                    remaining = deadline - time.monotonic()
                    if remaining > 0:
                        time.sleep(min(3, remaining))
                        old_status = _http_status(base_url, old_token)
                    if old_status == 401:
                        return True
                    if old_status == 429:
                        return False
                raise RotationError("Old token revocation could not be confirmed")
            if new_status == 429:
                new_token_throttles += 1
                if new_token_throttles >= 2:
                    raise RotationVerificationThrottled(
                        "Verification was rate-limited; new credential state is unconfirmed"
                    )
            elif new_status == 401:
                raise RotationError("New credential is not accepted")
        except (OSError, ValueError, TimeoutError):
            pass
        time.sleep(min(3, max(0, deadline - time.monotonic())))
    if new_token_throttles:
        raise RotationVerificationThrottled(
            "Verification was rate-limited; new credential state is unconfirmed"
        )
    raise RotationError("Gateway did not confirm the new token before timeout")


def rotate(*, base_url: str, profile: str, environment: str,
           old_token: str, new_token: str) -> None:
    """Preflight, merge, recreate, verify; attempt rollback on uncertainty."""
    if _health(base_url).get("status") != "ok":
        raise RotationError("Gateway health check failed")
    if _http_status(base_url, old_token) != 422:
        raise RotationError("The existing token was not accepted before rotation")
    print("Preflight passed; authenticated job routes remain protected.")
    try:
        _update_token(new_token, profile=profile, environment=environment)
        _rollover(profile=profile, environment=environment)
        old_revocation_verified = _verify(
            base_url, old_token=old_token, new_token=new_token
        )
    except RotationVerificationThrottled:
        # Reverting an unconfirmed rotation may restore a credential the
        # operator explicitly tried to revoke; require manual reconciliation.
        print("WARNING: verification was rate-limited; leaving the new Secret in place.")
        print("Authentication state is unconfirmed; inspect Modal and retry verification manually.")
        raise RotationVerificationThrottled(
            "Verification was rate-limited; new Secret was left in place"
        ) from None
    except Exception:
        print("Rotation unconfirmed; attempting to restore the previous credential.")
        try:
            _update_token(old_token, profile=profile, environment=environment)
            _rollover(profile=profile, environment=environment)
            if _http_status(base_url, old_token) != 422:
                print("WARNING: rollback requested but not fully verified; inspect Modal manually.")
            else:
                print("Previous credential was restored and verified.")
        except Exception:
            print("WARNING: rollback uncertain; inspect running containers and Secrets manually.")
        # Do not preserve exception chain: Modal SDK/CLI exceptions may include secrets.
        raise RotationError("Token rotation failed; operational details withheld") from None
    if old_revocation_verified:
        print("Token rotation verified: new credential accepted; old credential rejected.")
    else:
        print("New credential accepted, but previous credential revocation could not be verified due to HTTP 429.")
        print("WARNING: keep the new credential; review revocation after the rate limit resets.")
        raise RotationVerificationThrottled(
            "New credential accepted; previous credential revocation unverified (HTTP 429)"
        )
    print("Update private client configuration; this tool does not change client files.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-token-env-file", required=True, metavar="PRIVATE_DOTENV")
    parser.add_argument("--new-token-env-file", required=True, metavar="PRIVATE_DOTENV")
    parser.add_argument("--profile", default=os.environ.get("MODAL_PROFILE"))
    parser.add_argument("--environment", default=os.environ.get("MODAL_ENVIRONMENT"))
    parser.add_argument("--base-url", default=os.environ.get("TRANSLATION_GATEWAY_BASE_URL"))
    parser.add_argument("--apply", action="store_true", help="Modify Modal Secret and recreate App containers")
    parser.add_argument("--allow-custom-gateway-host", action="store_true",
                        help="Explicitly allow an HTTPS gateway host outside modal.run")
    parser.add_argument("--confirm-job-interruption", action="store_true",
                        help="Confirm that existing jobs/requests may be interrupted")
    args = parser.parse_args(argv)

    if not args.profile or not args.environment:
        parser.error("Explicit --profile and --environment are required")
    try:
        old = _read_private_token(args.current_token_env_file, new_file=False)
        new = _read_private_token(args.new_token_env_file, new_file=True)
        if secrets.compare_digest(old, new):
            raise RotationError("New token must differ from current token")
        print("Local token format and private file permissions verified.")
        print("Target Modal profile and environment selected.")
        if not args.apply:
            print("Dry-run only: no network calls, Secret updates or container rollovers.")
            return 0
        if not args.confirm_job_interruption:
            raise RotationError("--confirm-job-interruption is required with --apply")
        address = urlsplit(args.base_url or "")
        if (address.scheme != "https" or not address.hostname or
                address.username or address.password or address.path not in ("", "/") or
                address.query or address.fragment):
            raise RotationError("A bare HTTPS gateway URL without credentials is required")
        if not (address.hostname.endswith(".modal.run") or
                args.allow_custom_gateway_host):
            raise RotationError(
                "Non-Modal gateway host requires --allow-custom-gateway-host"
            )
        rotate(base_url=args.base_url.rstrip("/"), profile=args.profile,
               environment=args.environment, old_token=old, new_token=new)
    except RotationVerificationThrottled as error:
        # Incomplete verification is distinct from failure and from success.
        # Never roll back just because a protected probe was rate-limited.
        print("UNVERIFIED:", str(error))
        return 2
    except RotationError as error:
        # All errors raised by this script are fixed, sanitized strings.
        print("ERROR:", str(error))
        return 1
    except Exception:
        print("ERROR: Unexpected failure; details withheld to protect credentials")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
