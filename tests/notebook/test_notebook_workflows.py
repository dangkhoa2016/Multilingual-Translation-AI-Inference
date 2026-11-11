"""Behavior-first notebook tests, independent of exact Markdown and example sentences."""
import ast
import contextlib
import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

NOTEBOOK = Path(__file__).resolve().parents[2] / "notebooks/translation_api_demo.ipynb"


def _notebook():
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


def _code_by_id():
    return {c["id"]: "".join(c["source"]) for c in _notebook()["cells"]
            if c["cell_type"] == "code"}


def _edited_settings(source, updates):
    tree = ast.parse(source)
    found = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            name = node.targets[0]
            if isinstance(name, ast.Name) and name.id in updates:
                node.value = ast.Constant(value=updates[name.id])
                found.add(name.id)
    assert found == set(updates)
    return compile(ast.fix_missing_locations(tree), str(NOTEBOOK), "exec")


def _offline_kernel():
    code = _code_by_id()
    state = {"__name__": "__notebook_regression__"}
    with contextlib.redirect_stdout(io.StringIO()), patch(
        "urllib.request.OpenerDirector.open", side_effect=AssertionError("Offline initialization sent HTTP")
    ):
        for source in code.values():
            exec(compile(source, str(NOTEBOOK), "exec"), state)
    return code, state


def test_performance_metrics_display_only_finite_allowlisted_numbers():
    _code, state = _offline_kernel()
    assert state["SHOW_METRICS"] is True
    job = {"kind": "benchmark", "status": "completed", "runs": [
        {"model": "hy_mt2_30b", "attempt_no": 1, "status": "failed",
         "translation_text": None, "error_code": "GPU_INFERENCE_FAILED",
         "is_mock_result": False, "usage": {"total_tokens": 999}},
        {"model": "hy_mt2_30b", "attempt_no": 2, "status": "completed",
         "translation_text": "PRIVATE_TRANSLATION", "error_code": None,
         "is_mock_result": False,
         "usage": {"prompt_tokens": 1000, "completion_tokens": 215,
                   "total_tokens": 1215, "secret": "LEAK_MARKER"},
         "timings": {"inference_ms": 1234.5678, "queue_ms": float("nan"),
                     "tokens_per_second": 30.5, "diagnostics": "LEAK_MARKER"},
         "resources": {"cpu_utilization_percent": 208.5, "sampled_vram_mib": 31000,
                       "sampled_gpu_utilization_percent": 5,
                       "gpu_uuid": "LEAK_MARKER"}},
        {"model": "index_35b", "attempt_no": 1, "status": "completed",
         "translation_text": None, "is_mock_result": True, "error_code": None,
         "usage": {"prompt_tokens": True, "total_tokens": "LEAK_MARKER"},
         "timings": {"inference_ms": float("inf")},
         "resources": {"sampled_gpu_utilization_percent": 101}},
    ]}
    summary, columns = state["_comparison_columns"](job)
    assert len(summary["runs"]) == 3 and len(columns) == 2
    assert columns[0][0]["attempt_no"] == 2
    assert columns[0][0]["metrics"]["total_tokens"] == 1215
    assert columns[0][0]["metrics"]["cpu_utilization_percent"] == 208.5
    assert "queue_ms" not in columns[0][0]["metrics"]
    assert columns[1][0]["metrics"] == {}
    html = state["_comparison_html"](job)
    assert "Input tokens" in html and "Inference (ms)" in html
    assert "VRAM sample (MiB)" in html and "1,215" in html
    assert "1,234.57" in html and "N/A" in html
    for private in ("LEAK_MARKER", "PRIVATE_TRANSLATION", ">999<"):
        assert private not in html
    state["DISPLAY_LANGUAGE"] = "vi"
    assert "Token đầu vào" in state["_comparison_html"](job)
    state["SHOW_METRICS"] = False
    hidden = state["_comparison_html"](job)
    assert "Token đầu vào" not in hidden and "Mẫu VRAM" not in hidden
    assert "PRIVATE_TRANSLATION" not in hidden


def test_metrics_in_get_only_recovery_never_post_or_reveal_translation():
    _code, state = _offline_kernel()
    job = {"kind": "translation", "status": "completed",
           "runs": [{"model": "hy_mt2_30b", "attempt_no": 1,
                     "status": "completed", "translation_text": "PRIVATE_TEXT",
                     "is_mock_result": True, "error_code": None}]}
    html = state["_comparison_html"](job)
    assert "Input tokens" in html and "N/A" in html
    assert "PRIVATE_TEXT" not in html
    job_id = "00000000-0000-0000-0000-000000009900"
    job["job_id"] = job_id
    state.update(RUN_EXISTING_JOB_POLL=True, EXISTING_JOB_ID=job_id,
                 RUN_SUBMITTED_JOB_POLL=False)
    calls = []
    def get_only(method, url, **kwargs):
        calls.append((method, url))
        return 200, job
    state["_request"] = get_only
    with contextlib.redirect_stdout(io.StringIO()) as output:
        results, failures = state["_run_get_job"]()
    assert results == [job] and failures == []
    assert calls == [("GET", "/v1/jobs/" + job_id)]
    assert "PRIVATE_TEXT" not in output.getvalue()


@pytest.mark.parametrize(
    ("language", "show_metrics"),
    [("en", True), ("vi", True), ("en", False), ("vi", False), ("en", 1)],
)
def test_json_fallback_respects_metrics_visibility_without_leaking_private_data(
    language, show_metrics,
):
    """SHOW_METRICS applies to text/JSON fallback, including non-boolean settings."""
    _code, state = _offline_kernel()
    state["DISPLAY_LANGUAGE"] = language
    state["SHOW_METRICS"] = show_metrics
    state["SHOW_TRANSLATIONS"] = False
    state["_display_comparison_html"] = lambda _html: False
    job = {"kind": "benchmark", "status": "completed", "runs": [
        {
            "model": "hy_mt2_30b", "attempt_no": 1, "status": "completed",
            "translation_text": "PRIVATE_TRANSLATION_SHOULD_NOT_LEAK",
            "is_mock_result": False, "error_code": None,
            "usage": {"prompt_tokens": 120, "completion_tokens": 80,
                      "total_tokens": 200, "provider_token": "PRIVATE_TOKEN"},
            "timings": {"inference_ms": 1250.5, "queue_ms": float("nan"),
                        "server_diagnostic": "PRIVATE_DIAGNOSTIC"},
            "resources": {"sampled_vram_mib": 31200,
                          "sampled_gpu_utilization_percent": 7,
                          "gpu_uuid": "PRIVATE_GPU_UUID"},
        },
        {
            "model": "index_35b", "attempt_no": 1, "status": "completed",
            "translation_text": "PRIVATE_SECOND_TRANSLATION",
            "is_mock_result": True, "error_code": None,
            "usage": None, "timings": None, "resources": None,
        },
    ]}
    with contextlib.redirect_stdout(io.StringIO()) as output:
        state["_show_summary"](job)
    visible = output.getvalue()
    parsed, _end = json.JSONDecoder().raw_decode(visible)
    assert len(parsed["runs"]) == 2
    assert parsed["runs"][0]["model"] == "hy_mt2_30b"
    assert parsed["runs"][1]["model"] == "index_35b"
    assert all(p not in visible for p in (
        "PRIVATE_TRANSLATION_SHOULD_NOT_LEAK", "PRIVATE_SECOND_TRANSLATION",
        "PRIVATE_TOKEN", "PRIVATE_DIAGNOSTIC", "PRIVATE_GPU_UUID",
    ))
    if show_metrics is True:
        assert parsed["runs"][0]["metrics"] == {
            "prompt_tokens": 120, "completion_tokens": 80,
            "total_tokens": 200, "inference_ms": 1250.5,
            "sampled_vram_mib": 31200, "sampled_gpu_utilization_percent": 7,
        }
        assert parsed["runs"][1]["metrics"] == {}
    else:
        assert all("metrics" not in run for run in parsed["runs"])
        assert '"prompt_tokens"' not in visible
        assert '"sampled_vram_mib"' not in visible
        # The HTML path must apply the same strict boolean rule.
        assert "Input tokens" not in state["_comparison_html"](job)
        assert "Token đầu vào" not in state["_comparison_html"](job)


@pytest.mark.parametrize("show_metrics", [True, False])
def test_rich_summary_renders_only_html_and_honors_metrics_toggle(show_metrics):
    _code, state = _offline_kernel()
    state["SHOW_METRICS"] = show_metrics
    state["SHOW_TRANSLATIONS"] = False
    rendered = []
    state["_display_comparison_html"] = lambda markup: rendered.append(markup) or True
    job = {"kind": "translation", "status": "completed", "runs": [
        {"model": "hy_mt2_30b", "attempt_no": 1, "status": "completed",
         "translation_text": "PRIVATE_TEXT", "is_mock_result": False,
         "error_code": None, "usage": {"total_tokens": 24}}
    ]}
    with contextlib.redirect_stdout(io.StringIO()) as output:
        state["_show_summary"](job)
    assert len(rendered) == 1
    assert "PRIVATE_TEXT" not in rendered[0] + output.getvalue()
    assert ('Input tokens' in rendered[0]) is show_metrics
    assert '"metrics"' not in output.getvalue()


def test_primary_cells_are_offline_before_optional_settings_and_http_helpers():
    """The short first-run path can precede the advanced implementation section."""
    code = _code_by_id()
    state = {"__name__": "__primary_offline_path__"}
    with contextlib.redirect_stdout(io.StringIO()), patch(
        "urllib.request.OpenerDirector.open", side_effect=AssertionError("Offline path sent HTTP")
    ):
        for cid in ("request-key-internals", "settings", "secret-loader", "post-translation", "get-job"):
            exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    assert state["job_results"] == [] and state["poll_failures"] == []
    assert state["submitted_single"] is None
    assert not state["RUN_SINGLE_MODEL_POST"] and not state["RUN_MULTI_MODEL_POST"]
    assert not state["RUN_SUBMITTED_JOB_POLL"] and not state["RUN_EXISTING_JOB_POLL"]


@pytest.mark.parametrize(
    ("single", "multi", "expected_posts"),
    [(False, False, []), (True, False, ["/v1/jobs/translations"]),
     (False, True, ["/v1/jobs/benchmarks"]), (True, True, None)],
)
def test_paid_post_flags_are_mutually_exclusive_before_network(single, multi, expected_posts):
    """Reject conflicting POST modes before preflight GET or billable POST."""
    code, state = _offline_kernel()
    state.update(API_BASE_URL="https://example.test", API_TOKEN="synthetic-only-token",
                 ACKNOWLEDGE_PAID_GPU=True,
                 RUN_SINGLE_MODEL_POST=single, RUN_MULTI_MODEL_POST=multi)
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append((method, path))
        if path == "/health":
            return 200, {"status": "ok", "inference_enabled": True, "phase": "gpu"}
        if path == "/v1/models":
            return 200, {"models": [
                {"key": key, "enabled": True, "runtime_verified": True}
                for key in state["MODEL_KEYS"]]}
        assert method == "POST"
        job_id = "00000000-0000-0000-0000-000000009998"
        return 202, {"job_id": job_id, "status_url": "/v1/jobs/" + job_id}

    state["_request"] = fake_request

    def run(cid):
        exec(compile(code[cid], str(NOTEBOOK), "exec"), state)

    if expected_posts is None:
        for cid in ("post-translation", "post-benchmark"):
            with pytest.raises(ValueError, match="Both paid POST flags are enabled"):
                run(cid)
        with pytest.raises(ValueError, match="Both paid POST flags are enabled"):
            state["_submit"]("/v1/jobs/translations", state["_payload"](multi_model=False),
                             idempotency_key=state["SINGLE_MODEL_IDEMPOTENCY_KEY"])
        with pytest.raises(ValueError, match="Both paid POST flags are enabled"):
            exec(_edited_settings(code["settings"], {
                "RUN_SINGLE_MODEL_POST": True, "RUN_MULTI_MODEL_POST": True,
            }), state)
        assert calls == []
        assert not state["_PAID_POST_ATTEMPTS"]
        assert state["_SUBMISSION_HISTORY"] == {"single": {}, "multi": {}}
    else:
        with contextlib.redirect_stdout(io.StringIO()):
            run("post-translation")
            run("post-benchmark")
        assert [path for method, path in calls if method == "POST"] == expected_posts
        assert [path for method, path in calls if method == "GET"] == (
            ["/health", "/v1/models"] if expected_posts else []
        )


@pytest.mark.parametrize("kind", ("single", "multi"))
@pytest.mark.parametrize("recovery", ("history", "existing_uuid"))
def test_new_accepted_request_returns_from_recovery_to_current_job(monkeypatch, kind, recovery):
    """Saving/reading an old job must not prevent GET of the next accepted POST."""
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://gateway.example.test")
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", "synthetic-only-token")
    first_id = "00000000-0000-0000-0000-000000009001"
    second_id = "00000000-0000-0000-0000-000000009002"
    monkeypatch.setenv("TRANSLATION_EXISTING_JOB_ID", first_id)
    code, state = _offline_kernel()
    post_cell = "post-translation" if kind == "single" else "post-benchmark"
    post_path = "/v1/jobs/translations" if kind == "single" else "/v1/jobs/benchmarks"
    calls = []
    accepted = iter((first_id, second_id))

    def request(method, path, **kwargs):
        calls.append((method, path))
        if path == "/health":
            return 200, {"status": "ok", "phase": "gpu", "inference_enabled": True}
        if path == "/v1/models":
            return 200, {"models": [
                {"key": key, "enabled": True, "runtime_verified": True} for key in state["MODEL_KEYS"]
            ]}
        if method == "POST" and path == post_path:
            job_id = next(accepted)
            return 202, {"job_id": job_id, "kind": "translation" if kind == "single" else "benchmark",
                         "status": "queued", "status_url": "/v1/jobs/" + job_id}
        assert method == "GET" and path in ("/v1/jobs/" + first_id, "/v1/jobs/" + second_id)
        return 200, {"job_id": path.rsplit("/", 1)[-1],
                     "kind": "translation" if kind == "single" else "benchmark", "status": "completed",
                     "source_language": "en", "target_language": "vi",
                     "runs": [{"run_id": "00000000-0000-0000-0000-000000009010",
                               "model": "hy_mt2_30b", "attempt_no": 1, "status": "completed",
                               "translation_text": "synthetic-private-output", "is_mock_result": True,
                               "error_code": None}]}

    def run(cid, updates=None):
        source = _edited_settings(code[cid], updates) if updates else compile(code[cid], str(NOTEBOOK), "exec")
        exec(source, state)

    state["_request"] = request
    basic = {"ACKNOWLEDGE_PAID_GPU": True, "RUN_SINGLE_MODEL_POST": kind == "single",
             "RUN_MULTI_MODEL_POST": kind == "multi",
             "RUN_SUBMITTED_JOB_POLL": True, "SUBMITTED_JOB_TO_POLL": kind}
    saved = {"SAVED_SUBMISSION_NUMBER": 1 if recovery == "history" else 0,
             "RUN_EXISTING_JOB_POLL": recovery == "existing_uuid"}
    with contextlib.redirect_stdout(io.StringIO()):
        run("settings", basic)
        run(post_cell)
        run("settings", {**basic, "RUN_SINGLE_MODEL_POST": False, "RUN_MULTI_MODEL_POST": False})
        run("advanced-settings", saved)
        run("get-job")
        assert [job["job_id"] for job in state["job_results"]] == [first_id]

        # Follow the next-request instructions, retaining the user's Advanced settings.
        run("settings", {**basic, "TEXT_TO_TRANSLATE": "A second synthetic sentence.",
                         "NEW_SINGLE_REQUEST_ACTION": "second" if kind == "single" else "",
                         "NEW_BENCHMARK_REQUEST_ACTION": "second" if kind == "multi" else ""})
        run(post_cell)
        before = len(calls)
        run("get-job")
    assert state["poll_failures"] == []
    assert [job["job_id"] for job in state["job_results"]] == [second_id]
    assert calls[before:] == [("GET", "/v1/jobs/" + second_id)]
    assert sum(method == "POST" for method, _ in calls) == 2


@pytest.mark.parametrize("kind", ("single", "multi"))
def test_failed_new_post_preserves_recovery_selection(kind):
    code, state = _offline_kernel()
    state.update(API_BASE_URL="https://gateway.example.test", API_TOKEN="synthetic-token",
                 ACKNOWLEDGE_PAID_GPU=True, SAVED_SUBMISSION_NUMBER=1, RUN_EXISTING_JOB_POLL=True)
    state["RUN_SINGLE_MODEL_POST" if kind == "single" else "RUN_MULTI_MODEL_POST"] = True

    def request(method, path, **kwargs):
        if path == "/health":
            return 200, {"phase": "gpu", "inference_enabled": True}
        if path == "/v1/models":
            return 200, {"models": [
                {"key": key, "enabled": True, "runtime_verified": True} for key in state["MODEL_KEYS"]
            ]}
        assert method == "POST"
        raise state["NetworkRequestError"]("Synthetic transport failure")

    state["_request"] = request
    cid = "post-translation" if kind == "single" else "post-benchmark"
    with pytest.raises(state["NetworkRequestError"]):
        exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    assert state["SAVED_SUBMISSION_NUMBER"] == 1
    assert state["RUN_EXISTING_JOB_POLL"] is True


@pytest.mark.parametrize("field", ("kind", "status", "model", "error_code", "is_mock_result"))
def test_full_get_summary_masks_unexpected_metadata(field):
    code, state = _offline_kernel()
    job_id = "00000000-0000-0000-0000-000000009101"
    private_value = "synthetic-private-metadata-value"
    job = {"job_id": job_id, "kind": "translation", "status": "completed",
           "source_language": "en", "target_language": "vi",
           "runs": [{"run_id": "00000000-0000-0000-0000-000000009102",
                     "model": "hy_mt2_30b", "attempt_no": 1, "status": "completed",
                     "translation_text": "synthetic-private-translation", "is_mock_result": False,
                     "error_code": None}]}
    (job if field in ("kind", "status") else job["runs"][0])[field] = private_value
    state.update(RUN_EXISTING_JOB_POLL=True, EXISTING_JOB_ID=job_id,
                 API_BASE_URL="https://gateway.example.test", API_TOKEN="synthetic-token")

    def request(method, path, **kwargs):
        assert (method, path) == ("GET", "/v1/jobs/" + job_id)
        return 200, job

    state["_request"] = request
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exec(compile(code["get-job"], str(NOTEBOOK), "exec"), state)
    assert state["job_results"] == [job]
    assert state["poll_failures"] == []
    assert private_value not in output.getvalue()
    assert "synthetic-private-translation" not in output.getvalue()
    assert job_id not in output.getvalue()


def test_offline_workflow_works_after_every_markdown_cell_is_rewritten(monkeypatch):
    for env in ("TRANSLATION_GATEWAY_BASE_URL", "TRANSLATION_API_BEARER_TOKEN",
                "TRANSLATION_EXISTING_JOB_ID"):
        monkeypatch.delenv(env, raising=False)
    notebook = _notebook()
    for cell in notebook["cells"]:
        if cell["cell_type"] == "markdown":
            cell["source"] = ["Completely rewritten prose that changes no behavior.\n"]
    state = {"__name__": "__offline_markdown_independent__"}
    with patch("urllib.request.OpenerDirector.open",
               side_effect=AssertionError("Default Run All must not call HTTP")):
        with contextlib.redirect_stdout(io.StringIO()):
            for cell in notebook["cells"]:
                if cell["cell_type"] == "code":
                    exec(compile("".join(cell["source"]), str(NOTEBOOK), "exec"), state)
    assert not state["RUN_SINGLE_MODEL_POST"]
    assert not state["RUN_MULTI_MODEL_POST"]
    assert not state["RUN_SUBMITTED_JOB_POLL"]
    assert not state["RUN_EXISTING_JOB_POLL"]


def test_basic_settings_action_changes_only_single_key_and_reruns_are_stable():
    cells = _code_by_id()
    state = {"__name__": "__basic_settings_behavior__"}
    with contextlib.redirect_stdout(io.StringIO()):
        for cid in ("request-key-internals", "settings", "advanced-settings"):
            exec(compile(cells[cid], str(NOTEBOOK), "exec"), state)
    first = state["SINGLE_MODEL_IDEMPOTENCY_KEY"]
    multi = state["MULTI_MODEL_IDEMPOTENCY_KEY"]
    second_settings = _edited_settings(cells["settings"], {
        "TEXT_TO_TRANSLATE": "Another synthetic input.",
        "NEW_SINGLE_REQUEST_ACTION": "second",
    })
    with contextlib.redirect_stdout(io.StringIO()):
        exec(second_settings, state)
    second = state["SINGLE_MODEL_IDEMPOTENCY_KEY"]
    assert second != first
    assert state["MULTI_MODEL_IDEMPOTENCY_KEY"] == multi
    with contextlib.redirect_stdout(io.StringIO()):
        exec(second_settings, state)
    assert state["SINGLE_MODEL_IDEMPOTENCY_KEY"] == second
    assert state["_ACTION_KEYS"]["single"]["second"] == second
    assert state["RUN_SINGLE_MODEL_POST"] is False


@pytest.mark.parametrize("selection", ("multi", "both"))
def test_sequential_benchmark_post_then_get_uses_only_accepted_multi_uuid(
    monkeypatch, selection,
):
    """Real cell order: earlier GET, POST benchmark 202, then GET benchmark 200."""
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://private-gateway.example.test")
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", "synthetic-bearer-secret")
    code = _code_by_id()
    state = {"__name__": "__benchmark_sequential_cells__"}
    def run(cid):
        exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    with contextlib.redirect_stdout(io.StringIO()):
        for cid in ("request-key-internals", "settings", "advanced-settings",
                    "secret-loader", "http-client", "validation-payload",
                    "submit-preflight", "poll-summary"):
            run(cid)

    state["ACKNOWLEDGE_PAID_GPU"] = True
    state["RUN_SINGLE_MODEL_POST"] = False
    state["RUN_MULTI_MODEL_POST"] = True
    state["RUN_SUBMITTED_JOB_POLL"] = True
    state["SUBMITTED_JOB_TO_POLL"] = selection
    state["_gpu_preflight"] = lambda _: None
    single_id = "00000000-0000-0000-0000-000000008101"
    multi_id = "00000000-0000-0000-0000-000000008102"
    if selection == "both":
        # Simulate an earlier accepted single job from the same kernel.
        fingerprint = state["_request_fingerprint"](
            "/v1/jobs/translations", state["_payload"](multi_model=False),
            state["SINGLE_MODEL_IDEMPOTENCY_KEY"]
        )
        state["submitted_single"] = state["_remember_submission"]("single", {
            "job_id": single_id, "_gateway_origin": state["API_BASE_URL"],
            "_request_fingerprint": fingerprint,
        })

    methods = []

    def fake_request(method, endpoint, **kwargs):
        methods.append((method, endpoint))
        if method == "POST":
            assert endpoint == "/v1/jobs/benchmarks"
            assert kwargs["idempotency_key"] == state["MULTI_MODEL_IDEMPOTENCY_KEY"]
            return 202, {"job_id": multi_id, "status_url": "/v1/jobs/" + multi_id}
        assert method == "GET"
        assert endpoint in ("/v1/jobs/" + single_id, "/v1/jobs/" + multi_id)
        return 200, {
            "job_id": endpoint.rsplit("/", 1)[-1],
            "kind": "benchmark" if endpoint.endswith(multi_id) else "translation",
            "status": "completed",
            "runs": [{"model": "hy_mt2_30b", "status": "completed",
                      "attempt_no": 1, "is_mock_result": True,
                      "translation_text": "synthetic-private-text"}],
        }

    state["_request"] = fake_request
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        run("get-job")  # Above POST: cannot GET the new benchmark yet.
        assert not any(endpoint == "/v1/jobs/" + multi_id
                       for method, endpoint in methods if method == "GET")
        run("post-benchmark")  # Exactly one paid POST, returning 202.
        assert state["submitted_multi"]["job_id"] == multi_id
        run("get-benchmark")  # Must GET only the new benchmark, never replay POST.
    assert methods[-2:] == [
        ("POST", "/v1/jobs/benchmarks"), ("GET", "/v1/jobs/" + multi_id)
    ]
    assert sum(method == "POST" for method, _ in methods) == 1
    assert sum(endpoint == "/v1/jobs/" + multi_id
               for _, endpoint in methods) == 1
    assert state["benchmark_job_results"][0]["job_id"] == multi_id
    assert state["benchmark_poll_failures"] == []
    if selection == "both":
        assert methods == [
            ("GET", "/v1/jobs/" + single_id),
            ("POST", "/v1/jobs/benchmarks"),
            ("GET", "/v1/jobs/" + multi_id),
        ]
    else:
        assert len(methods) == 2

    visible = output.getvalue()
    assert "synthetic-bearer-secret" not in visible
    assert "private-gateway.example.test" not in visible
    assert "synthetic-private-text" not in visible
    assert multi_id not in visible


@pytest.mark.parametrize("selection,post,read", [
    ("single", True, True),
    ("multi", False, True),
    ("multi", True, False),
])
def test_benchmark_get_skips_without_matching_submission_or_polling(monkeypatch, selection, post, read):
    """GET-only never sends a POST; a missing match or disabled GET is a no-op."""
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://gateway.example.test")
    code = _code_by_id()
    state = {"__name__": "__benchmark_get_off_by_default__"}
    with contextlib.redirect_stdout(io.StringIO()):
        for cid in ("request-key-internals", "settings", "advanced-settings",
                    "secret-loader", "http-client", "validation-payload",
                    "submit-preflight", "poll-summary", "get-job"):
            exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    state["RUN_MULTI_MODEL_POST"] = post
    state["RUN_SUBMITTED_JOB_POLL"] = read
    state["SUBMITTED_JOB_TO_POLL"] = selection
    state["_request"] = lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("No HTTP permitted when benchmark GET is disabled/misconfigured")
    )
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(code["get-benchmark"], str(NOTEBOOK), "exec"), state)
    assert state["benchmark_job_results"] == []
    assert state["benchmark_poll_failures"] == []



@pytest.mark.parametrize("selector", ("multi", "both"))
def test_benchmark_get_polls_accepted_reference_with_post_disabled(monkeypatch, selector):
    """Accept once, switch off POST in Basic settings, poll repeatedly with GET."""
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://gateway.example.test")
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", "synthetic-bearer-secret")
    code = _code_by_id()
    state = {"__name__": "__get_after_post_disabled__"}

    def run(cid):
        exec(compile(code[cid], str(NOTEBOOK), "exec"), state)

    with contextlib.redirect_stdout(io.StringIO()):
        for cid in ("request-key-internals", "settings", "advanced-settings",
                    "secret-loader", "http-client", "validation-payload",
                    "submit-preflight", "poll-summary", "get-job"):
            run(cid)
    state["RUN_MULTI_MODEL_POST"] = True
    state["RUN_SUBMITTED_JOB_POLL"] = True
    state["SUBMITTED_JOB_TO_POLL"] = selector
    multi_id = "00000000-0000-0000-0000-000000008222"
    fingerprint = state["_request_fingerprint"](
        "/v1/jobs/benchmarks", state["_payload"](multi_model=True),
        state["MULTI_MODEL_IDEMPOTENCY_KEY"],
    )
    state["submitted_multi"] = state["_remember_submission"]("multi", {
        "job_id": multi_id, "_gateway_origin": state["API_BASE_URL"],
        "_request_fingerprint": fingerprint,
    })
    original_key = state["MULTI_MODEL_IDEMPOTENCY_KEY"]
    # Exactly how a user safely switches POST off after a completed 202 response.
    with contextlib.redirect_stdout(io.StringIO()):
        exec(_edited_settings(code["settings"], {
            "RUN_MULTI_MODEL_POST": False, "RUN_SUBMITTED_JOB_POLL": True,
            "SUBMITTED_JOB_TO_POLL": selector,
        }), state)
    assert state["RUN_MULTI_MODEL_POST"] is False
    assert state["MULTI_MODEL_IDEMPOTENCY_KEY"] == original_key
    assert state["RUN_SUBMITTED_JOB_POLL"] is True

    # Optional old single reference must not be selected by this benchmark view.
    old_single = "00000000-0000-0000-0000-000000008221"
    state["submitted_single"] = {"job_id": old_single,
                                 "_gateway_origin": state["API_BASE_URL"]}
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append((method, path))
        assert method == "GET", "Polling must never issue a paid POST"
        assert path == f"/v1/jobs/{multi_id}"
        return 200, {
            "job_id": multi_id, "kind": "benchmark", "status": "completed",
            "runs": [{"model": "hy_mt2_30b", "attempt_no": 1,
                      "status": "completed", "is_mock_result": False,
                      "translation_text": "private-synthetic-output"}],
        }

    state["_request"] = fake_request
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        run("get-benchmark")
        assert state["benchmark_job_results"][0]["job_id"] == multi_id
        assert state["benchmark_poll_failures"] == []
        run("get-benchmark")
        assert state["benchmark_job_results"][0]["job_id"] == multi_id
    assert calls == [("GET", f"/v1/jobs/{multi_id}")] * 2
    displayed = output.getvalue()
    for hidden in ("synthetic-bearer-secret", "gateway.example.test",
                   "private-synthetic-output", multi_id, old_single):
        assert hidden not in displayed


@pytest.mark.parametrize(
    ("issue", "expected_reason"),
    [
        ("changed_payload", "request_mismatch"),
        ("wrong_gateway", "gateway_mismatch"),
        ("missing_multi", None),
        ("wrong_selector", None),
    ],
)
def test_benchmark_get_never_polls_unmatched_or_single_only_reference(
    monkeypatch, issue, expected_reason,
):
    """No matching benchmark => no GET, no POST, no stale single-job fallback."""
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://gateway.example.test")
    code = _code_by_id()
    state = {"__name__": "__benchmark_get_rejects_mismatched__"}

    def run(cid):
        exec(compile(code[cid], str(NOTEBOOK), "exec"), state)

    with contextlib.redirect_stdout(io.StringIO()):
        for cid in ("request-key-internals", "settings", "advanced-settings",
                    "secret-loader", "http-client", "validation-payload",
                    "submit-preflight", "poll-summary", "get-job"):
            run(cid)
    state["RUN_MULTI_MODEL_POST"] = False
    state["RUN_SUBMITTED_JOB_POLL"] = True
    state["SUBMITTED_JOB_TO_POLL"] = "single" if issue == "wrong_selector" else "both"
    state["submitted_single"] = {
        "job_id": "00000000-0000-0000-0000-000000008111",
        "_gateway_origin": state["API_BASE_URL"],
    }
    if issue != "missing_multi":
        fingerprint = state["_request_fingerprint"](
            "/v1/jobs/benchmarks", state["_payload"](multi_model=True),
            state["MULTI_MODEL_IDEMPOTENCY_KEY"],
        )
        state["submitted_multi"] = state["_remember_submission"]("multi", {
            "job_id": "00000000-0000-0000-0000-000000008222",
            "_gateway_origin": state["API_BASE_URL"],
            "_request_fingerprint": fingerprint,
        })
    if issue == "changed_payload":
        state["TEXT_TO_TRANSLATE"] = "Changed payload with no accepted benchmark"
    elif issue == "wrong_gateway":
        state["API_BASE_URL"] = "https://different-gateway.example.test"
    state["_request"] = lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("Unsafe GET or POST on a mismatched benchmark")
    )
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        run("get-benchmark")
    assert state["benchmark_job_results"] == []
    if expected_reason is None:
        assert state["benchmark_poll_failures"] == []
    else:
        assert state["benchmark_poll_failures"] == [{"reason": expected_reason}]
    for hidden in ("00000000-0000-0000-0000-000000008111",
                   "00000000-0000-0000-0000-000000008222",
                   "different-gateway.example.test"):
        assert hidden not in output.getvalue()

def test_non_boolean_paid_switches_are_rejected_before_any_request():
    code, state = _offline_kernel()
    for name in ("RUN_SINGLE_MODEL_POST", "RUN_MULTI_MODEL_POST", "ACKNOWLEDGE_PAID_GPU"):
        state[name] = "False"  # A truthy string must never count as explicit consent.
        try:
            with pytest.raises(ValueError, match="must be Python booleans"):
                state["_validate_exclusive_paid_post_flags"]()
        finally:
            state[name] = False
