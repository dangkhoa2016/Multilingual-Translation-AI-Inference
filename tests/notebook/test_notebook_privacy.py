"""Notebook behavior regression tests."""
import contextlib
import io
import json
import types
from unittest.mock import patch

import pytest
from notebook_test_support import (
    NOTEBOOK,
    _advanced_guide,
    _bind_accepted_test_references,
    _code_by_id,
    _notebook,
    _run_helpers,
)


@pytest.fixture(autouse=True)
def _synthetic_gateway_for_isolated_notebook_tests(monkeypatch):
    # A stable test-only URL; all actual HTTP is mocked in the test cases.
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://gateway.example.test")



def test_job_ids_are_visible_only_with_explicit_opt_in(capsys):
    code = _code_by_id(_notebook())
    state = {"__name__": "__safe_id_recovery_test__"}
    _run_helpers(code, state)
    state["API_BASE_URL"] = "https://gateway.example.test"
    job_id = "00000000-0000-0000-0000-000000000333"
    state["RUN_SINGLE_MODEL_POST"] = True
    state["_gpu_preflight"] = lambda models: None
    state["_request"] = lambda *args, **kwargs: (202, {
        "job_id": job_id,
        "status": "pending",
        "kind": "translation",
        "status_url": "/v1/jobs/" + job_id,
    })
    exec(compile(code["post-translation"], str(NOTEBOOK), "exec"), state)
    assert job_id not in capsys.readouterr().out

    # Display through the read-only UUID cell, never by repeating a paid POST.
    state["SHOW_JOB_IDS"] = True
    state["RUN_SINGLE_MODEL_POST"] = False
    exec(compile(code["show-saved-job-id"], str(NOTEBOOK), "exec"), state)
    assert job_id in capsys.readouterr().out
    recovery = _advanced_guide(_notebook())
    assert "clear outputs" in recovery.lower()
    assert "LOAD_EXISTING_JOB_ID_FROM_SECRETS=True" in recovery


def test_new_request_and_private_recovery_conflict_fails_before_key_mutation():
    # Run real cells separately: persisted mode from Advanced is retained
    # when the user later edits only Basic Settings.
    code = {c["id"]: c["source"] for c in _notebook()["cells"]
            if c["cell_type"] == "code"}
    state = {"__name__": "__conflict__"}
    for cid in ("request-key-internals", "settings", "advanced-settings"):
        exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    old = (state["SINGLE_MODEL_IDEMPOTENCY_KEY"],
           state["MULTI_MODEL_IDEMPOTENCY_KEY"])
    state["LOAD_PERSISTED_IDEMPOTENCY_KEYS"] = True
    invalid = code["settings"].replace(
        'NEW_SINGLE_REQUEST_ACTION = ""', 'NEW_SINGLE_REQUEST_ACTION = "next"'
    )
    with pytest.raises(ValueError, match="either new request keys or persisted-key recovery"):
        exec(compile(invalid, str(NOTEBOOK), "exec"), state)
    assert old == (state["SINGLE_MODEL_IDEMPOTENCY_KEY"],
                   state["MULTI_MODEL_IDEMPOTENCY_KEY"])
    state["NEW_SINGLE_REQUEST_ACTION"] = "next"
    state["LOAD_FROM_COLAB_SECRETS"] = True
    with pytest.raises(ValueError, match="either new request keys or persisted-key recovery"):
        exec(compile(code["secret-loader"], str(NOTEBOOK), "exec"), state)


@pytest.mark.parametrize("failure", ["timeout", "network", "http", "malformed"])
def test_poll_error_is_isolated_and_subsequent_job_is_returned(failure):
    """A failure for the first job must not suppress an available second result."""
    from urllib.error import URLError

    code = _code_by_id(_notebook())
    state = {"__name__": "__isolated_polling_test__"}
    _run_helpers(code, state)
    first = "00000000-0000-0000-0000-000000003333"
    second = "00000000-0000-0000-0000-000000004444"
    state["submitted_single"] = {"job_id": first, "_gateway_origin": state["API_BASE_URL"]}
    state["submitted_multi"] = {"job_id": second, "_gateway_origin": state["API_BASE_URL"]}
    state["RUN_SUBMITTED_JOB_POLL"] = True
    state["SUBMITTED_JOB_TO_POLL"] = "both"
    assert state["RUN_SINGLE_MODEL_POST"] is False
    assert state["RUN_MULTI_MODEL_POST"] is False
    calls = []
    errors = {
        "timeout": TimeoutError("private-api-token and secret text"),
        "network": URLError("private-api-token and secret text"),
        "http": state["APIRequestError"](503),
        "malformed": ValueError("private-api-token and secret text"),
    }
    completed = {"job_id": second, "status": "completed", "runs": [
        {"model": "hy_mt2_30b", "status": "completed",
         "translation_text": "PRIVATE TRANSLATION",
         "is_mock_result": False, "error_code": None}
    ]}

    def fake_poll(jid):
        calls.append(jid)
        if jid == first:
            raise errors[failure]
        return completed

    state["_poll"] = fake_poll
    state["_request"] = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("No direct HTTP or POST expected from mocked _poll")
    )
    output = io.StringIO()
    _bind_accepted_test_references(state)
    with contextlib.redirect_stdout(output):
        exec(compile(code["get-job"], str(NOTEBOOK), "exec"), state)

    assert calls == [first, second]
    assert state["job_results"] == [completed]
    assert len(state["poll_failures"]) == 1
    assert state["submitted_single"]["job_id"] == first
    assert state["submitted_multi"]["job_id"] == second
    expected = {
        "timeout": {"reason": "timeout"},
        "network": {"reason": "network"},
        "http": {"reason": "http", "status_code": 503},
        "malformed": {"reason": "invalid_response"},
    }
    assert state["poll_failures"] == [expected[failure]]
    text = output.getvalue()
    assert "PRIVATE TRANSLATION" not in text
    assert "private-api-token" not in text
    assert first not in text and second not in text
    assert "do not resubmit paid POST" in text


def test_unsupported_language_pair_error_is_visible_in_safe_summary(capsys):
    code = _code_by_id(_notebook())
    state = {"__name__": "__unsupported_language_pair_summary_test__"}
    _run_helpers(code, state)
    job = {
        "kind": "translation",
        "status": "failed",
        "runs": [
            {"model": "hy_mt2_30b", "attempt_no": 1, "status": "failed",
             "error_code": "UNSUPPORTED_LANGUAGE_PAIR",
             "is_mock_result": False, "translation_text": None},
        ],
    }
    state["_show_summary"](job)
    printed = capsys.readouterr().out
    summary, _ = json.JSONDecoder().raw_decode(printed[printed.index("{"):])
    assert summary["runs"][0]["error_code"] == "UNSUPPORTED_LANGUAGE_PAIR"
    assert summary["runs"][0]["status"] == "failed"
    assert "unknown_error" not in printed


def test_saved_uuid_remains_hidden_by_default_and_bulk_reveal_is_refused(capsys):
    code = _code_by_id(_notebook())
    state = {"__name__": "__private_uuid_default__"}
    _run_helpers(code, state)
    first = "00000000-0000-0000-0000-000000008882"
    second = "00000000-0000-0000-0000-000000008883"
    state["submitted_single"] = {"job_id": first}
    state["submitted_multi"] = {"job_id": second}
    state["_request"] = lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("Offline UUID retrieval must not send HTTP")
    )
    exec(compile(code["show-saved-job-id"], str(NOTEBOOK), "exec"), state)
    assert first not in capsys.readouterr().out
    state["SHOW_JOB_IDS"] = True
    state["SUBMITTED_JOB_TO_POLL"] = "both"
    exec(compile(code["show-saved-job-id"], str(NOTEBOOK), "exec"), state)
    out = capsys.readouterr().out
    assert "Select exactly one" in out
    assert first not in out and second not in out
    state["SUBMITTED_JOB_TO_POLL"] = "single"
    state["submitted_single"] = None
    exec(compile(code["show-saved-job-id"], str(NOTEBOOK), "exec"), state)
    assert "No accepted submission" in capsys.readouterr().out


def test_progress_reports_per_model_changes_without_private_fields(capsys):
    """One model finishes early; progress is visible before the other completes."""
    code = _code_by_id(_notebook())
    state = {"__name__": "__offline_poll_progress__"}
    _run_helpers(code, state)
    state["POLL_INTERVAL_SECONDS"] = 0
    job_id = "00000000-0000-0000-0000-000000008884"
    private_text = "SECRET_TRANSLATION_NOT_FOR_NOTEBOOK_OUTPUT"
    states = [
        ["completed", "running"],
        ["completed", "running"],
        ["completed", "completed"],
    ]
    requests = []

    def fake_get(method, path, **kwargs):
        assert method == "GET" and kwargs.get("authenticated") is True
        requests.append(path)
        a, b = states.pop(0)
        return 200, {
            "status": "completed" if b == "completed" else "running",
            "job_id": job_id,
            "runs": [
                {"model": "hy_mt2_30b", "attempt_no": 1,
                 "status": a, "translation_text": private_text},
                {"model": "index_35b", "attempt_no": 1,
                 "status": b, "translation_text": private_text},
            ],
        }

    state["_request"] = fake_get
    with contextlib.redirect_stdout(io.StringIO()) as output:
        result = state["_poll"](job_id, timeout_seconds=10)
    lines = output.getvalue().splitlines()
    assert len(requests) == 3
    assert len(lines) == 3  # Two initial states + one changed model.
    assert "hy_mt2_30b attempt 1: completed" in lines[0]
    assert "index_35b attempt 1: running" in lines[1]
    assert "index_35b attempt 1: completed" in lines[2]
    assert all(line.startswith("[+") for line in lines)
    assert result["status"] == "completed"
    assert private_text not in output.getvalue()
    assert job_id not in output.getvalue()
    assert "https://" not in output.getvalue()


@pytest.mark.parametrize("bad_token", [
    "private-test-token\nextra", "private-test-token\rextra",
    "private-test-token\r\nextra", "private-test-token\textra",
    "private-test-token\x00extra", "private-test-token\u2028extra",
    "private-test-token\n", " private-test-token",
])
def test_invalid_private_token_is_rejected_before_http_without_leaking(
    monkeypatch, bad_token
):
    """An HTTP-header error must never echo the private value into a traceback."""
    import traceback

    codes = _code_by_id(_notebook())
    state = {"__name__": "__invalid_bearer__"}
    _run_helpers(codes, state)
    state["API_TOKEN"] = bad_token
    state["API_BASE_URL"] = "https://private-gateway.example.test"
    with patch("urllib.request.OpenerDirector.open",
               side_effect=AssertionError("Request must not reach the network")):
        with pytest.raises(ValueError, match="Invalid private Bearer token format") as exc:
            state["_request"]("GET", "/v1/models", authenticated=True)
    rendered = "".join(traceback.format_exception(exc.value))
    assert bad_token not in rendered
    assert "private-test-token" not in rendered
    assert "private-gateway.example.test" not in rendered


def test_transport_header_exception_is_sanitized_even_with_a_valid_token():
    import traceback

    codes = _code_by_id(_notebook())
    state = {"__name__": "__transport_sanitized__"}
    _run_helpers(codes, state)
    secret = "synthetic-token-must-never-be-in-err"
    state["API_TOKEN"] = secret
    state["API_BASE_URL"] = "https://private-gateway.example.test"

    def bad_header(*_args, **_kwargs):
        raise ValueError("Invalid header value b'Bearer " + secret + "'")

    state["_OPENER"] = types.SimpleNamespace(open=bad_header)
    with pytest.raises(state["NetworkRequestError"],
                       match="Invalid request encoding") as exc:
        state["_request"]("GET", "/v1/models", authenticated=True)
    rendered = "".join(traceback.format_exception(exc.value))
    assert secret not in rendered
    assert "private-gateway.example.test" not in rendered


def test_one_shot_labels_reject_secret_like_or_invalid_input_before_key_changes():
    # Each real settings cell validates its own label before changing keys.
    code = {c["id"]: c["source"] for c in _notebook()["cells"]
            if c["cell_type"] == "code"}
    state = {"__name__": "__bad_action_input__"}
    for cid in ("request-key-internals", "settings", "advanced-settings"):
        exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    old_single = state["SINGLE_MODEL_IDEMPOTENCY_KEY"]
    old_multi = state["MULTI_MODEL_IDEMPOTENCY_KEY"]
    bad_single = code["settings"].replace(
        'NEW_SINGLE_REQUEST_ACTION = ""',
        'NEW_SINGLE_REQUEST_ACTION = "contains space"'
    )
    with pytest.raises(ValueError, match="non-secret alphanumeric action label"):
        exec(compile(bad_single, str(NOTEBOOK), "exec"), state)
    bad_multi = code["settings"].replace(
        'NEW_BENCHMARK_REQUEST_ACTION = ""',
        'NEW_BENCHMARK_REQUEST_ACTION = "contains space"'
    )
    with pytest.raises(ValueError, match="non-secret alphanumeric action label"):
        exec(compile(bad_multi, str(NOTEBOOK), "exec"), state)
    assert state["SINGLE_MODEL_IDEMPOTENCY_KEY"] == old_single
    assert state["MULTI_MODEL_IDEMPOTENCY_KEY"] == old_multi


@pytest.mark.parametrize("raw_body", [
    b"<html>private token secret; proxy error</html>",
    b'{"job_id": "truncated"',
    b"\\xff\\xfe\\xfd",
])
def test_http_200_invalid_json_uses_invalid_response_error(monkeypatch, raw_body):
    """Real decoder classifies non-JSON/invalid encoding as content, not network."""
    code = _code_by_id(_notebook())
    state = {"__name__": "__invalid_json_transport__"}
    _run_helpers(code, state)
    state["API_BASE_URL"] = "https://private-gateway.example.test"
    state["API_TOKEN"] = "private-hidden-token"

    class FakeResponse(io.BytesIO):
        status = 200

    calls = []
    def fake_open(request, timeout):
        calls.append((request.get_method(), timeout))
        return FakeResponse(raw_body)

    monkeypatch.setattr(state["_OPENER"], "open", fake_open)
    with pytest.raises(state["InvalidResponseError"], match="Invalid JSON response") as failure:
        state["_request"]("GET", "/v1/jobs/00000000-0000-0000-0000-000000007001",
                          authenticated=True)
    assert not isinstance(failure.value, state["NetworkRequestError"])
    assert calls == [("GET", 30)]
    assert "private-hidden-token" not in str(failure.value)
    assert "private-gateway.example.test" not in str(failure.value)
    assert "proxy error" not in str(failure.value)


@pytest.mark.parametrize(("cid", "flag", "path", "multi"), (
    ("post-translation", "RUN_SINGLE_MODEL_POST", "/v1/jobs/translations", False),
    ("post-benchmark", "RUN_MULTI_MODEL_POST", "/v1/jobs/benchmarks", True),
))
def test_invalid_gateway_then_valid_gateway_does_not_lock_unused_key(cid, flag, path, multi):
    """F1: failed local URL validation must not poison a previously unused key."""
    code = _code_by_id(_notebook())
    state = {"__name__": "__f1_invalid_url_test__"}
    _run_helpers(code, state)
    state["ACKNOWLEDGE_PAID_GPU"] = True
    state[flag] = True
    key = state["MULTI_MODEL_IDEMPOTENCY_KEY" if multi else "SINGLE_MODEL_IDEMPOTENCY_KEY"]
    state["API_BASE_URL"] = ""  # Simulate missing Secrets even with prior environment.
    state["_request"] = lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("An invalid local URL must not issue HTTP")
    )
    with pytest.raises(ValueError, match="valid HTTPS gateway"):
        exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    assert key not in state["_REQUEST_IDENTITIES"]

    state["API_BASE_URL"] = "https://gateway.example.test"
    calls = []
    job_id = "00000000-0000-0000-0000-000000004401"
    def fake_request(method, api_path, **kwargs):
        calls.append((method, api_path))
        if method == "POST":
            assert kwargs["idempotency_key"] == key
            return 202, {"job_id": job_id, "status_url": "/v1/jobs/" + job_id}
        if api_path == "/health":
            return 200, {"inference_enabled": True, "phase": "gpu"}
        assert api_path == "/v1/models"
        return 200, {"models": [
            {"key": name, "enabled": True, "runtime_verified": True}
            for name in state["MODEL_KEYS"]
        ]}
    state["_request"] = fake_request
    exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    assert calls == [("GET", "/health"), ("GET", "/v1/models"), ("POST", path)]
    assert key in state["_REQUEST_IDENTITIES"]
    submission = state["submitted_multi" if multi else "submitted_single"]
    assert submission["job_id"] == job_id




@pytest.mark.parametrize("failure_type", ["url", "timeout", "encoding"])
def test_invalid_locale_cannot_expose_original_transport_exception(failure_type):
    import traceback
    from urllib.error import URLError

    code = _code_by_id(_notebook())
    state = {"__name__": "__invalid_locale_transport__"}
    _run_helpers(code, state)
    state.update(DISPLAY_LANGUAGE="VI", API_BASE_URL="https://private.example.test", API_TOKEN="synthetic-token")
    failures = {"url": URLError("SYNTHETIC_PRIVATE_ENDPOINT"),
                "timeout": TimeoutError("SYNTHETIC_PRIVATE_ENDPOINT"),
                "encoding": ValueError("SYNTHETIC_PRIVATE_ENDPOINT")}
    with patch.object(state["_OPENER"], "open", side_effect=failures[failure_type]):
        try:
            state["_request"]("GET", "/v1/models", authenticated=True)
        except Exception:
            rendered = traceback.format_exc()
        else:
            pytest.fail("Expected an invalid-locale or sanitized transport error")
    assert "SYNTHETIC_PRIVATE_ENDPOINT" not in rendered


def test_invalid_locale_is_rejected_before_any_http_request():
    code = _code_by_id(_notebook())
    state = {"__name__": "__invalid_locale_before_http__"}
    _run_helpers(code, state)
    state.update(DISPLAY_LANGUAGE="VI", API_BASE_URL="https://private.example.test", API_TOKEN="synthetic-token")
    with patch.object(state["_OPENER"], "open", side_effect=AssertionError("HTTP must not start")):
        with pytest.raises(ValueError, match="DISPLAY_LANGUAGE"):
            state["_request"]("POST", "/v1/jobs/translations", authenticated=True, payload={})


@pytest.mark.parametrize("failure_type", ["url", "timeout", "encoding"])
def test_transport_details_stay_hidden_if_locale_changes_during_the_request(failure_type):
    import traceback
    from urllib.error import URLError

    code = _code_by_id(_notebook())
    state = {"__name__": "__locale_changed_during_transport__"}
    _run_helpers(code, state)
    state.update(API_BASE_URL="https://private.example.test", API_TOKEN="synthetic-valid-test-token")
    failures = {"url": URLError("SYNTHETIC_PRIVATE_ENDPOINT"),
                "timeout": TimeoutError("SYNTHETIC_PRIVATE_ENDPOINT"),
                "encoding": ValueError("SYNTHETIC_PRIVATE_ENDPOINT")}

    def fail_during_request(*args, **kwargs):
        state["DISPLAY_LANGUAGE"] = "VI"
        raise failures[failure_type]

    with patch.object(state["_OPENER"], "open", side_effect=fail_during_request):
        try:
            state["_request"]("GET", "/v1/models", authenticated=True)
        except Exception:
            rendered = traceback.format_exc()
        else:
            pytest.fail("Expected a sanitized transport error")
    assert "SYNTHETIC_PRIVATE_ENDPOINT" not in rendered
    assert "NetworkRequestError" in rendered
