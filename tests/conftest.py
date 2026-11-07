from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from translation_ai_inference.api import create_api
from translation_ai_inference.database import Base, make_engine, make_session_factory
from translation_ai_inference.repository import JobRepository
from translation_ai_inference.settings import Settings


@pytest.fixture()
def client_factory(tmp_path: Path):
    engines = []

    def create(dispatcher_mode="inline-mock", dispatcher=None, **settings_overrides):
        path = tmp_path / "test-jobs.sqlite3"
        engine = make_engine(f"sqlite+pysqlite:///{path}")
        Base.metadata.create_all(engine)
        engines.append(engine)
        repo = JobRepository(make_session_factory(engine))
        settings = Settings(database_url=f"sqlite+pysqlite:///{path}",
                            api_bearer_token="unit-test-token", dispatcher_mode=dispatcher_mode,
                            **settings_overrides)
        client = TestClient(create_api(settings, repository=repo, dispatcher=dispatcher))
        return client, repo

    yield create
    for engine in engines:
        engine.dispose()


@pytest.fixture()
def headers():
    return {"Authorization": "Bearer unit-test-token", "Idempotency-Key": "same-request"}


@pytest.fixture()
def translation_payload():
    return {"model": "hy_mt2_30b", "source_language": "en", "target_language": "vi",
            "text": "Good morning!"}
