"""Offline safety regressions: smoke reports never touch tracked public evidence."""
import json
import stat

import pytest

from scripts.api import smoke_gpu


@pytest.mark.parametrize("all_models", [False, True])
def test_runtime_report_is_private_unique_and_does_not_overwrite_public_evidence(
    tmp_path, all_models,
):
    public = tmp_path / "reports"
    public.mkdir()
    name = "gpu_api_four_model_benchmark.json" if all_models else "gpu_api_translation.json"
    tracked = public / name
    tracked.write_text("tracked-public-report-must-stay-unchanged", encoding="utf-8")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    report = {"all_models": all_models, "status": "real_gpu_api_passed", "runs": []}

    first = smoke_gpu.save_private_report(report, temp_parent=str(runtime))
    second = smoke_gpu.save_private_report(report, temp_parent=str(runtime))

    assert first != second
    assert first.parent.parent == runtime.resolve()
    assert first.name == name
    assert stat.S_IMODE(first.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(first.stat().st_mode) == 0o600
    assert json.loads(first.read_text(encoding="utf-8")) == report
    assert tracked.read_text(encoding="utf-8") == "tracked-public-report-must-stay-unchanged"


@pytest.mark.parametrize("report", [
    {"all_models": False, "job_id": "private-job-id"},
    {"all_models": True, "runs": [{"status_url": "/v1/jobs/private-job-id"}]},
    {"all_models": True, "runs": [{"idempotency_key": "private-key"}]},
    {"all_models": False, "runs": [{"gpu_uuid": "GPU-private-device"}]},
    {"all_models": False, "runs": [{"run_id": "private-run-id"}]},
    {"all_models": False, "test_job_id": "private-job-id"},
    {"all_models": False, "runs": ({"job_id": "private-job-id"},)},
])
def test_private_report_refuses_to_serialize_live_job_ids(tmp_path, report):
    with pytest.raises(ValueError, match="identifiers"):
        smoke_gpu.save_private_report(report, temp_parent=str(tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_private_report_rejects_any_repo_location(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke_gpu, "ROOT", tmp_path)
    target = tmp_path / "reports"
    target.mkdir()
    with pytest.raises(ValueError, match="inside the repository"):
        smoke_gpu.save_private_report({"all_models": False}, temp_parent=str(target))
    assert list(target.iterdir()) == []


@pytest.mark.parametrize("filename", (
    "unicode_input_boundary.json", "concurrent_model_jobs.json", "gpu_container_reuse.json",
    "deployed_gpu_readiness.json", "postgresql_gpu_jobs.json",
))
def test_private_report_supports_named_probe_outputs_with_unique_restricted_files(tmp_path, filename):
    report = {"status": "pass", "runs": []}
    first = smoke_gpu.save_private_report(report, filename=filename, temp_parent=str(tmp_path))
    second = smoke_gpu.save_private_report(report, filename=filename, temp_parent=str(tmp_path))
    assert first.name == second.name == filename and first != second
    assert first.parent.parent == tmp_path.resolve()
    assert stat.S_IMODE(first.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(first.stat().st_mode) == 0o600
    assert json.loads(first.read_text()) == {"status": "pass", "runs": []}


@pytest.mark.parametrize("filename", ("../report.json", "/tmp/report.json", "nested/report.json",
                                       "nested\\report.json", "unknown.json"))
def test_private_report_rejects_unsupported_output_names_without_writing(tmp_path, filename):
    with pytest.raises(ValueError, match="filename"):
        smoke_gpu.save_private_report({"status": "pass"}, filename=filename, temp_parent=str(tmp_path))
    assert list(tmp_path.iterdir()) == []
