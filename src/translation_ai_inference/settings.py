"""Environment settings: never contain real credentials in source control."""
from dataclasses import dataclass
from os import environ


@dataclass(frozen=True)
class Settings:
    database_url: str
    api_bearer_token: str
    request_owner: str = "single-tenant-api"
    dispatcher_mode: str = "record-only"
    max_input_characters: int = 1000

    @classmethod
    def from_environment(cls) -> "Settings":
        database_url = environ.get("TRANSLATION_INFERENCE_DATABASE_URL", "")
        api_bearer_token = environ.get("TRANSLATION_API_BEARER_TOKEN", "")
        dispatcher_mode = environ.get("TRANSLATION_DISPATCHER_MODE", "record-only")
        if not database_url:
            raise RuntimeError("TRANSLATION_INFERENCE_DATABASE_URL must be configured")
        if not api_bearer_token or api_bearer_token.lower() in {"changeme", "replace-me"}:
            raise RuntimeError("TRANSLATION_API_BEARER_TOKEN must contain a real local secret")
        if dispatcher_mode not in {"record-only", "inline-mock", "modal-cpu-mock"}:
            raise RuntimeError("Unknown TRANSLATION_DISPATCHER_MODE")
        return cls(database_url=database_url, api_bearer_token=api_bearer_token,
                   dispatcher_mode=dispatcher_mode)
