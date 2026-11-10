"""Primary comparison workflow and private, escaped notebook result rendering."""
import ast
import contextlib
import copy
import io
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

NOTEBOOK = Path(__file__).resolve().parents[2] / "notebooks/translation_api_demo.ipynb"
MODELS = ("hy_mt2_30b", "index_35b", "gemma4_31b_it", "qwen35_35b")


def kernel():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    code = {c["id"]: "".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code"}
    state = {"__name__": "__comparison_regression__"}
    with contextlib.redirect_stdout(io.StringIO()), patch(
        "urllib.request.OpenerDirector.open", side_effect=AssertionError("Offline initialization sent HTTP")
    ):
        for source in code.values():
            exec(compile(source, str(NOTEBOOK), "exec"), state)
    return code, state


def edited(source, updates):
    tree = ast.parse(source)
    found = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in updates:
                node.value = ast.parse(repr(updates[name]), mode="eval").body
                found.add(name)
    assert found == set(updates), "Comparison controls must be available in Basic settings"
    return compile(ast.fix_missing_locations(tree), str(NOTEBOOK), "exec")


def comparison_job():
    return {
        "job_id": "00000000-0000-0000-0000-000000009901", "kind": "benchmark", "status": "completed",
        "source_language": "private-source-label", "target_language": "private-target-label",
        "runs": [
            {"run_id": f"00000000-0000-0000-0000-{index + 9902:012d}",
             "model": model, "attempt_no": 1, "status": "completed", "is_mock_result": False,
             "translation_text": f"Bản dịch riêng {index + 1}", "error_code": None,
             "error_detail": "private-error-detail"}
            for index, model in enumerate(MODELS)
        ],
    }


def render(state, job, reveal=False):
    assert "_comparison_html" in state, "Notebook needs an HTML comparison renderer"
    return state["_comparison_html"](job, show_translations=reveal)


def test_four_models_and_next_request_need_only_basic_settings(monkeypatch):
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://gateway.example.test")
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", "synthetic-private-token")
    code, state = kernel()
    sent = []
    polled = []

    def request(method, path, **kwargs):
        if path == "/health":
            return 200, {"phase": "gpu", "inference_enabled": True}
        if path == "/v1/models":
            return 200, {"models": [
                {"key": key, "enabled": True, "runtime_verified": True} for key in MODELS
            ]}
        if method == "POST":
            assert path == "/v1/jobs/benchmarks"
            sent.append(copy.deepcopy(kwargs))
            job_id = f"00000000-0000-0000-0000-{len(sent):012d}"
            return 202, {"job_id": job_id, "status_url": "/v1/jobs/" + job_id,
                         "kind": "benchmark", "status": "queued"}
        polled.append(path)
        return 200, {**comparison_job(), "job_id": path.rsplit("/", 1)[-1]}

    state["_request"] = request
    basic = {"ACKNOWLEDGE_PAID_GPU": True, "RUN_SINGLE_MODEL_POST": False,
             "RUN_MULTI_MODEL_POST": True, "RUN_SUBMITTED_JOB_POLL": True,
             "SUBMITTED_JOB_TO_POLL": "multi", "MULTI_MODEL_KEYS": list(MODELS),
             "NEW_BENCHMARK_REQUEST_ACTION": "first-comparison"}
    with contextlib.redirect_stdout(io.StringIO()):
        for action in ("first-comparison", "second-comparison"):
            options = {**basic, "NEW_BENCHMARK_REQUEST_ACTION": action,
                       "TEXT_TO_TRANSLATE": "Public sample " + action}
            exec(edited(code["settings"], options), state)
            exec(compile(code["secret-loader"], str(NOTEBOOK), "exec"), state)
            exec(compile(code["post-benchmark"], str(NOTEBOOK), "exec"), state)
            exec(compile(code["post-benchmark"], str(NOTEBOOK), "exec"), state)
            # Reconfigure Basic for read-only follow-up; no Advanced cell or extra POST.
            exec(edited(code["settings"], {**options, "RUN_MULTI_MODEL_POST": False}), state)
            exec(compile(code["get-job"], str(NOTEBOOK), "exec"), state)
            assert len(state["job_results"][0]["runs"]) == 4
    assert len(sent) == 2 and len(polled) == 2
    assert all(payload["payload"]["models"] == list(MODELS) for payload in sent)
    assert sent[0]["idempotency_key"] != sent[1]["idempotency_key"]


def test_advanced_settings_preserves_basic_comparison_selection():
    code, state = kernel()
    with contextlib.redirect_stdout(io.StringIO()):
        exec(edited(code["settings"], {"MULTI_MODEL_KEYS": [MODELS[0], MODELS[3]],
                                     "RUN_MULTI_MODEL_POST": True,
                                     "NEW_BENCHMARK_REQUEST_ACTION": "selected-pair"}), state)
        key = state["MULTI_MODEL_IDEMPOTENCY_KEY"]
        exec(compile(code["advanced-settings"], str(NOTEBOOK), "exec"), state)
    assert state["MULTI_MODEL_KEYS"] == ["hy_mt2_30b", "qwen35_35b"]
    assert state["RUN_MULTI_MODEL_POST"] is True
    assert state["MULTI_MODEL_IDEMPOTENCY_KEY"] == key


def test_comparison_hides_text_and_private_metadata_by_default():
    _, state = kernel()
    job = comparison_job()
    markup = render(state, job)
    assert "<table" in markup and "SHOW_TRANSLATIONS" in markup
    for run in job["runs"]:
        assert run["translation_text"] not in markup and run["run_id"] not in markup
        assert run["model"] in markup
    assert job["job_id"] not in markup
    assert "private-source-label" not in markup and "private-target-label" not in markup
    assert "private-error-detail" not in markup


@pytest.mark.parametrize("value", ("False", 1, None, {}))
def test_nonboolean_reveal_flag_keeps_private_text_hidden(value):
    _, state = kernel()
    job = comparison_job()
    markup = state["_comparison_html"](job, show_translations=value)
    state["SHOW_TRANSLATIONS"] = value
    with contextlib.redirect_stdout(io.StringIO()) as output:
        state["_show_summary"](job)
    for run in job["runs"]:
        assert run["translation_text"] not in markup + output.getvalue()


def test_comparison_escapes_revealed_html_and_preserves_unicode_and_newlines():
    _, state = kernel()
    job = comparison_job()
    job["runs"][0]["translation_text"] = '<script>alert("private")</script>\nTiếng Việt & 日本語'
    markup = render(state, job, True)
    assert "<script>" not in markup
    assert "&lt;script&gt;" in markup and "&amp;" in markup
    assert "Tiếng Việt" in markup and "日本語" in markup and "\n" in markup


def test_comparison_shows_only_latest_translation_for_each_model():
    _, state = kernel()
    job = comparison_job()
    job["runs"][0]["translation_text"] = "STALE-TRANSLATION"
    job["runs"].append({**job["runs"][0], "attempt_no": 2, "translation_text": "LATEST-TRANSLATION"})
    markup = render(state, job, True)
    assert "LATEST-TRANSLATION" in markup and "STALE-TRANSLATION" not in markup


def test_failed_model_does_not_hide_other_translations():
    _, state = kernel()
    job = comparison_job()
    job["status"] = "partial_failed"
    job["runs"][1].update(status="failed", translation_text=None, error_code="GPU_INFERENCE_FAILED")
    markup = render(state, job, True)
    assert "GPU_INFERENCE_FAILED" in markup and "index_35b" in markup
    for index in (0, 2, 3):
        assert job["runs"][index]["translation_text"] in markup


@pytest.mark.parametrize("reveal", (False, True))
def test_rich_summary_uses_escaped_html_without_leaking_private_metadata(monkeypatch, reveal):
    _, state = kernel()
    rendered = []
    ipython = ModuleType("IPython")
    ipython.get_ipython = lambda: object()
    display = ModuleType("IPython.display")
    display.HTML = lambda value: SimpleNamespace(data=value)
    display.display = rendered.append
    monkeypatch.setitem(sys.modules, "IPython", ipython)
    monkeypatch.setitem(sys.modules, "IPython.display", display)
    state["SHOW_TRANSLATIONS"] = reveal
    job = comparison_job()
    with contextlib.redirect_stdout(io.StringIO()) as output:
        state["_show_summary"](job)
    assert len(rendered) == 1 and "<table" in rendered[0].data
    assert job["job_id"] not in rendered[0].data + output.getvalue()
    for run in job["runs"]:
        assert (run["translation_text"] in rendered[0].data) is reveal


def test_result_rendering_works_without_an_ipython_kernel(monkeypatch):
    _, state = kernel()
    ipython = ModuleType("IPython")
    ipython.get_ipython = lambda: None
    display = ModuleType("IPython.display")
    display.HTML = lambda value: value
    display.display = lambda value: pytest.fail("Plain Python must use a text fallback")
    monkeypatch.setitem(sys.modules, "IPython", ipython)
    monkeypatch.setitem(sys.modules, "IPython.display", display)
    state["SHOW_TRANSLATIONS"] = True
    with contextlib.redirect_stdout(io.StringIO()) as output:
        state["_show_summary"](comparison_job())
    for value in ("hy_mt2_30b", "qwen35_35b", "Bản dịch riêng 1", "Bản dịch riêng 4"):
        assert value in output.getvalue()
