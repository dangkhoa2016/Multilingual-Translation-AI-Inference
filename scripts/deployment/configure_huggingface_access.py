"""Create a dedicated Hugging Face access credential for Modal CPU staging.

Dry run by default. --apply creates exactly one Modal Secret, without replacing
existing Secrets, modifying deployments, downloading weights or running GPUs.
"""
import argparse
import getpass
import os
import re
import sys
from pathlib import Path

from multilingual_translation_ai_inference.resource_names import (
    MODAL_HUGGINGFACE_DOWNLOAD_SECRET_NAME,
)


class SetupError(Exception):
    """Operator-facing error that must not reveal credentials."""


def read_token(env_file: Path | None) -> str:
    if env_file is not None:
        if not env_file.is_file():
            raise SetupError("Private dotenv file was not found")
        if env_file.stat().st_mode & 0o077:
            raise SetupError("Private dotenv file must have mode 0600 (chmod 600)")
        from dotenv import dotenv_values
        token = dotenv_values(env_file).get("HF_TOKEN")
    else:
        token = os.environ.get("HF_TOKEN")
        if not token:
            if not sys.stdin.isatty():
                raise SetupError(
                    "No HF_TOKEN in environment; use --env-file in noninteractive sessions"
                )
            token = getpass.getpass("Hugging Face read token (hidden): ")
    if not isinstance(token, str) or not re.fullmatch(r"hf_[A-Za-z0-9]{8,}", token.strip()):
        raise SetupError("HF_TOKEN is missing or has an invalid format")
    return token.strip()


def create_secret(*, profile: str, environment: str,
                  apply: bool, env_file: Path | None) -> None:
    if not profile.strip() or not environment.strip():
        raise SetupError("An explicit Modal profile and environment are required")
    if not apply:
        print(f"Dry run: profile={profile}, environment={environment}; "
              f"Secret={MODAL_HUGGINGFACE_DOWNLOAD_SECRET_NAME}; no cloud operation")
        return
    os.environ["MODAL_PROFILE"] = profile
    os.environ["MODAL_ENVIRONMENT"] = environment
    try:
        import modal
        existing = {item.name for item in modal.Secret.objects.list(
            environment_name=environment,
        )}
    except Exception:
        raise SetupError(
            "Cannot inspect Modal Secrets; verify profile and environment"
        ) from None
    if MODAL_HUGGINGFACE_DOWNLOAD_SECRET_NAME in existing:
        raise SetupError("Hugging Face staging Secret already exists; no changes made")
    token = read_token(env_file)
    try:
        modal.Secret.objects.create(
            MODAL_HUGGINGFACE_DOWNLOAD_SECRET_NAME,
            {"HF_TOKEN": token},
            allow_existing=False,
            environment_name=environment,
        )
    except Exception:
        raise SetupError(
            "Secret creation unconfirmed; inspect Modal before retrying"
        ) from None
    print(f"Created CPU-staging-only Modal Secret: {MODAL_HUGGINGFACE_DOWNLOAD_SECRET_NAME}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, help="Explicit Modal profile")
    parser.add_argument("--environment", required=True, help="Explicit Modal environment")
    parser.add_argument("--env-file", type=Path, help="Private dotenv file containing HF_TOKEN")
    parser.add_argument("--apply", action="store_true", help="Create only the named Secret")
    args = parser.parse_args(argv)
    try:
        create_secret(profile=args.profile, environment=args.environment,
                      apply=args.apply, env_file=args.env_file)
    except SetupError as exc:
        print(f"Setup error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
