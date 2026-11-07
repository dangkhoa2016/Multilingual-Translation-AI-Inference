"""Environment settings: never contain real credentials in source control."""
from dataclasses import dataclass
from os import environ

from .gpu_budget import configured_estimate


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
        if not api_bearer_token or api_bearer_token.lower() in {"changeme", "replace-me"}:
            raise RuntimeError("TRANSLATION_API_BEARER_TOKEN must contain a real local secret")
        if dispatcher_mode not in {"record-only", "inline-mock", "modal-cpu-mock", "modal-gpu"}:
            raise RuntimeError("Unknown TRANSLATION_DISPATCHER_MODE")
        limits = {}
        for key, variable, default in (
            ("max_jobs_per_minute", "TRANSLATION_MAX_JOBS_PER_MINUTE", 10),
            ("max_jobs_per_day", "TRANSLATION_MAX_JOBS_PER_DAY", 100),
            ("max_model_runs_per_day", "TRANSLATION_MAX_MODEL_RUNS_PER_DAY", 200),
            ("max_attempts_per_model", "TRANSLATION_MAX_ATTEMPTS_PER_MODEL", 2),
        ):
            value = int(environ.get(variable, str(default)))
            if value < 1:
                raise ValueError(f"{variable} must be a positive integer")
            limits[key] = value
        estimate_per_run, budget_per_day = configured_estimate(
            environ.get("TRANSLATION_ESTIMATED_GPU_USD_PER_RUN"),
            environ.get("TRANSLATION_MAX_ESTIMATED_GPU_USD_PER_DAY"),
        )
        return cls(
            database_url=database_url, api_bearer_token=api_bearer_token,
            dispatcher_mode=dispatcher_mode,
            estimated_gpu_microusd_per_run=estimate_per_run,
            max_estimated_gpu_microusd_per_day=budget_per_day,
            **limits,
        )
