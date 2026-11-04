"""Worker connections are released on every invocation, without waiting for GC."""
from unittest.mock import patch

import pytest
from sqlalchemy import event

import modal_app
from multilingual_translation_ai_inference import database
from multilingual_translation_ai_inference.gpu_runtime import (
    ExecutionUncertain,
    InferenceFailure,
    L40SModelRuntime,
    UnsupportedLanguagePair,
)
from multilingual_translation_ai_inference.repository import JobRepository


@pytest.mark.parametrize("worker_kind", ["gpu", "cpu"])
@pytest.mark.parametrize("outcome", ["success", "duplicate", "failure", "claim_error", "persist_error"])
def test_worker_releases_its_engine_on_all_paths(
    client_factory, translation_payload, monkeypatch, worker_kind, outcome,
):
    client, repo = client_factory(dispatcher_mode="record-only")
    posted = client.post("/v1/jobs/translations", json=translation_payload,
                         headers={"Authorization": "Bearer unit-test-token-2026"}).json()
    run = repo.get(posted["job_id"], "single-tenant-api").runs[0]
    claim = repo.claim_dispatch(run.id)
    monkeypatch.setenv("TRANSLATION_INFERENCE_DATABASE_URL", str(repo.session_factory.kw["bind"].url))
    original = database.make_engine
    engines, disposed = [], []
    def tracked_engine(url):
        engine = original(url)
        engines.append(engine)
        event.listen(engine, "engine_disposed", lambda e: disposed.append(e))
        return engine
    monkeypatch.setattr(database, "make_engine", tracked_engine)
    runtime = L40SModelRuntime("hy_mt2_30b")
    monkeypatch.setattr(runtime, "translate", lambda *args: ("Synthetic result", 3, 4))
    if outcome == "failure":
        def fail(*args):
            raise InferenceFailure("Synthetic confirmed failure")
        if worker_kind == "gpu":
            monkeypatch.setattr(runtime, "translate", fail)
        else:
            monkeypatch.setattr("multilingual_translation_ai_inference.worker.process_mock_translation_run", fail)
    if outcome == "claim_error":
        monkeypatch.setattr(JobRepository, "start_run", lambda *args: (_ for _ in ()).throw(RuntimeError("claim")))
    if outcome == "persist_error":
        monkeypatch.setattr(JobRepository, "finish_run", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("persist")))
    def invoke():
        if worker_kind == "gpu":
            return runtime.process_job(run.id, claim)
        return modal_app.translation_inference_cpu_mock_job_worker.local(run.id, claim)
    try:
        with patch("multilingual_translation_ai_inference.telemetry.sample_gpu", return_value={}):
            if outcome in {"claim_error", "persist_error"} or (outcome == "failure" and worker_kind == "cpu"):
                with pytest.raises((RuntimeError, InferenceFailure)):
                    invoke()
            else:
                assert invoke() is (outcome != "failure")
                if outcome == "duplicate":
                    assert invoke() is False
        assert engines and disposed == engines
    finally:
        for engine in engines:
            engine.dispose()


@pytest.mark.parametrize("error", [ExecutionUncertain, UnsupportedLanguagePair])
def test_gpu_releases_engine_on_uncertain_and_unsupported_runs(
    client_factory, translation_payload, monkeypatch, error,
):
    client, repo = client_factory(dispatcher_mode="record-only")
    posted = client.post("/v1/jobs/translations", json=translation_payload,
                         headers={"Authorization": "Bearer unit-test-token-2026"}).json()
    rid = repo.get(posted["job_id"], "single-tenant-api").runs[0].id
    token = repo.claim_dispatch(rid)
    engine = database.make_engine(str(repo.session_factory.kw["bind"].url))
    disposed = []
    event.listen(engine, "engine_disposed", lambda e: disposed.append(e))
    monkeypatch.setattr(database, "make_engine", lambda url: engine)
    monkeypatch.setenv("TRANSLATION_INFERENCE_DATABASE_URL", str(engine.url))
    runtime = L40SModelRuntime("hy_mt2_30b")
    monkeypatch.setattr(runtime, "translate", lambda *args: (_ for _ in ()).throw(error("synthetic")))
    try:
        assert runtime.process_job(rid, token) is False
        assert disposed == [engine]
    finally:
        engine.dispose()
