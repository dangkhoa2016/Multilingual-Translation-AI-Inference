"""Provider changes must not require renaming Modal or environment resources."""

import pytest

from multilingual_translation_ai_inference.resource_names import (
    MODAL_API_AUTH_SECRET_NAME,
    MODAL_APP_NAME,
    MODAL_GPU_WEIGHT_VOLUME_NAMES,
    MODAL_POSTGRESQL_CONNECTION_SECRET_NAME,
)
from multilingual_translation_ai_inference.settings import Settings


def test_modal_names_do_not_reference_a_postgresql_host():
    assert MODAL_APP_NAME == "multilingual-translation-ai-inference-api-and-model-workers"
    assert MODAL_POSTGRESQL_CONNECTION_SECRET_NAME == "multilingual-translation-ai-inference-postgresql-connection"
    assert MODAL_API_AUTH_SECRET_NAME == "multilingual-translation-ai-inference-api-authentication"
    for name in (MODAL_APP_NAME, MODAL_POSTGRESQL_CONNECTION_SECRET_NAME,
                 MODAL_API_AUTH_SECRET_NAME, *MODAL_GPU_WEIGHT_VOLUME_NAMES.values()):
        assert "neon" not in name.lower()


def test_runtime_connection_string_is_selected_by_provider_independent_key(monkeypatch):
    monkeypatch.setenv("TRANSLATION_INFERENCE_DATABASE_URL", "postgresql+psycopg://user:password@pg.provider-one.test/translations")
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", "test-long-bearer-token")
    settings = Settings.from_environment()
    assert settings.database_url.endswith("@pg.provider-one.test/translations")

    monkeypatch.setenv("TRANSLATION_INFERENCE_DATABASE_URL", "postgresql+psycopg://user:password@pg.provider-two.test/translations")
    assert Settings.from_environment().database_url.endswith("@pg.provider-two.test/translations")


def test_legacy_host_named_env_var_is_not_used(monkeypatch):
    monkeypatch.delenv("TRANSLATION_INFERENCE_DATABASE_URL", raising=False)
    monkeypatch.setenv("TRANSLATION_NEON_DATABASE_URL", "sqlite:///should-not-be-read.db")
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", "test-long-bearer-token")
    with pytest.raises(RuntimeError, match="TRANSLATION_INFERENCE_DATABASE_URL"):
        Settings.from_environment()
