"""Offline HTTP smoke via TestClient. No GPU, network or cloud PostgreSQL required."""
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from translation_ai_inference.api import create_api
from translation_ai_inference.database import Base, make_engine, make_session_factory
from translation_ai_inference.repository import JobRepository
from translation_ai_inference.settings import Settings


def main():
    with TemporaryDirectory() as directory:
        url = f"sqlite+pysqlite:///{Path(directory) / 'local-demo.sqlite3'}"
        engine = make_engine(url)
        Base.metadata.create_all(engine)
        settings = Settings(database_url=url, api_bearer_token="demo-secret-only",
                            dispatcher_mode="inline-mock")
        client = TestClient(create_api(settings,
                                     repository=JobRepository(make_session_factory(engine))))
        headers = {"Authorization": "Bearer demo-secret-only", "Idempotency-Key": "demo-001"}
        request = {"model": "hy_mt2_30b", "source_language": "en",
                   "target_language": "vi", "text": "The quick brown fox jumps over the lazy dog."}
        response = client.post("/v1/jobs/translations", headers=headers, json=request)
        response.raise_for_status()
        print("POST", response.status_code, response.json())
        job = client.get(response.json()["status_url"], headers=headers)
        job.raise_for_status()
        print("GET", job.status_code, job.json())
        assert job.json()["runs"][0]["is_mock_result"] is True
        engine.dispose()


if __name__ == "__main__":
    main()
