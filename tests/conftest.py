from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from multilingual_translation_ai_inference.api import create_api
from multilingual_translation_ai_inference.database import Base, make_engine, make_session_factory
from multilingual_translation_ai_inference.repository import JobRepository
from multilingual_translation_ai_inference.settings import Settings


@pytest.fixture()
def client_factory(tmp_path: Path):
    engines = []

    def create(dispatcher_mode="inline-mock", dispatcher=None, **settings_overrides):
        path = tmp_path / "test-jobs.sqlite3"
        engine = make_engine(f"sqlite+pysqlite:///{path}")
        Base.metadata.create_all(engine)
        engines.append(engine)
        repo = JobRepository(make_session_factory(engine))
        # Tests may use a dedicated valid-length Bearer secret without changing shared fixtures.
        token = settings_overrides.pop("api_bearer_token", "unit-test-token-2026")
        settings = Settings(database_url=f"sqlite+pysqlite:///{path}",
                            api_bearer_token=token, dispatcher_mode=dispatcher_mode,
                            **settings_overrides)
        client = TestClient(create_api(settings, repository=repo, dispatcher=dispatcher))
        return client, repo

    yield create
    for engine in engines:
        engine.dispose()


@pytest.fixture()
def headers():
    return {"Authorization": "Bearer unit-test-token-2026", "Idempotency-Key": "same-request"}


@pytest.fixture()
def translation_payload():
    return {"model": "hy_mt2_30b", "source_language": "en", "target_language": "vi",
            "text": "Good morning!"}
