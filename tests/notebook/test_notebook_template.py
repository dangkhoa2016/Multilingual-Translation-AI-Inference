"""Notebook behavior regression tests."""
import ast
import contextlib
import io
import json
from unittest.mock import patch

import pytest
from notebook_test_support import (
    NOTEBOOK,
    _code_by_id,
    _code_cells,
    _normalize_notebook_sources,
    _notebook,
    _run_helpers,
)


@pytest.fixture(autouse=True)
def _synthetic_gateway_for_isolated_notebook_tests(monkeypatch):
    # A stable test-only URL; all actual HTTP is mocked in the test cases.
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://gateway.example.test")



def test_notebook_source_strings_and_line_arrays_have_the_same_meaning():
    """Tools may serialize cell sources using either legal nbformat representation."""
    raw = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    expected = _notebook()
    expected_sources = {cell["id"]: cell["source"] for cell in expected["cells"]}
    for encoding in ("string", "lines"):
        candidate = json.loads(json.dumps(raw))
        for cell in candidate["cells"]:
            source = cell["source"]
            source = "".join(source) if isinstance(source, list) else source
            cell["source"] = source if encoding == "string" else source.splitlines(keepends=True)
        normalized = _normalize_notebook_sources(candidate)
        assert {cell["id"]: cell["source"] for cell in normalized["cells"]} == expected_sources
        assert _code_by_id(normalized) == _code_by_id(expected)
        for code in _code_cells(normalized):
            ast.parse(code)




def test_notebook_is_unexecuted_and_contains_the_five_documented_routes():
    notebook = _notebook()
    assert notebook["nbformat"] == 4
    assert notebook["nbformat_minor"] >= 5
    assert len(notebook["cells"]) >= 15
    assert len({cell["id"] for cell in notebook["cells"]}) == len(notebook["cells"])
    assert all(cell["cell_type"] in {"code", "markdown"} for cell in notebook["cells"])

    source = "\n".join(cell["source"] for cell in notebook["cells"])
    for path in (
        "/health",
        "/v1/models",
        "/v1/jobs/translations",
        "/v1/jobs/benchmarks",
        "/v1/jobs/{job_id}",
    ):
        assert path in source

    code_cells = _code_cells(notebook)
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            assert cell["execution_count"] is None
            assert cell["outputs"] == []
        assert not cell.get("attachments")
    for source in code_cells:
        ast.parse(source)
    code_by_id = _code_by_id(notebook)
    assert "def _require_gateway(" in code_by_id["http-client"]
    assert "def _validate_payload(" in code_by_id["validation-payload"]
    assert "def _verify_request_identity(" in code_by_id["submit-preflight"]
    assert "def _poll(" in code_by_id["poll-summary"]
    assert "sample-response" in code_by_id


def test_synthetic_api_examples_match_real_response_schemas_without_network():
    from multilingual_translation_ai_inference.schemas import JobSubmitted, JobView

    code = _code_by_id(_notebook())
    state = {"__name__": "__synthetic_response_test__"}
    with patch("urllib.request.OpenerDirector.open",
               side_effect=AssertionError("Unexpected network request")):
        _run_helpers(code, state)
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(code["sample-response"], str(NOTEBOOK), "exec"), state)

    submitted = JobSubmitted.model_validate(state["example_submission"])
    completed = JobView.model_validate(state["example_job_view"])
    assert submitted.status == "queued"  # Backend initial state, unlike pending.
    assert submitted.status_url.endswith(str(submitted.job_id))
    assert completed.job_id == submitted.job_id
    assert len(completed.runs) == 1
    assert completed.runs[0].is_mock_result is True


def test_notebook_refuses_live_posts_without_explicit_paid_gpu_ack(monkeypatch):
    """A user enabling GET alone cannot accidentally dispatch inference."""
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://gateway.example.test")
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", "safe-test-token")
    state = {"__name__": "__mock_http_notebook_test__"}
    code = _code_by_id(_notebook())
    _run_helpers(code, state)
    state["RUN_SINGLE_MODEL_POST"] = False
    state["RUN_MULTI_MODEL_POST"] = False

    def should_never_open(*args, **kwargs):
        raise AssertionError("HTTP used without paid GPU acknowledgement")

    monkeypatch.setattr(state["_OPENER"], "open", should_never_open)
    for cid, single, multi in (
        ("post-translation", True, False),
        ("post-benchmark", False, True),
    ):
        state["RUN_SINGLE_MODEL_POST"] = single
        state["RUN_MULTI_MODEL_POST"] = multi
        with pytest.raises(RuntimeError, match="ACKNOWLEDGE_PAID_GPU"):
            exec(compile(code[cid], str(NOTEBOOK), "exec"), state)


def test_notebook_sanitizes_http_errors(monkeypatch):
    from urllib.error import HTTPError

    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://gateway.example.test")
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", "hidden-test-token")
    state = {"__name__": "__mock_http_notebook_test__"}
    _run_helpers(_code_by_id(_notebook()), state)

    def fake_error(request, timeout):
        raise HTTPError(request.full_url, 401, "private-api-error hidden-test-token", {}, None)

    monkeypatch.setattr(state["_OPENER"], "open", fake_error)
    with pytest.raises(state["APIRequestError"], match="HTTP 401") as failure:
        state["_request"]("GET", "/v1/models", authenticated=True)
    assert "hidden-test-token" not in str(failure.value)
    assert "gateway.example.test" not in str(failure.value)

def test_catalog_get_does_not_call_public_health(monkeypatch):
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://gateway.example.test")
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", "private-test-token")
    code = _code_by_id(_notebook())
    state = {"__name__": "__catalog_only_test__"}
    _run_helpers(code, state)
    state["RUN_MODEL_CATALOG_GET"] = True
    requests = []

    def fake_request(method, path, **kwargs):
        requests.append((method, path, kwargs))
        return 200, {"models": []}

    state["_request"] = fake_request
    with contextlib.redirect_stdout(io.StringIO()):
        for cid in ("get-health", "get-models", "get-job"):
            exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    assert [(method, path) for method, path, _ in requests] == [("GET", "/v1/models")]
    assert requests[0][2]["authenticated"] is True


@pytest.mark.parametrize("selected", ["single", "multi"])
def test_saved_uuid_can_be_revealed_offline_without_any_http_or_post(selected, capsys):
    """Recovery must not require a repeated paid GPU request or a working gateway."""
    code = _code_by_id(_notebook())
    state = {"__name__": "__offline_saved_uuid__"}
    _run_helpers(code, state)
    saved = "00000000-0000-0000-0000-000000008881"
    path, key_name, multi = (
        ("/v1/jobs/translations", "SINGLE_MODEL_IDEMPOTENCY_KEY", False)
        if selected == "single" else
        ("/v1/jobs/benchmarks", "MULTI_MODEL_IDEMPOTENCY_KEY", True)
    )
    state["submitted_" + selected] = {
        "job_id": saved, "_gateway_origin": state["API_BASE_URL"],
        "_request_fingerprint": state["_request_fingerprint"](
            path, state["_payload"](multi_model=multi), state[key_name],
        ),
    }
    state["SUBMITTED_JOB_TO_POLL"] = selected
    state["SHOW_JOB_IDS"] = True
    state["_request"] = lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("A saved UUID reveal must never send HTTP")
    )
    state["_gpu_preflight"] = lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("A saved UUID reveal must not preflight GPU")
    )
    assert state["RUN_SINGLE_MODEL_POST"] is False
    assert state["RUN_MULTI_MODEL_POST"] is False
    assert state["RUN_SUBMITTED_JOB_POLL"] is False
    exec(compile(code["show-saved-job-id"], str(NOTEBOOK), "exec"), state)
    out = capsys.readouterr().out
    assert saved in out and "PRIVATE JOB UUID" in out


def test_label_histories_are_independent_and_default_stays_offline():
    code = _code_by_id(_notebook())
    state = {"__name__": "__f01_two_kinds__"}
    settings = code["settings"]
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(settings, str(NOTEBOOK), "exec"), state)

    def run(single, multi):
        modified = settings.replace(
            'NEW_SINGLE_REQUEST_ACTION = ""',
            f'NEW_SINGLE_REQUEST_ACTION = "{single}"'
        ).replace(
            'NEW_BENCHMARK_REQUEST_ACTION = ""',
            f'NEW_BENCHMARK_REQUEST_ACTION = "{multi}"'
        )
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(modified, str(NOTEBOOK), "exec"), state)
        return (state["SINGLE_MODEL_IDEMPOTENCY_KEY"],
                state["MULTI_MODEL_IDEMPOTENCY_KEY"])

    original_single, original_multi = run("2", "2")
    changed_single, original_multi_again = run("3", "2")
    assert changed_single != original_single
    assert original_multi_again == original_multi
    returned_single, changed_multi = run("2", "3")
    assert returned_single == original_single
    assert changed_multi != original_multi
    assert run("3", "2") == (changed_single, original_multi)
    assert all(state[k] is False for k in (
        "ACKNOWLEDGE_PAID_GPU", "RUN_SINGLE_MODEL_POST",
        "RUN_MULTI_MODEL_POST", "RUN_SUBMITTED_JOB_POLL"
    ))


def test_synthetic_completed_job_has_short_privacy_safe_summary():
    codes = _code_by_id(_notebook())
    state = {"__name__": "__synthetic_summary__"}
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        _run_helpers(codes, state)
        exec(compile(codes["sample-response"], str(NOTEBOOK), "exec"), state)
    output = stdout.getvalue()
    assert "SYNTHETIC SUMMARY ONLY" in output
    assert "translation_length:" in output
    assert "status: completed" in output
    assert "SHOW_TRANSLATIONS=True" in output
    assert "never submit a new post" in output.lower()
    assert state["RUN_SINGLE_MODEL_POST"] is False
    assert state["RUN_MULTI_MODEL_POST"] is False




def test_notebook_real_cell_boundaries_for_first_next_and_saved_job(monkeypatch):
    """Execute separate Jupyter cells in documented order; do not fuse Settings."""
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://gateway.example.test")
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", "synthetic-secret-not-printed")
    monkeypatch.delenv("TRANSLATION_EXISTING_JOB_ID", raising=False)
    code = {cell["id"]: cell["source"] for cell in _notebook()["cells"]
            if cell["cell_type"] == "code"}
    state = {"__name__": "__actual_cell_workflow__"}

    def run(cid, source=None):
        exec(compile(source if source is not None else code[cid], str(NOTEBOOK), "exec"), state)

    first_basic = (code["settings"]
                   .replace("ACKNOWLEDGE_PAID_GPU = False", "ACKNOWLEDGE_PAID_GPU = True")
                   .replace("RUN_SINGLE_MODEL_POST = False", "RUN_SINGLE_MODEL_POST = True")
                   .replace("RUN_SUBMITTED_JOB_POLL = False", "RUN_SUBMITTED_JOB_POLL = True"))
    calls = []
    def synthetic_gateway(method, path, **kwargs):
        calls.append((method, path))
        if path == "/health":
            return 200, {"phase": "gpu", "inference_enabled": True}
        if path == "/v1/models":
            return 200, {"models": [
                {"key": name, "enabled": True, "runtime_verified": True}
                for name in state["MODEL_KEYS"]
            ]}
        if method == "POST":
            job_id = f"00000000-0000-0000-0000-{sum(c[0] == 'POST' for c in calls):012d}"
            return 202, {"job_id": job_id, "status_url": "/v1/jobs/" + job_id}
        if method == "GET" and path.startswith("/v1/jobs/"):
            return 200, {"job_id": path.rsplit("/", 1)[-1],
                         "kind": "translation", "status": "completed",
                         "runs": [{"model": state["MODEL_KEY"], "status": "completed",
                                   "attempt_no": 1, "is_mock_result": True,
                                   "translation_text": "[MOCK ONLY]"}]}
        raise AssertionError("Unexpected synthetic API operation")

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        run("request-key-internals")
        run("settings", first_basic)
        run("advanced-settings")
        for cid in ("secret-loader", "http-client", "validation-payload",
                    "submit-preflight", "poll-summary"):
            run(cid)
        state["_request"] = synthetic_gateway
        run("post-translation")
        run("get-job")
        first_id = state["submitted_single"]["job_id"]
        first_key = state["SINGLE_MODEL_IDEMPOTENCY_KEY"]
        assert state["job_results"][0]["job_id"] == first_id

        # New request: separately change the Basic text and Advanced label.
        next_basic = first_basic.replace(
            'TEXT_TO_TRANSLATE = "The little fox crossed the wooden bridge at sunrise."',
            'TEXT_TO_TRANSLATE = "A second synthetic sentence for the next job."')
        next_basic = next_basic.replace(
            'NEW_SINGLE_REQUEST_ACTION = ""',
            'NEW_SINGLE_REQUEST_ACTION = "second-sentence"')
        run("settings", next_basic)  # Basic only; no Advanced rerun.
        assert state["SINGLE_MODEL_IDEMPOTENCY_KEY"] != first_key
        run("post-translation")
        run("get-job")
        second_id = state["submitted_single"]["job_id"]
        assert first_id != second_id
        assert state["job_results"][0]["job_id"] == second_id

        # Saved old UUID: configure GET only, with both paid POST flags off.
        saved_basic = next_basic.replace("RUN_SINGLE_MODEL_POST = True",
                                         "RUN_SINGLE_MODEL_POST = False").replace(
                                         "RUN_SUBMITTED_JOB_POLL = True",
                                         "RUN_SUBMITTED_JOB_POLL = False")
        saved_advanced = code["advanced-settings"].replace(
            "RUN_EXISTING_JOB_POLL = False", "RUN_EXISTING_JOB_POLL = True")
        monkeypatch.setenv("TRANSLATION_EXISTING_JOB_ID", first_id)
        before_posts = sum(c[0] == "POST" for c in calls)
        run("settings", saved_basic)
        run("advanced-settings", saved_advanced)
        run("secret-loader")
        run("get-job")
        assert state["job_results"][0]["job_id"] == first_id
        assert sum(c[0] == "POST" for c in calls) == before_posts
        assert state["RUN_SINGLE_MODEL_POST"] is False
        assert state["RUN_MULTI_MODEL_POST"] is False
    assert "synthetic-secret-not-printed" not in out.getvalue()
    assert first_id not in out.getvalue() and second_id not in out.getvalue()


def test_submission_history_never_reveals_old_uuid_by_default(monkeypatch):
    """An accepted UUID is stored but not printed or polled without opt-in."""
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://gateway.example.test")
    state = {"__name__": "__private_submission_history_test__"}
    code = _code_by_id(_notebook())
    _run_helpers(code, state)
    state["RUN_SINGLE_MODEL_POST"] = True
    state["_gpu_preflight"] = lambda models: None
    job_id = "00000000-0000-0000-0000-000000007871"
    state["_request"] = lambda method, path, **kw: (
        202, {"job_id": job_id, "status_url": "/v1/jobs/" + job_id}
    )
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exec(compile(code["post-translation"], str(NOTEBOOK), "exec"), state)
        assert state["_SUBMISSION_HISTORY"]["single"]
        exec(compile(code["show-saved-job-id"], str(NOTEBOOK), "exec"), state)
    assert job_id not in output.getvalue()
    assert "PRIVATE JOB UUID" not in output.getvalue()


