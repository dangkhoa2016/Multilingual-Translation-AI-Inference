"""Create two Modal Secrets from one private .env; dry-run by default."""
import argparse
import io
import os
import re
import stat
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

from dotenv import dotenv_values

from multilingual_translation_ai_inference.resource_names import (
    MODAL_API_AUTH_SECRET_NAME,
    MODAL_POSTGRESQL_CONNECTION_SECRET_NAME,
)
from multilingual_translation_ai_inference.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
DB = "TRANSLATION_INFERENCE_DATABASE_URL"
MIGRATE = "TRANSLATION_INFERENCE_MIGRATION_DATABASE_URL"
TOKEN = "TRANSLATION_API_BEARER_TOKEN"
MODE = "TRANSLATION_DISPATCHER_MODE"
OPTIONAL = (
    "TRANSLATION_MAX_JOBS_PER_MINUTE", "TRANSLATION_MAX_JOBS_PER_DAY",
    "TRANSLATION_MAX_MODEL_RUNS_PER_DAY", "TRANSLATION_MAX_ATTEMPTS_PER_MODEL",
    "TRANSLATION_AUTH_FAILURE_LIMIT", "TRANSLATION_AUTH_FAILURE_WINDOW_SECONDS",
    "TRANSLATION_AUTH_LOCKOUT_SECONDS", "TRANSLATION_AUTH_MAX_TRACKED_CLIENTS",
    "TRANSLATION_MAX_API_BODY_BYTES", "TRANSLATION_MAX_REQUESTS_PER_MINUTE_PER_PEER",
    "TRANSLATION_MAX_REQUESTS_PER_MINUTE_PER_PROCESS",
    "TRANSLATION_MAX_JOB_POLLS_PER_MINUTE", "TRANSLATION_MAX_PENDING_JOBS_PER_OWNER",
    "TRANSLATION_MAX_PENDING_RUNS_PER_MODEL", "TRANSLATION_ESTIMATED_GPU_USD_PER_RUN",
    "TRANSLATION_MAX_ESTIMATED_GPU_USD_PER_DAY", "TRANSLATION_AUDIT_LOG_ENABLED",
)
ALLOWED = set(OPTIONAL) | {DB, MIGRATE, TOKEN, MODE}
PLACEHOLDERS = ("YOUR_OWN", "REPLACE-WITH", "DB_USER", "DB_NAME",
                "DIRECT_HOST", "RUNTIME_HOST", "URL_ENCODED_PASSWORD")


class SetupError(Exception):
    pass


def read_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file() or path.name == ".env.example":
        raise SetupError("Prepare a private .env from .env.example")
    if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise SetupError("Restrict .env permissions: chmod 600 .env")
    result: dict[str, str] = {}
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise SetupError(f"Invalid .env line {line_no}")
        key, raw = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", key):
            raise SetupError(f"Invalid .env key on line {line_no}")
        if key not in ALLOWED:
            continue
        if key in result:
            raise SetupError(f"Duplicate .env key: {key}")
        # Align with the runtime dotenv parser. In particular, an unquoted
        # "#" inside a printable token is literal, not a shell comment.
        # Parse one line at a time so duplicate keys remain detectable.
        try:
            parsed = dotenv_values(stream=io.StringIO(f"{key}={raw}\n"),
                                   interpolate=False, verbose=False)
        except Exception:
            raise SetupError(f"Invalid .env value for {key}") from None
        if key not in parsed or parsed[key] is None:
            raise SetupError(f"Invalid quotes or value in {key}")
        result[key] = parsed[key]
    return result


def database_name(value: str, key: str) -> str:
    if any(p.lower() in value.lower() for p in PLACEHOLDERS):
        raise SetupError(f"Replace {key} placeholder")
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"postgresql", "postgresql+psycopg"}:
            raise SetupError(f"{key} must use PostgreSQL")
        if not parsed.hostname or not parsed.username or not parsed.password:
            raise SetupError(f"{key} is missing host or credentials")
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise SetupError(f"{key} has invalid port")
        name = unquote(parsed.path.lstrip("/"))
        if not name or "/" in name:
            raise SetupError(f"{key} is missing database name")
        return name
    except ValueError:
        raise SetupError(f"{key} has invalid URL") from None


def prepare(values: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    for key in (DB, MIGRATE, TOKEN):
        if not values.get(key):
            raise SetupError(f"Set {key} in private .env")
    if database_name(values[DB], DB) != database_name(values[MIGRATE], MIGRATE):
        raise SetupError("Runtime and migration must use the same PostgreSQL database")
    if values[TOKEN].lower().startswith("replace-") or any(
        p.lower() in values[TOKEN].lower() for p in PLACEHOLDERS
    ):
        raise SetupError("Replace placeholder API Bearer token")
    database = {DB: values[DB]}
    api = {TOKEN: values[TOKEN], MODE: "modal-cpu-mock"}
    api.update({key: values[key] for key in OPTIONAL if key in values})
    with patch.dict(os.environ, {**database, **api}, clear=True):
        try:
            Settings.from_environment()
        except (RuntimeError, ValueError):
            raise SetupError("Invalid API token or runtime options in .env") from None
    return database, api


def provision(database: dict[str, str], api: dict[str, str],
              profile: str, environment: str) -> None:
    os.environ["MODAL_PROFILE"] = profile
    os.environ["MODAL_ENVIRONMENT"] = environment
    try:
        import modal
        existing = {secret.name for secret in modal.Secret.objects.list(
            environment_name=environment,
        )}
    except Exception:
        raise SetupError("Could not inspect Modal Secrets; verify profile/environment") from None
    names = (MODAL_POSTGRESQL_CONNECTION_SECRET_NAME, MODAL_API_AUTH_SECRET_NAME)
    if any(name in existing for name in names):
        raise SetupError("A target Secret already exists; no changes made")
    for name, data in zip(names, (database, api)):
        try:
            modal.Secret.objects.create(name, data, allow_existing=False,
                                        environment_name=environment)
        except Exception:
            raise SetupError(f"Creation of {name} unconfirmed; no overwrite attempted. "
                             "Inspect Modal before retrying; the first Secret might exist") from None
        print(f"Created Modal Secret: {name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--profile", default=os.environ.get("MODAL_PROFILE"))
    parser.add_argument("--environment", default=os.environ.get("MODAL_ENVIRONMENT"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    database, api = prepare(read_dotenv(args.env_file))
    print("Validated private .env. Migration URL stays local; initial mode=modal-cpu-mock.")
    if not args.apply:
        print("Dry run: no Modal operation, migration, deployment, or GPU launch.")
        return 0
    if not args.profile or not args.environment:
        raise SetupError("Specify --profile and --environment or export MODAL_* variables")
    print(f"Creating Secrets in profile={args.profile}, environment={args.environment}")
    provision(database, api, args.profile, args.environment)
    print("Two Secrets created. Run Alembic and deployment separately.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SetupError as exc:
        print(f"Setup error: {exc}", file=sys.stderr)
        sys.exit(1)
