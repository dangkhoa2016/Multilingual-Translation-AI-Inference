"""Execute opt-in probes offline: real reporting must preserve archived evidence."""
import io
import json
import stat
import sys
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID

import pytest

from multilingual_translation_ai_inference.settings import Settings
from scripts.api import smoke_dispatch, smoke_gpu
from scripts.deployment import verify_gpu_workers


def _report_locations(tmp_path, monkeypatch, module, constant, name):
    archive = tmp_path / "repository" / "reports" / name
    archive.parent.mkdir(parents=True)
    archive.write_text("archived-sanitized-evidence", encoding="utf-8")
    monkeypatch.setattr(module, constant, archive, raising=False)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setattr(smoke_gpu.tempfile, "gettempdir", lambda: str(runtime))
    return archive, runtime


def _private_report(runtime, name):
    files = list(runtime.glob("*/" + name))
    assert len(files) == 1
    path = files[0]
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("failed", [False, True])
def test_readiness_probe_preserves_archive_and_excludes_runtime_identifiers(
    tmp_path, monkeypatch, capsys, failed,
):
    archive, runtime = _report_locations(tmp_path, monkeypatch, verify_gpu_workers,
                                        "REPORT_PATH", "deployed_gpu_readiness.json")
    classes = verify_gpu_workers.MODAL_GPU_INFERENCE_CLASS_NAMES
    identities = ["GPU-" + str(UUID(int=i + 1)) for i in range(4)]
    private = "SYNTHETIC_PRIVATE_RPC_DETAIL"

    def from_name(app, cls_name):
        model = next(key for key, value in classes.items() if value == cls_name)
        index = list(classes).index(model)

        def get(**kwargs):
            if failed and index == 0:
                raise TimeoutError(private)
            return {"model": model, "gpu": "NVIDIA L40S", "model_loaded": True,
                    "gpu_uuid": identities[index], "device_id": private,
                    "ready_seconds": 1.0}

        return lambda: SimpleNamespace(readiness=SimpleNamespace(
            spawn=lambda: SimpleNamespace(get=get)))

    monkeypatch.setattr(verify_gpu_workers.modal.Cls, "from_name", from_name)
    monkeypatch.setattr(sys, "argv", ["verify_gpu_workers.py", "--run"])
    if failed:
        with pytest.raises(SystemExit):
            verify_gpu_workers.main()
    else:
        verify_gpu_workers.main()
    assert archive.read_text(encoding="utf-8") == "archived-sanitized-evidence"
    report = _private_report(runtime, "deployed_gpu_readiness.json")
    assert report["status"] == ("readiness_failed" if failed else "four_deployed_gpu_classes_ready")
    text = json.dumps(report) + capsys.readouterr().out
    assert private not in text
    assert all(identity not in text for identity in identities)
    assert '"gpu_uuid"' not in text and '"device_id"' not in text


def test_dispatch_probe_preserves_archive_and_omits_live_job_identity(
    tmp_path, monkeypatch, capsys, client_factory,
):
    archive, runtime = _report_locations(tmp_path, monkeypatch, smoke_dispatch,
                                        "REPORT", "postgresql_gpu_jobs.json")
    client, repo = client_factory(dispatcher_mode="record-only")
    settings = Settings(database_url=str(repo.session_factory.kw["bind"].url),
                        api_bearer_token="unit-test-token-2026")
    monkeypatch.setattr(smoke_dispatch.Settings, "from_environment", lambda: settings)
    ids = []

    def from_name(app, cls_name):
        def spawn(run_id, token):
            ids.append(run_id)
            assert repo.start_run(run_id, token) is not None
            assert repo.finish_run(run_id, token, "Synthetic external worker output", mock=False)
            return SimpleNamespace(object_id="synthetic-call-id")
        return lambda: SimpleNamespace(process_job=SimpleNamespace(spawn=spawn))

    def urlopen(request, **kwargs):
        response = client.get(urlsplit(request.full_url).path, headers=dict(request.header_items()))
        assert response.status_code == 200
        payload = response.json()
        if "job_id" in payload:
            ids.append(payload["job_id"])
        stream = io.BytesIO(json.dumps(payload).encode("utf-8"))
        stream.status = 200
        return stream

    monkeypatch.setattr(verify_gpu_workers.modal.Cls, "from_name", from_name)
    monkeypatch.setattr(smoke_dispatch.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(sys, "argv", ["smoke_dispatch.py", "--run", "--base-url", "https://gateway.example.test"])
    smoke_dispatch.main()
    assert archive.read_text(encoding="utf-8") == "archived-sanitized-evidence"
    report = _private_report(runtime, "postgresql_gpu_jobs.json")
    assert report["status"] == "four_real_gpu_jobs_persisted_and_read_by_gateway"
    assert len(report["results"]) == 4
    text = json.dumps(report) + capsys.readouterr().out
    assert ids and all(identity not in text for identity in ids)
    assert '"test_job_id"' not in text
