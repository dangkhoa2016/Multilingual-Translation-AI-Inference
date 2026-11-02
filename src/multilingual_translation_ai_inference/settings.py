"""Environment settings: never contain real credentials in source control."""
from dataclasses import dataclass
from os import environ

from .gpu_budget import configured_estimate


def _valid_api_bearer_token(token: str) -> bool:
    """Apply one credential policy to env loading and direct Settings construction."""
    return (
        isinstance(token, str)
        and 16 <= len(token) <= 4096
        and token.isascii()
        and all(33 <= ord(char) <= 126 for char in token)
        and token.lower() not in {"changeme", "replace-me"}
    )


@dataclass(frozen=True)
class Settings:
    database_url: str
    api_bearer_token: str
    request_owner: str = "single-tenant-api"
    dispatcher_mode: str = "record-only"
    max_input_characters: int = 1000
    max_jobs_per_minute: int = 10
    max_jobs_per_day: int = 100
    max_model_runs_per_day: int = 200
    max_attempts_per_model: int = 2
    # Best-effort authentication guard per CPU gateway process (not per Modal App).
    auth_failure_limit: int = 3
    auth_failure_window_seconds: int = 300
    auth_lockout_seconds: int = 900
    auth_max_tracked_clients: int = 4096
    max_api_body_bytes: int = 65536
    max_requests_per_minute_per_peer: int = 120
    max_requests_per_minute_per_process: int = 600
    max_job_polls_per_minute: int = 120
    max_pending_jobs_per_owner: int = 20
    max_pending_runs_per_model: int = 20
    audit_log_enabled: bool = False

    def __post_init__(self) -> None:
        if type(self.audit_log_enabled) is not bool:
            raise ValueError("TRANSLATION_AUDIT_LOG_ENABLED must be a boolean")
        if not _valid_api_bearer_token(self.api_bearer_token):
            raise ValueError(
                "TRANSLATION_API_BEARER_TOKEN must be a 16–4096-character printable ASCII secret "
                "without spaces or control characters"
            )
        for name, value, ceiling in (
            ("TRANSLATION_AUTH_FAILURE_LIMIT", self.auth_failure_limit, 100),
            ("TRANSLATION_AUTH_FAILURE_WINDOW_SECONDS", self.auth_failure_window_seconds, 86400),
            ("TRANSLATION_AUTH_LOCKOUT_SECONDS", self.auth_lockout_seconds, 86400),
            ("TRANSLATION_AUTH_MAX_TRACKED_CLIENTS", self.auth_max_tracked_clients, 100000),
            ("TRANSLATION_MAX_API_BODY_BYTES", self.max_api_body_bytes, 1048576),
            ("TRANSLATION_MAX_REQUESTS_PER_MINUTE_PER_PEER", self.max_requests_per_minute_per_peer, 1000000),
            ("TRANSLATION_MAX_REQUESTS_PER_MINUTE_PER_PROCESS", self.max_requests_per_minute_per_process, 1000000),
            ("TRANSLATION_MAX_JOB_POLLS_PER_MINUTE", self.max_job_polls_per_minute, 1000000),
            ("TRANSLATION_MAX_PENDING_JOBS_PER_OWNER", self.max_pending_jobs_per_owner, 100000),
            ("TRANSLATION_MAX_PENDING_RUNS_PER_MODEL", self.max_pending_runs_per_model, 100000),
        ):
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError(f"{name} must be an integer between 1 and {ceiling}")
    # Optional and explicitly *estimated* admission reservations, not actual Modal billing.
    estimated_gpu_microusd_per_run: int = 0
    max_estimated_gpu_microusd_per_day: int = 0

    @classmethod
    def from_environment(cls) -> "Settings":
        database_url = environ.get("TRANSLATION_INFERENCE_DATABASE_URL", "")
        api_bearer_token = environ.get("TRANSLATION_API_BEARER_TOKEN", "")
        dispatcher_mode = environ.get("TRANSLATION_DISPATCHER_MODE", "record-only")
        if not database_url:
            raise RuntimeError("TRANSLATION_INFERENCE_DATABASE_URL must be configured")
        if not _valid_api_bearer_token(api_bearer_token):
            raise RuntimeError(
                "TRANSLATION_API_BEARER_TOKEN must be a 16–4096-character printable ASCII secret "
                "without spaces or control characters"
            )
        if dispatcher_mode not in {"record-only", "inline-mock", "modal-cpu-mock", "modal-gpu"}:
            raise RuntimeError("Unknown TRANSLATION_DISPATCHER_MODE")
        limits = {}
        for key, variable, default in (
            ("max_jobs_per_minute", "TRANSLATION_MAX_JOBS_PER_MINUTE", 10),
            ("max_jobs_per_day", "TRANSLATION_MAX_JOBS_PER_DAY", 100),
            ("max_model_runs_per_day", "TRANSLATION_MAX_MODEL_RUNS_PER_DAY", 200),
            ("max_attempts_per_model", "TRANSLATION_MAX_ATTEMPTS_PER_MODEL", 2),
            ("auth_failure_limit", "TRANSLATION_AUTH_FAILURE_LIMIT", 3),
            ("auth_failure_window_seconds", "TRANSLATION_AUTH_FAILURE_WINDOW_SECONDS", 300),
            ("auth_lockout_seconds", "TRANSLATION_AUTH_LOCKOUT_SECONDS", 900),
            ("auth_max_tracked_clients", "TRANSLATION_AUTH_MAX_TRACKED_CLIENTS", 4096),
            ("max_api_body_bytes", "TRANSLATION_MAX_API_BODY_BYTES", 65536),
            ("max_requests_per_minute_per_peer", "TRANSLATION_MAX_REQUESTS_PER_MINUTE_PER_PEER", 120),
            ("max_requests_per_minute_per_process", "TRANSLATION_MAX_REQUESTS_PER_MINUTE_PER_PROCESS", 600),
            ("max_job_polls_per_minute", "TRANSLATION_MAX_JOB_POLLS_PER_MINUTE", 120),
            ("max_pending_jobs_per_owner", "TRANSLATION_MAX_PENDING_JOBS_PER_OWNER", 20),
            ("max_pending_runs_per_model", "TRANSLATION_MAX_PENDING_RUNS_PER_MODEL", 20),
        ):
            value = int(environ.get(variable, str(default)))
            if value < 1:
                raise ValueError(f"{variable} must be a positive integer")
            limits[key] = value
        estimate_per_run, budget_per_day = configured_estimate(
            environ.get("TRANSLATION_ESTIMATED_GPU_USD_PER_RUN"),
            environ.get("TRANSLATION_MAX_ESTIMATED_GPU_USD_PER_DAY"),
        )
        audit = environ.get("TRANSLATION_AUDIT_LOG_ENABLED", "false").strip().lower()
        if audit not in {"true", "false"}:
            raise ValueError("TRANSLATION_AUDIT_LOG_ENABLED must be true or false")
        return cls(
            database_url=database_url, api_bearer_token=api_bearer_token,
            dispatcher_mode=dispatcher_mode, audit_log_enabled=audit == "true",
            estimated_gpu_microusd_per_run=estimate_per_run,
            max_estimated_gpu_microusd_per_day=budget_per_day,
            **limits,
        )
