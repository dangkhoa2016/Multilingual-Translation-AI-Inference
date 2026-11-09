"""Notebook behavior regression tests."""
import contextlib
import io
import json
from unittest.mock import patch

import pytest
from notebook_test_support import (
    NOTEBOOK,
    _bind_accepted_test_references,
    _code_by_id,
    _code_cells,
    _notebook,
    _run_helpers,
)


@pytest.fixture(autouse=True)
def _synthetic_gateway_for_isolated_notebook_tests(monkeypatch):
    # A stable test-only URL; all actual HTTP is mocked in the test cases.
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://gateway.example.test")



def test_run_all_is_offline_and_never_prints_private_credentials(monkeypatch):
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://private-gateway.example.test")
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", "private-example-test-token")
    monkeypatch.setenv("TRANSLATION_EXISTING_JOB_ID", "00000000-0000-0000-0000-000000000000")

    notebook = _notebook()
    globals_dict = {"__name__": "__offline_notebook_test__"}
    stdout = io.StringIO()
    with (
        patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("Network request")),
        contextlib.redirect_stdout(stdout),
    ):
        for source in _code_cells(notebook):
            exec(compile(source, str(NOTEBOOK), "exec"), globals_dict)

    for flag in (
        "RUN_HEALTH_GET",
        "RUN_MODEL_CATALOG_GET",
        "RUN_SINGLE_MODEL_POST",
        "RUN_MULTI_MODEL_POST",
        "RUN_EXISTING_JOB_POLL",
        "RUN_SUBMITTED_JOB_POLL",
        "ACKNOWLEDGE_PAID_GPU",
        "SHOW_TRANSLATIONS",
        "SHOW_JOB_IDS",
        "LOAD_EXISTING_JOB_ID_FROM_SECRETS",
        "LOAD_PERSISTED_IDEMPOTENCY_KEYS",
    ):
        assert globals_dict[flag] is False
    assert globals_dict["submitted_single"] is None
    assert globals_dict["submitted_multi"] is None
    assert globals_dict["job_results"] == []
    assert globals_dict["single_payload"]["model"] == "hy_mt2_30b"
    assert len(globals_dict["multi_payload"]["models"]) == 2
    assert globals_dict["example_submission"]["status_url"] == (
        "/v1/jobs/" + globals_dict["example_job_id"]
    )
    assert globals_dict["example_job_view"]["runs"][0]["is_mock_result"] is True
    assert "SYNTHETIC EXAMPLE ONLY" in stdout.getvalue()
    assert "Offline validation PASS" in stdout.getvalue()
    assert "private-example-test-token" not in stdout.getvalue()
    assert "private-gateway.example.test" not in stdout.getvalue()


def test_gpu_submission_requires_explicit_opt_in_and_input_is_bounded():
    notebook = _notebook()
    state = {"__name__": "__offline_test__"}
    _run_helpers(_code_by_id(notebook), state)

    with pytest.raises(RuntimeError, match="ACKNOWLEDGE_PAID_GPU"):
        state["_gpu_preflight"](["hy_mt2_30b"])

    sample = state["_payload"](multi_model=False)
    assert sample["source_language"] == "en"
    assert sample["target_language"] == "vi"

    invalid = {**sample, "text": "あ" * 1001}
    with pytest.raises(ValueError, match="1–1,000"):
        state["_validate_payload"](invalid, multi_model=False)

    duplicate = {**sample, "models": ["hy_mt2_30b", "hy_mt2_30b"]}
    duplicate.pop("model")
    with pytest.raises(ValueError, match="duplicate"):
        state["_validate_payload"](duplicate, multi_model=True)


def test_offline_run_all_with_two_models_and_no_network():
    notebook = _notebook()
    state = {"__name__": "__two_model_run_all_test__"}
    output = io.StringIO()
    with (
        patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("No network")),
        contextlib.redirect_stdout(output),
    ):
        for cell in notebook["cells"]:
            if cell["cell_type"] != "code":
                continue
            source = cell["source"]
            if cell["id"] == "settings":
                assert "MULTI_MODEL_KEYS = list(MODEL_KEYS)[:2]" in source
            exec(compile(source, str(NOTEBOOK), "exec"), state)
    assert state["multi_payload"]["models"] == list(state["MODEL_KEYS"])[:2]
    assert state["submitted_single"] is None and state["submitted_multi"] is None
    assert "'multi_model_count': 2" in output.getvalue()


def test_poll_uses_updated_runtime_timeout_after_settings_change():
    code = _code_by_id(_notebook())
    state = {"__name__": "__runtime_timeout_test__"}
    _run_helpers(code, state)
    assert state["_poll"].__kwdefaults__["timeout_seconds"] is None
    state["POLL_TIMEOUT_SECONDS"] = 7
    state["_request"] = lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("Timed-out poll must not call the API")
    )
    with patch.object(state["time"], "monotonic", side_effect=[100, 108]):
        with pytest.raises(TimeoutError, match="Polling timed out"):
            state["_poll"]("00000000-0000-0000-0000-000000000001")
    with patch.object(state["time"], "monotonic", side_effect=[100, 110]):
        with pytest.raises(TimeoutError, match="Polling timed out"):
            state["_poll"]("00000000-0000-0000-0000-000000000001", timeout_seconds=5)
    with pytest.raises(ValueError, match="Polling timeout must be positive"):
        state["_poll"]("00000000-0000-0000-0000-000000000001", timeout_seconds=0)


def test_optional_reset_is_explicit_and_noop_by_default():
    code = _code_by_id(_notebook())
    state = {"__name__": "__local_reset_test__"}
    _run_helpers(code, state)
    state["submitted_single"] = {"job_id": "mock-single", "_gateway_origin": state["API_BASE_URL"]}
    state["submitted_multi"] = {"job_id": "mock-multi", "_gateway_origin": state["API_BASE_URL"]}
    exec(compile(code["reset-submissions"], str(NOTEBOOK), "exec"), state)
    assert state["submitted_single"] and state["submitted_multi"]
    enabled = code["reset-submissions"].replace(
        "RESET_LOCAL_SUBMISSIONS = False", "RESET_LOCAL_SUBMISSIONS = True"
    )
    assert enabled != code["reset-submissions"]
    state["_SUBMISSION_HISTORY"]["single"]["synthetic-fingerprint"] = {
        "job_id": "00000000-0000-0000-0000-000000000001",
    }
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(enabled, str(NOTEBOOK), "exec"), state)
    assert state["submitted_single"] is None and state["submitted_multi"] is None
    assert state["_SUBMISSION_HISTORY"] == {"single": {}, "multi": {}}


@pytest.mark.parametrize("reused_kernel", [False, True])
def test_run_all_with_all_live_flags_false_makes_zero_http_calls(
    monkeypatch, reused_kernel
):
    """A cached submission must not trigger hidden GETs during offline Run All."""
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://private.example.test")
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", "hidden-private-token")
    state = {"__name__": "__reused_kernel_offline__"}
    old_single = {"job_id": "00000000-0000-0000-0000-000000001111"}
    old_multi = {"job_id": "00000000-0000-0000-0000-000000002222"}
    if reused_kernel:
        state["submitted_single"] = old_single
        state["submitted_multi"] = old_multi
        state["RUN_SUBMITTED_JOB_POLL"] = True  # a previous live run
        state["RUN_EXISTING_JOB_POLL"] = True

    count = []
    def no_network(*args, **kwargs):
        count.append(True)
        raise AssertionError("Offline Run All called the network")

    output = io.StringIO()
    with (
        patch("urllib.request.OpenerDirector.open", side_effect=no_network),
        contextlib.redirect_stdout(output),
    ):
        for code in _code_cells(_notebook()):
            exec(compile(code, str(NOTEBOOK), "exec"), state)

    assert count == []
    assert not any(state[flag] for flag in (
        "RUN_HEALTH_GET", "RUN_MODEL_CATALOG_GET", "RUN_SINGLE_MODEL_POST",
        "RUN_MULTI_MODEL_POST", "RUN_EXISTING_JOB_POLL",
        "RUN_SUBMITTED_JOB_POLL",
    ))
    assert state["job_results"] == []
    assert state["poll_failures"] == []
    if reused_kernel:
        assert state["submitted_single"] is old_single
        assert state["submitted_multi"] is old_multi
    assert "hidden-private-token" not in output.getvalue()
    assert "private.example.test" not in output.getvalue()


def test_real_poll_helper_uses_only_authenticated_get_and_retries_next_job():
    """Exercise real HTTP polling code with an offline request fake."""
    code = _code_by_id(_notebook())
    state = {"__name__": "__real_poll_helper_offline_test__"}
    _run_helpers(code, state)
    first = "00000000-0000-0000-0000-000000005555"
    second = "00000000-0000-0000-0000-000000006666"
    state["submitted_single"] = {"job_id": first, "_gateway_origin": state["API_BASE_URL"]}
    state["submitted_multi"] = {"job_id": second, "_gateway_origin": state["API_BASE_URL"]}
    state["RUN_SUBMITTED_JOB_POLL"] = True
    state["SUBMITTED_JOB_TO_POLL"] = "both"
    requests = []

    def fake_request(method, path, **kwargs):
        requests.append((method, path, kwargs.get("authenticated")))
        assert method == "GET" and kwargs.get("authenticated") is True
        if path.endswith(first):
            raise state["APIRequestError"](401)
        return 200, {
            "job_id": second, "status": "completed",
            "runs": [{"model": "hy_mt2_30b", "status": "completed",
                      "translation_text": "HIDDEN VALUE", "is_mock_result": False}]
        }

    state["_request"] = fake_request
    output = io.StringIO()
    _bind_accepted_test_references(state)
    with contextlib.redirect_stdout(output):
        exec(compile(code["get-job"], str(NOTEBOOK), "exec"), state)
    assert len(requests) == 2
    assert requests[0][1].endswith(first)
    assert requests[1][1].endswith(second)
    assert state["job_results"][0]["job_id"] == second
    assert state["poll_failures"] == [{"reason": "http", "status_code": 401}]
    assert "GET job HTTP 401" in output.getvalue()
    assert "HIDDEN VALUE" not in output.getvalue()


def test_polling_reuses_cached_jobs_only_with_explicit_flag():
    code = _code_by_id(_notebook())
    state = {"__name__": "__explicit_poll_gate_test__"}
    _run_helpers(code, state)
    state["submitted_single"] = {"job_id": "00000000-0000-0000-0000-000000007777", "_gateway_origin": state["API_BASE_URL"]}
    calls = []
    state["_poll"] = lambda jid: calls.append(jid) or {"job_id": jid, "runs": []}
    state["_show_summary"] = lambda job: None
    _bind_accepted_test_references(state)
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(code["get-job"], str(NOTEBOOK), "exec"), state)
    assert calls == [] and state["submitted_single"]
    state["RUN_SUBMITTED_JOB_POLL"] = True
    state["SUBMITTED_JOB_TO_POLL"] = "both"
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(code["get-job"], str(NOTEBOOK), "exec"), state)
    assert calls == ["00000000-0000-0000-0000-000000007777"]


def test_retry_summary_marks_latest_attempt_without_exposing_text(capsys):
    code = _code_by_id(_notebook())
    state = {"__name__": "__retry_summary_test__"}
    _run_helpers(code, state)
    job = {
        "kind": "translation", "status": "completed",
        "runs": [
            {"model": "hy_mt2_30b", "attempt_no": 1, "status": "failed",
             "translation_text": None, "error_code": "ERROR", "is_mock_result": False},
            {"model": "hy_mt2_30b", "attempt_no": 2, "status": "completed",
             "translation_text": "PRIVATE TRANSLATION", "is_mock_result": False},
        ],
    }
    state["_show_summary"](job)
    printed = capsys.readouterr().out
    summary, _ = json.JSONDecoder().raw_decode(printed[printed.index("{"):])
    assert summary["status"] == "completed"
    assert [run["attempt_no"] for run in summary["runs"]] == [1, 2]
    assert [run["is_latest_attempt"] for run in summary["runs"]] == [False, True]
    assert "latest attempt" in printed
    assert "PRIVATE TRANSLATION" not in printed


def test_invalid_submitted_job_selection_cannot_issue_get():
    code = _code_by_id(_notebook())
    state = {"__name__": "__invalid_poll_selection_test__"}
    _run_helpers(code, state)
    state["RUN_SUBMITTED_JOB_POLL"] = True
    state["SUBMITTED_JOB_TO_POLL"] = "everything"
    state["_request"] = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("Invalid selection cannot issue HTTP")
    )
    with pytest.raises(ValueError, match="single, multi or both"):
        exec(compile(code["get-job"], str(NOTEBOOK), "exec"), state)


def test_unbound_legacy_reference_requires_explicit_uuid_recovery():
    code = _code_by_id(_notebook())
    state = {"__name__": "__legacy_unbound_guard_test__"}
    _run_helpers(code, state)
    state["submitted_single"] = {
        "job_id": "00000000-0000-0000-0000-000000009999",
        "_gateway_origin": state["API_BASE_URL"],
    }
    jobs, errors = state["_select_submitted_jobs"]()
    assert jobs == []
    assert errors == [{"reason": "request_mismatch"}]


def test_first_run_guidance_is_short_and_explicitly_keeps_helpers_unchanged():
    cells = {cell["id"]: cell["source"] for cell in _notebook()["cells"]}
    for token in ("Basic settings", "Secrets", "helper", "POST", "GET"):
        assert token in cells["intro"]
    assert "Do not edit or rerun them for normal API usage" in cells["helpers-guide"]
    assert "Không sửa hoặc chạy lại khi dùng API thông thường" in cells["helpers-guide"]
    advanced_help = cells["advanced-settings-guide"]
    assert "NEW_SINGLE_REQUEST_ACTION" in cells["settings-guide"]
    assert "NEW_BENCHMARK_REQUEST_ACTION" in advanced_help
    assert "uncertain" in advanced_help
    assert "không đổi key" in advanced_help.lower()
    assert "POST" in cells["settings-guide"]


def test_get_only_recovery_needs_no_persisted_key(monkeypatch):
    for name in ("TRANSLATION_SINGLE_IDEMPOTENCY_KEY", "TRANSLATION_MULTI_IDEMPOTENCY_KEY"):
        monkeypatch.delenv(name, raising=False)
    code = _code_by_id(_notebook())
    state = {"__name__": "__get_only_recovery_test__"}
    exec(compile(code["settings"], str(NOTEBOOK), "exec"), state)
    state["LOAD_PERSISTED_IDEMPOTENCY_KEYS"] = True
    state["RUN_EXISTING_JOB_POLL"] = True
    exec(compile(code["secret-loader"], str(NOTEBOOK), "exec"), state)
    assert state["_LOADED_PERSISTED_KEYS"] == set()




def test_notebook_client_output_language_selection_is_explicit_and_private(capsys):
    """English/Vietnamese messages never concatenate both languages at runtime."""
    notebook = _notebook()
    cells = {c["id"]: c["source"] for c in notebook["cells"] if c["cell_type"] == "code"}
    state = {"__name__": "__notebook_locale__"}
    for name in ("request-key-internals", "settings", "advanced-settings",
                 "get-job", "poll-summary"):
        exec(compile(cells[name], str(NOTEBOOK), "exec"), state)
    english = capsys.readouterr().out
    assert "SKIPPED GET" in english
    assert " / VI:" not in english

    state["DISPLAY_LANGUAGE"] = "vi"
    exec(compile(cells["get-job"], str(NOTEBOOK), "exec"), state)
    vietnamese = capsys.readouterr().out
    assert "BỎ QUA GET" in vietnamese
    assert "SKIPPED GET" not in vietnamese
    assert " / VI:" not in vietnamese

    with pytest.raises(ValueError, match="Cấu trúc phản hồi job không hợp lệ"):
        state["_validated_runs"]({})
    state["DISPLAY_LANGUAGE"] = "en"
    with pytest.raises(ValueError, match="Invalid job response structure"):
        state["_validated_runs"]({})


def test_recovery_guides_are_short_bilingual_topics():
    notebook = _notebook()
    by_id = {cell["id"]: cell for cell in notebook["cells"]}
    topics = ("advanced-usage", "request-identity-guide",
              "get-only-recovery-guide", "secrets-setup-guide")
    ids = [c["id"] for c in notebook["cells"]]
    assert len(notebook["cells"]) == 43
    assert ids.index("advanced-usage") + 1 == ids.index("request-identity-guide")
    for topic in topics:
        cell = by_id[topic]
        assert cell["cell_type"] == "markdown"
        assert "**English**" in cell["source"]
        assert "**Tiếng Việt**" in cell["source"]
        assert len(cell["source"]) < 6500
    assert "#141-request-identity-and-persistent-keys--định-danh-và-lưu-khóa-yêu-cầu" in by_id["translation-md"]["source"]
    assert "### 14.1 Request identity and persistent keys /" in by_id["request-identity-guide"]["source"]
    assert "### 14.3 Detailed Secrets setup /" in by_id["secrets-setup-guide"]["source"]


@pytest.mark.parametrize("language, wanted, other", [
    ("en", "Translation comparison", "So sánh bản dịch"),
    ("vi", "So sánh bản dịch", "Translation comparison"),
])
def test_comparison_caption_uses_only_the_selected_display_language(language, wanted, other):
    code = _code_by_id(_notebook())
    state = {"__name__": "__localized_comparison_caption__"}
    _run_helpers(code, state)
    state["DISPLAY_LANGUAGE"] = language
    job = {"kind": "translation", "status": "completed", "runs": [
        {"model": "hy_mt2_30b", "status": "completed", "attempt_no": 1,
         "translation_text": "Private text", "is_mock_result": False, "error_code": None},
    ]}
    markup = state["_comparison_html"](job)
    assert wanted in markup
    assert other not in markup
    assert "Private text" not in markup
