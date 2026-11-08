"""Ensure bilingual API examples agree with actual schemas and run-state aggregation."""
import json
import re
from pathlib import Path
from types import SimpleNamespace

from multilingual_translation_ai_inference.repository import summarize_run_states
from multilingual_translation_ai_inference.schemas import JobSubmitted, JobView, RunView, SubmitBenchmark

ROOT = Path(__file__).resolve().parents[2]


def documentation(filename):
    return (ROOT / "docs" / filename).read_text(encoding="utf-8")


def json_examples(text):
    return [json.loads(raw) for raw in re.findall(r"§§§json\n(.*?)\n§§§".replace("§", chr(96)), text, re.S)]


def test_bilingual_job_examples_match_actual_schema_and_aggregate_status():
    en = documentation("development.md")
    vi = documentation("development.vi.md")
    examples = [json_examples(en), json_examples(vi)]
    assert examples[0] == examples[1]
    assert len(examples[0]) >= 5  # Four contract examples plus per-run telemetry sample.
    requests, benchmark, submissions, job_views = examples[0][:4]
    metrics_example = RunView.model_validate(examples[0][4])
    assert metrics_example.usage["total_tokens"] == 200
    assert metrics_example.timings["inference_ms"] == 2450.0
    assert metrics_example.resources["sampled_vram_mib"] == 31200
    assert requests["model"] == "hy_mt2_30b"
    selected = SubmitBenchmark.model_validate(benchmark)
    assert selected.models == ["hy_mt2_30b", "qwen35_35b"]
    default = SubmitBenchmark.model_validate({k: v for k, v in benchmark.items() if k != "models"})
    assert default.models == ["hy_mt2_30b", "index_35b", "gemma4_31b_it", "qwen35_35b"]
    submitted = JobSubmitted.model_validate(submissions)
    assert submitted.status_url == f"/v1/jobs/{submitted.job_id}"
    job = JobView.model_validate(job_views)
    assert job.kind == "benchmark"
    assert len(job.runs) == 4
    attempts = [
        SimpleNamespace(model_key=r.model, attempt_no=r.attempt_no, status=r.status)
        for r in job.runs
    ]
    assert summarize_run_states(attempts) == job.status == "execution_uncertain"
    assert any(r.status == "running" for r in job.runs)
    assert any(r.status == "execution_uncertain" for r in job.runs)
    assert any(r.is_mock_result is True for r in job.runs)


def test_bilingual_status_rules_match_latest_attempts_and_uncertain_handling():
    for filename in ("development.md", "development.vi.md"):
        text = documentation(filename)
        for state in (
            "queued", "dispatching", "running", "completed", "failed",
            "partial_failed", "dispatch_uncertain", "execution_uncertain",
        ):
            assert state in text
        for name in ("JobSubmitted", "JobView", "attempt_no", "runs[]",
                     "runtime_verified", "admission", "is_mock_result"):
            assert name in text
    sample = [
        SimpleNamespace(model_key="hy_mt2_30b", attempt_no=1, status="failed"),
        SimpleNamespace(model_key="hy_mt2_30b", attempt_no=2, status="completed"),
        SimpleNamespace(model_key="index_35b", attempt_no=1, status="failed"),
    ]
    assert summarize_run_states(sample) == "partial_failed"


def test_readmes_link_to_contract_without_repeating_its_full_contents(published_readmes):
    for name, dest in (
        ("README.md", "docs/development.md#"),
        ("README.vi.md", "docs/development.vi.md#"),
    ):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert dest in text
        reference = (ROOT / dest.split("#", 1)[0]).read_text(encoding="utf-8")
        assert "JobSubmitted" in reference and "JobView" in reference
        assert "job.status" in reference and "runs[]" in reference
        assert "partial_failed" not in text
