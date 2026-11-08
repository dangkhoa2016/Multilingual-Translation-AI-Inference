"""Shared offline test harness for the public two-mode API notebook.

No external requests or GPU allocations are ever made by these tests.
"""
import contextlib
import io
import json
import uuid
from pathlib import Path

NOTEBOOK_PATH = Path(__file__).resolve().parents[2] / "notebooks" / "translation_api_demo.ipynb"
EXPECTED_MODELS = ("hy_mt2_30b", "index_35b", "gemma4_31b_it", "qwen35_35b")


def notebook():
    return json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))


def source(cell_id):
    return "".join(next(cell["source"] for cell in notebook()["cells"] if cell["id"] == cell_id))


def initialize():
    namespace = {"__name__": "__notebook_test__"}
    for cell_id in ("config", "helpers"):
        exec(compile(source(cell_id), f"<{cell_id}>", "exec"), namespace)
    # Legacy tests continue to cover the public four-model parallel API path.
    # Dedicated tests below select the default "per_model" sequence explicitly.
    namespace["BENCHMARK_SEQUENCE"] = "parallel"
    # Unit tests that use immediate synthetic responses do not wait 6.25 s
    # between posts; explicit pacing/integration tests restore the real helper.
    namespace["_pace_gpu_submissions_real"] = namespace["_pace_gpu_submissions"]
    namespace["_pace_gpu_submissions"] = lambda: None
    return namespace


def execute(namespace, *, mode="offline", fake=None):
    namespace["DEMO_MODE"] = mode
    if fake is not None:
        namespace["_LIVE_REQUEST"] = fake
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exec(compile(source("full-demo"), "<full-demo>", "exec"), namespace)
    return buffer.getvalue()


class FakeGateway:
    def __init__(self, *, phase="gpu", enabled=None):
        self.phase = phase
        self.enabled = set(EXPECTED_MODELS if enabled is None else enabled)
        self.calls = []
        self.jobs = {}
        self.fail_next_post = False

    def __call__(self, method, path, *, payload=None, authenticated=False, idempotency_key=None):
        self.calls.append((method, path, idempotency_key))
        if method == "GET" and path == "/health":
            return 200, {"status": "ok", "phase": self.phase,
                         "inference_enabled": self.phase == "gpu"}
        if method == "GET" and path == "/v1/models":
            return 200, {"models": [{"key": key, "enabled": key in self.enabled,
                                     "runtime_verified": key in self.enabled}
                                    for key in EXPECTED_MODELS]}
        if method == "POST" and path in ("/v1/jobs/translations", "/v1/jobs/benchmarks"):
            assert authenticated
            assert idempotency_key and idempotency_key.startswith("full-demo-")
            if self.fail_next_post:
                self.fail_next_post = False
                raise RuntimeError("Ambiguous response; POST outcome unknown")
            job_id = str(uuid.uuid5(uuid.NAMESPACE_URL, idempotency_key))
            models = payload.get("models", [payload.get("model")])
            self.jobs[job_id] = {"job_id": job_id,
                                 "kind": "benchmark" if path.endswith("benchmarks") else "translation",
                                 "status": "completed",
                                 "runs": [
                                     {"model": model, "attempt_no": 1, "status": "completed",
                                      "is_mock_result": False,
                                      "translation_text": "[LOCAL TEST STUB] " + model,
                                      "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
                                      "timings": {"inference_ms": 150.0}}
                                     for model in models]}
            return 202, {"job_id": job_id, "status_url": "/v1/jobs/" + job_id}
        if method == "GET" and path.startswith("/v1/jobs/"):
            return 200, self.jobs[path.rsplit("/", 1)[-1]]
        raise RuntimeError("Unexpected fake API call")

    @property
    def posts(self):
        return [call for call in self.calls if call[0] == "POST"]


def gpu_environment(monkeypatch):
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://translation.example.test")
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", "synthetic-private-test-token-123456")
