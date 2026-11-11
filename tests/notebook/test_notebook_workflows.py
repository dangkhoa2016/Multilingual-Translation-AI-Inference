"""Regression tests for full API Run All and extra GPU guardrails."""
import pytest
from notebook_test_support import FakeGateway, execute, gpu_environment, initialize


def test_invalid_benchmark_payload_rejected_before_paid_translation(monkeypatch):
    gpu_environment(monkeypatch)
    state = initialize()
    state["MULTI_MODEL_KEYS"] = ["hy_mt2_30b", "hy_mt2_30b"]
    fake = FakeGateway()
    with pytest.raises(ValueError):
        execute(state, mode="gpu", fake=fake)
    assert fake.posts == []


def test_gpu_mock_result_stops_before_benchmark(monkeypatch):
    gpu_environment(monkeypatch)
    state = initialize()

    class BogusGateway(FakeGateway):
        def __call__(self, method, path, **kwargs):
            status, result = super().__call__(method, path, **kwargs)
            if method == "GET" and path.startswith("/v1/jobs/"):
                result["runs"][0]["is_mock_result"] = True
            return status, result

    fake = BogusGateway()
    with pytest.raises(RuntimeError, match="chưa xác nhận|real inference"):
        execute(state, mode="gpu", fake=fake)
    assert len(fake.posts) == 1


def test_gpu_dispatcher_flips_to_mock_before_post(monkeypatch):
    gpu_environment(monkeypatch)
    state = initialize()

    class SwitchedGateway(FakeGateway):
        def __init__(self):
            super().__init__()
            self.health_checks = 0

        def __call__(self, method, path, **kwargs):
            if method == "GET" and path == "/health":
                self.health_checks += 1
                if self.health_checks >= 3:
                    self.phase = "mock-only"
            return super().__call__(method, path, **kwargs)

    fake = SwitchedGateway()
    with pytest.raises(RuntimeError, match="CPU mock"):
        execute(state, mode="gpu", fake=fake)
    assert fake.posts == []


def test_failed_translation_stops_before_second_paid_job(monkeypatch):
    gpu_environment(monkeypatch)
    state = initialize()

    class FailedTranslation(FakeGateway):
        def __call__(self, method, path, **kwargs):
            status, result = super().__call__(method, path, **kwargs)
            if method == "GET" and path.startswith("/v1/jobs/") and result["kind"] == "translation":
                result["status"] = "failed"
                result["runs"][0]["status"] = "failed"
                result["runs"][0]["error_code"] = "model_failure"
            return status, result

    fake = FailedTranslation()
    with pytest.raises(RuntimeError, match="thất bại|failed"):
        execute(state, mode="gpu", fake=fake)
    assert [x[1] for x in fake.posts] == ["/v1/jobs/translations"]
    assert state["translation_result"]["status"] == "failed"


def test_latest_successful_retry_is_shown_not_older_failed_attempt(monkeypatch):
    gpu_environment(monkeypatch)
    state = initialize()

    class RetriedJobsFixed(FakeGateway):
        def __call__(self, method, path, **kwargs):
            status, result = super().__call__(method, path, **kwargs)
            if method == "GET" and path.startswith("/v1/jobs/"):
                runs = result["runs"]
                result["runs"] = []
                for run in runs:
                    if run.get("attempt_no") == 1:
                        result["runs"].extend([
                            {**run, "status": "failed", "attempt_no": 1,
                             "translation_text": "OLD FAILED TEXT"},
                            {**run, "status": "completed", "attempt_no": 2,
                             "translation_text": "CURRENT SUCCESS TEXT"},
                        ])
                    else:
                        result["runs"].append(run)
            return status, result

    fake = RetriedJobsFixed()
    output = execute(state, mode="gpu", fake=fake)
    assert "CURRENT SUCCESS TEXT" in output
    assert "OLD FAILED TEXT" not in output
    assert len(fake.posts) == 5


def test_failed_benchmark_does_not_claim_full_demo_success(monkeypatch):
    gpu_environment(monkeypatch)
    state = initialize()

    class FailedBenchmark(FakeGateway):
        def __call__(self, method, path, **kwargs):
            status, result = super().__call__(method, path, **kwargs)
            if method == "GET" and path.startswith("/v1/jobs/") and result["kind"] == "benchmark":
                result["status"] = "failed"
                result["runs"][0]["status"] = "failed"
            return status, result

    fake = FailedBenchmark()
    with pytest.raises(RuntimeError, match="thất bại|failed"):
        execute(state, mode="gpu", fake=fake)
    assert len(fake.posts) == 2  # Failed during warm-up; no measured job submitted.
    assert state["warmup_result"]["status"] == "failed"


def test_missing_model_result_must_not_be_accepted(monkeypatch):
    gpu_environment(monkeypatch)
    state = initialize()

    class MissingResult(FakeGateway):
        def __call__(self, method, path, **kwargs):
            status, result = super().__call__(method, path, **kwargs)
            if method == "GET" and path.startswith("/v1/jobs/") and result["kind"] == "benchmark":
                result["runs"] = result["runs"][:-1]
            return status, result

    fake = MissingResult()
    with pytest.raises(RuntimeError, match="thiếu model|missing"):
        execute(state, mode="gpu", fake=fake)


def test_invalid_run_id_rejected_without_network():
    state = initialize()
    state["DEMO_RUN_ID"] = "spaces invalid"
    with pytest.raises(ValueError, match="DEMO_RUN_ID"):
        execute(state)


def test_offline_demo_includes_all_api_steps():
    output = execute(initialize())
    for part in ("GET /health", "GET /v1/models", "WARM-UP 1",
                 "WARM-UP remaining models", "MEASURED ROUND 3/3"):
        assert part in output
