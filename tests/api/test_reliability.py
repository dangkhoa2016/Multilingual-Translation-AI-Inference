"""CPU-only Reliability regressions for 1000-character boundaries and uncertain execution."""
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from multilingual_translation_ai_inference import gpu_runtime
from multilingual_translation_ai_inference.database import Job
from multilingual_translation_ai_inference.gpu_runtime import ExecutionUncertain, L40SModelRuntime
from scripts.api import container_reuse, reliability_smoke, smoke_gpu
from scripts.api.reliability_smoke import (
    BOUNDARY_TEXT,
    CONCURRENT_TEXTS,
    request_payload,
    sanitized_run,
    validate_fixture,
)


def test_boundary_fixture_is_1000_codepoints_not_1000_bytes():
    validate_fixture()
    assert len(BOUNDARY_TEXT) == 1000
    assert len(BOUNDARY_TEXT.encode("utf-8")) > 1000
    assert len(BOUNDARY_TEXT + "x") == 1001
    assert "\n\n" in BOUNDARY_TEXT
    assert len(set(CONCURRENT_TEXTS)) == 2


@pytest.mark.parametrize("script", ("reliability_smoke.py", "container_reuse.py"))
def test_probe_documented_direct_command_is_cpu_only(script):
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    result = subprocess.run(
        [sys.executable, str(root / "scripts/api" / script)], cwd=root,
        env=env, text=True, capture_output=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert ("CPU-only dry-run" if script == "reliability_smoke.py" else "No GPUs started") in result.stdout


def test_negative_probe_rejects_invalid_structure_without_creating_jobs(client_factory, headers):
    client, repo = client_factory(dispatcher_mode="record-only")
    outcomes = reliability_smoke.negative_input_tests(client, "", headers)
    assert outcomes == {"1001_codepoints": 422, "empty_whitespace": 422,
                        "same_language": 422, "invalid_language_label": 422}
    with repo.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 0
    # An arbitrary alphabetic label remains valid under the open-language contract.
    response = client.post("/v1/jobs/translations", headers=headers, json={
        **request_payload("Hello", model="hy_mt2_30b"), "target_language": "xx",
    })
    assert response.status_code == 202


@pytest.fixture()
def isolated_runtime_reports(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    public = repository / "reports"
    public.mkdir(parents=True)
    names = ("unicode_input_boundary.json", "concurrent_model_jobs.json", "gpu_container_reuse.json")
    originals = {name: public / name for name in names}
    for name, path in originals.items():
        path.write_text("approved historical evidence: " + name)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    # Isolate the legacy writer paths too: a failing regression must not touch real reports.
    monkeypatch.setattr(reliability_smoke, "REPORT_DIRECTORY", public, raising=False)
    monkeypatch.setattr(container_reuse, "REPORT_PATH", originals["gpu_container_reuse.json"], raising=False)
    monkeypatch.setattr(smoke_gpu, "ROOT", repository)
    monkeypatch.setattr(smoke_gpu.tempfile, "gettempdir", lambda: str(runtime))
    return originals, runtime


@pytest.mark.parametrize("scenario", ("boundary", "concurrency"))
def test_reliability_workflow_keeps_history_and_writes_private_summary(
    client_factory, headers, isolated_runtime_reports, scenario
):
    originals, runtime = isolated_runtime_reports
    client, repo = client_factory()
    operation = reliability_smoke.run_boundary if scenario == "boundary" else reliability_smoke.run_concurrency
    # Exercise real HTTP orchestration and storage; mock output must fail the GPU-result gate.
    with pytest.raises(AssertionError, match="inference failed|did not both finish"):
        operation(client, "", headers, 10)
    for name, path in originals.items():
        assert path.read_text() == "approved historical evidence: " + name
    files = list(runtime.glob("*/*.json"))
    assert len(files) == 1
    report_file = files[0]
    expected_name = "unicode_input_boundary.json" if scenario == "boundary" else "concurrent_model_jobs.json"
    assert report_file.name == expected_name
    assert stat.S_IMODE(report_file.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(report_file.stat().st_mode) == 0o600
    raw = report_file.read_text()
    report = json.loads(raw)
    assert report["status"] == "failed_or_incomplete"
    assert "job_id" not in report and "job_ids" not in report
    with repo.session_factory() as session:
        ids = session.scalars(select(Job.id)).all()
        assert len(ids) == (1 if scenario == "boundary" else 2)
        assert all(job_id not in raw for job_id in ids)
    assert BOUNDARY_TEXT not in raw and all(text not in raw for text in CONCURRENT_TEXTS)


def test_container_probe_keeps_history_and_omits_device_identifier(
    isolated_runtime_reports, monkeypatch, capsys
):
    originals, runtime = isolated_runtime_reports
    calls = []
    gpu_uuid = "GPU-12345678-1234-1234-1234-123456789abc"

    def readiness():
        calls.append("readiness")
        return {"model": "hy_mt2_30b", "model_loaded": True, "single_GPU": True,
                "gpu": "NVIDIA L40S", "gpu_uuid": gpu_uuid, "ready_seconds": 1.0,
                "sampled_vram_mib": 31000}

    worker = SimpleNamespace(readiness=SimpleNamespace(remote=readiness))
    monkeypatch.setattr(container_reuse.modal.Cls, "from_name", lambda *args: lambda: worker)
    monkeypatch.setattr(sys, "argv", ["container_reuse.py", "--run"])
    container_reuse.main()
    assert calls == ["readiness", "readiness"]
    for name, path in originals.items():
        assert path.read_text() == "approved historical evidence: " + name
    files = list(runtime.glob("*/gpu_container_reuse.json"))
    assert len(files) == 1
    raw = files[0].read_text()
    report = json.loads(raw)
    assert report["same_gpu_uuid"] is True and report["warm_container_reuse_observed"] is True
    assert len(report["measurements"]) == 2
    assert all("gpu_uuid" not in row for row in report["measurements"])
    assert gpu_uuid not in raw and gpu_uuid not in capsys.readouterr().out
    assert stat.S_IMODE(files[0].stat().st_mode) == 0o600


def test_api_1000_accepted_and_1001_rejected_before_db_charge(client_factory, headers):
    client, repo = client_factory(dispatcher_mode="record-only")
    url = "/v1/jobs/translations"
    invalid = request_payload(BOUNDARY_TEXT + "x", model="hy_mt2_30b")
    response = client.post(url, headers=headers, json=invalid)
    assert response.status_code == 422
    with repo.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 0
    valid = request_payload(BOUNDARY_TEXT, model="hy_mt2_30b")
    accepted = client.post(url, headers=headers, json=valid)
    assert accepted.status_code == 202
    assert client.post(url, headers=headers, json=valid).json()["job_id"] == accepted.json()["job_id"]
    conflict = client.post(url, headers=headers,
                           json=request_payload(BOUNDARY_TEXT[:-1] + "!", model="hy_mt2_30b"))
    assert conflict.status_code == 409
    with repo.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 1
    job = client.get(accepted.json()["status_url"], headers=headers).json()
    assert job["status"] == "queued"
    assert job["runs"][0]["status"] == "queued"


def test_public_unauthorized_cannot_create_1000_character_job(client_factory):
    client, repo = client_factory(dispatcher_mode="record-only")
    response = client.post(
        "/v1/jobs/translations",
        json=request_payload(BOUNDARY_TEXT, model="hy_mt2_30b"),
    )
    assert response.status_code == 401
    with repo.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 0


def test_1001_input_rejected_for_four_model_benchmark(client_factory, headers):
    client, repo = client_factory(dispatcher_mode="record-only")
    payload = request_payload(
        BOUNDARY_TEXT + "x",
        models=("hy_mt2_30b", "index_35b", "gemma4_31b_it", "qwen35_35b"),
    )
    response = client.post("/v1/jobs/benchmarks", json=payload, headers=headers)
    assert response.status_code == 422
    with repo.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 0


@pytest.mark.parametrize("error", [
    TimeoutError("The local GPU socket timed out"),
    ConnectionError("The local GPU connection dropped"),
    ValueError("Invalid JSON response from llama-server"),
])
def test_gpu_transport_unknown_result_never_reports_confirmed_failure(monkeypatch, error):
    runtime = L40SModelRuntime("hy_mt2_30b")

    class Process:
        @staticmethod
        def poll():
            return None

    runtime.process = Process()
    runtime.spec = {"gguf_filename": "pinned.gguf"}

    def broken_transport(*args, **kwargs):
        raise error

    monkeypatch.setattr(gpu_runtime, "_request_json", broken_transport)
    with pytest.raises(ExecutionUncertain, match="Completion status unknown"):
        runtime.translate(
            "en", "vi", "One nonempty source sentence.",
            '{"preserve_formatting": true}',
        )


def test_sanitized_report_excludes_translation_text():
    translated = "Bản dịch riêng tư."
    sanitized = sanitized_run({
        "model": "hy_mt2_30b", "status": "completed",
        "translation_text": translated, "is_mock_result": False,
        "attempt_no": 1, "error_code": None,
    })
    assert sanitized["translation_sha256"] == hashlib.sha256(translated.encode()).hexdigest()
    assert sanitized["translation_characters"] == len(translated)
    assert "translation_text" not in sanitized
    assert translated not in repr(sanitized)


def _reliability_report(name: str) -> dict:
    import json
    from pathlib import Path

    return json.loads(
        (Path(__file__).resolve().parents[2] / "reports" / name).read_text(
            encoding="utf-8"
        )
    )


def test_recorded_boundary_report_has_four_nonmock_models_and_rejections():
    report = _reliability_report("unicode_input_boundary.json")
    assert report["status"] == "pass"
    assert report["input_codepoints"] == 1000
    assert report["input_utf8_bytes"] > 1000
    assert len(report["runs"]) == 4
    assert {run["model"] for run in report["runs"]} == {
        "hy_mt2_30b", "index_35b", "gemma4_31b_it", "qwen35_35b",
    }
    assert all(v == 422 for v in report["rejected_inputs_http_422"].values())
    assert set(report["rejected_inputs_http_422"]) == {
        "1001_codepoints", "empty_whitespace", "same_language",
        "unknown_language",
    }
    assert report["idempotent_job_reused"] is True
    assert report["conflicting_payload_http_409"] == 409
    assert report["parent_job_status"] == "completed"
    for run in report["runs"]:
        assert run["status"] == "completed"
        assert run["is_mock_result"] is False
        assert run["has_nonempty_output"] is True
        assert run["attempt_no"] == 1
        assert run["translation_characters"] > 0
        assert len(run["translation_sha256"]) == 64
        assert "translation_text" not in run


def test_recorded_same_model_report_has_two_distinct_completed_jobs():
    report = _reliability_report("concurrent_model_jobs.json")
    assert report["status"] == "pass"
    assert report["gpu_model"] == "hy_mt2_30b"
    assert report["number_of_jobs"] == 2
    assert report["unique_job_ids"] == 2
    assert len(report["post_latencies_seconds"]) == 2
    assert len(report["runs"]) == 2
    assert all(run["status"] == "completed" and
               run["is_mock_result"] is False and
               run["has_nonempty_output"] and
               run["attempt_no"] == 1 for run in report["runs"])


def test_recorded_worker_reuse_report_preserves_cold_start_uncertainty():
    report = _reliability_report("gpu_container_reuse.json")
    assert report["status"] == "two_readiness_calls_passed"
    assert report["first_call_cold_start_guaranteed"] is False
    assert report["warm_container_reuse_observed"] is True
    assert report["same_gpu_uuid"] is True
    assert len(report["measurements"]) == 2
    first, second = report["measurements"]
    assert first["gpu_uuid"] == second["gpu_uuid"]
    assert first["model"] == second["model"] == "hy_mt2_30b"
    assert second["rpc_wall_seconds"] < first["rpc_wall_seconds"]
    assert first["model_initialization_seconds"] > 0
