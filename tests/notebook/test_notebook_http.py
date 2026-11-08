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
    _notebook,
    _run_helpers,
)


@pytest.fixture(autouse=True)
def _synthetic_gateway_for_isolated_notebook_tests(monkeypatch):
    # A stable test-only URL; all actual HTTP is mocked in the test cases.
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://gateway.example.test")


@pytest.mark.parametrize("header,expected", [
    ("60", 60), ("0", 0), ("86400", 86400), (" 120 ", 120),
    (None, None), ("-1", None), ("1.5", None), ("86401", None),
    ("9" * 1000, None), ("private-retry-value", None), ("１２", None),
    ("Wed, 11 Nov 2026 09:00:00 GMT", None),
])
def test_http_429_retains_only_bounded_numeric_retry_after(header, expected):
    from urllib.error import HTTPError

    code = _code_by_id(_notebook())
    state = {"__name__": "__retry_after_headers__"}
    _run_helpers(code, state)
    headers = {} if header is None else {"Retry-After": header}
    error = HTTPError("https://private.example.test", 429, "private-reason", headers,
                      io.BytesIO(b"private-response-body"))
    with patch.object(state["_OPENER"], "open", side_effect=error):
        with pytest.raises(state["APIRequestError"]) as caught:
            state["_request"]("GET", "/v1/models")
    assert caught.value.status_code == 429
    assert caught.value.retry_after_seconds == expected
    message = str(caught.value)
    if expected is not None:
        assert f"Retry-After: {expected} seconds" in message
    else:
        assert "Retry-After:" not in message
    for private in ("private-retry-value", "private-reason", "private-response-body", "private.example.test"):
        assert private not in message


def test_get_429_displays_retry_after_without_automatic_retry(capsys):
    code = _code_by_id(_notebook())
    state = {"__name__": "__get_retry_hint__"}
    _run_helpers(code, state)
    state.update(RUN_EXISTING_JOB_POLL=True, EXISTING_JOB_ID="00000000-0000-0000-0000-000000007010")
    attempts = []

    def poll(job_id):
        attempts.append(job_id)
        raise state["APIRequestError"](429, retry_after_seconds=60)

    state["_poll"] = poll
    exec(compile(code["get-job"], str(NOTEBOOK), "exec"), state)
    assert len(attempts) == 1
    assert state["poll_failures"] == [{"reason": "http", "status_code": 429}]
    assert "Retry-After: 60 seconds" in capsys.readouterr().out



def test_get_endpoints_and_job_polling_use_authenticated_safe_http_mocks(monkeypatch, capsys):
    """Exercise GET cells with fake HTTP only: no real gateway or GPU access."""
    import io
    from urllib.parse import urlsplit

    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://gateway.example.test")
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", "secret-not-to-be-printed")
    job_id = "00000000-0000-0000-0000-000000000001"
    monkeypatch.setenv("TRANSLATION_EXISTING_JOB_ID", job_id)
    state = {"__name__": "__mock_http_notebook_test__"}
    code = _code_by_id(_notebook())
    _run_helpers(code, state)
    state["RUN_HEALTH_GET"] = True
    state["RUN_MODEL_CATALOG_GET"] = True
    state["RUN_EXISTING_JOB_POLL"] = True
    requested = []

    class FakeHTTPResponse(io.BytesIO):
        def __init__(self, body):
            super().__init__(json.dumps(body).encode("utf-8"))
            self.status = 200

    def fake_open(request, timeout):
        assert timeout == 30
        assert request.get_method() == "GET", "No POST must run during GET acceptance."
        path = urlsplit(request.full_url).path
        requested.append(path)
        assert request.full_url.startswith("https://gateway.example.test/")
        assert request.get_header("Accept") == "application/json"
        if path == "/health":
            assert request.get_header("Authorization") is None
            return FakeHTTPResponse({"status": "ok", "inference_enabled": True, "phase": "gpu"})
        assert request.get_header("Authorization") == "Bearer secret-not-to-be-printed"
        if path == "/v1/models":
            return FakeHTTPResponse({"models": [
                {"key": key, "enabled": True, "runtime_verified": True}
                for key in state["MODEL_KEYS"]
            ]})
        assert path == f"/v1/jobs/{job_id}"
        return FakeHTTPResponse({
            "job_id": job_id, "status": "completed", "kind": "translation",
            "runs": [{
                "model": "hy_mt2_30b", "status": "completed",
                "translation_text": "private-synthetic-translation",
                "is_mock_result": False, "error_code": None,
            }],
        })

    monkeypatch.setattr(state["_OPENER"], "open", fake_open)
    for cid in ("get-health", "get-models", "post-translation",
                "post-benchmark", "get-job"):
        exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    assert requested == ["/health", "/v1/models", f"/v1/jobs/{job_id}"]
    assert state["health_result"]["inference_enabled"] is True
    assert len(state["catalog_result"]["models"]) == 4
    assert len(state["job_results"]) == 1
    printed = capsys.readouterr().out
    assert "secret-not-to-be-printed" not in printed
    assert "gateway.example.test" not in printed
    assert "private-synthetic-translation" not in printed
    assert job_id not in printed


@pytest.mark.parametrize(("status", "expected_action"), [
    (401, "Bearer token"),
    (403, "access permissions"),
    (404, "verify the saved job UUID"),
    (429, "respect rate limits"),
    (500, "gateway availability"),
    (503, "gateway availability"),
])
def test_poll_http_status_is_actionable_and_no_sensitive_value_is_echoed(status, expected_action):
    code = _code_by_id(_notebook())
    state = {"__name__": "__safe_http_poll_errors__"}
    _run_helpers(code, state)
    first = "00000000-0000-0000-0000-000000001100"
    second = "00000000-0000-0000-0000-000000001101"
    state["submitted_single"] = {"job_id": first, "_gateway_origin": state["API_BASE_URL"]}
    state["submitted_multi"] = {"job_id": second, "_gateway_origin": state["API_BASE_URL"]}
    state["RUN_SUBMITTED_JOB_POLL"] = True
    state["SUBMITTED_JOB_TO_POLL"] = "both"
    calls = []

    def fake_poll(jid):
        calls.append(jid)
        if jid == first:
            raise state["APIRequestError"](status)
        return {"job_id": jid, "runs": [], "status": "completed"}

    state["_poll"] = fake_poll
    state["_show_summary"] = lambda job: None
    output = io.StringIO()
    _bind_accepted_test_references(state)
    with contextlib.redirect_stdout(output):
        exec(compile(code["get-job"], str(NOTEBOOK), "exec"), state)

    assert calls == [first, second]
    assert state["poll_failures"] == [{"reason": "http", "status_code": status}]
    assert len(state["job_results"]) == 1
    message = output.getvalue()
    assert f"GET job HTTP {status}" in message
    assert expected_action in message
    assert "do not resubmit paid POST" in message
    assert first not in message and second not in message
    for private in ("Authorization", "secret-token", "http://private", "translation_text"):
        assert private not in message


def test_poll_invalid_http_code_is_not_reflected_as_private_string():
    code = _code_by_id(_notebook())
    state = {"__name__": "__http_status_sanitization_test__"}
    _run_helpers(code, state)
    state["RUN_SUBMITTED_JOB_POLL"] = True
    state["SUBMITTED_JOB_TO_POLL"] = "both"
    state["submitted_single"] = {"job_id": "00000000-0000-0000-0000-000000001102", "_gateway_origin": state["API_BASE_URL"]}
    state["_poll"] = lambda jid: (_ for _ in ()).throw(
        state["APIRequestError"]("private-auth-token")
    )
    out = io.StringIO()
    _bind_accepted_test_references(state)
    with contextlib.redirect_stdout(out):
        exec(compile(code["get-job"], str(NOTEBOOK), "exec"), state)
    assert state["poll_failures"] == [{"reason": "http", "status_code": None}]
    assert "private-auth-token" not in out.getvalue()


@pytest.mark.parametrize(("token", "language"), [
    ("short", "en"),
    ("x" * 15, "vi"),
    ("x" * 4097, "en"),
])
def test_authenticated_notebook_rejects_invalid_token_length_before_network(token, language):
    code = _code_by_id(_notebook())
    state = {"__name__": "__invalid_token_length_test__"}
    _run_helpers(code, state)
    state["API_BASE_URL"] = "https://gateway.example.test"
    state["API_TOKEN"] = token
    state["DISPLAY_LANGUAGE"] = language
    with patch.object(state["_OPENER"], "open") as outbound:
        with pytest.raises(ValueError) as caught:
            state["_request"]("GET", "/v1/models", authenticated=True)
    outbound.assert_not_called()
    assert token not in str(caught.value)
    if language == "vi":
        assert "16–4096 ký tự ASCII" in str(caught.value)
    else:
        assert "16–4096 ASCII characters" in str(caught.value)


@pytest.mark.parametrize("length", [16, 4096])
def test_authenticated_notebook_accepts_token_length_boundaries_offline(length):
    code = _code_by_id(_notebook())
    state = {"__name__": "__valid_token_length_test__"}
    _run_helpers(code, state)
    state["API_BASE_URL"] = "https://gateway.example.test"
    state["API_TOKEN"] = "a" * length

    class LocalResponse(io.BytesIO):
        status = 200

    with patch.object(
        state["_OPENER"], "open",
        return_value=LocalResponse(b'{"models": []}'),
    ) as outbound:
        status, result = state["_request"]("GET", "/v1/models", authenticated=True)
    assert status == 200 and result == {"models": []}
    outbound.assert_called_once()


def test_transport_failure_is_sanitized_to_distinct_network_exception(monkeypatch):
    from urllib.error import URLError

    code = _code_by_id(_notebook())
    state = {"__name__": "__sanitize_transport_test__"}
    _run_helpers(code, state)
    state["API_BASE_URL"] = "https://private.example.test"
    state["API_TOKEN"] = "private-token-for-tests"
    with patch.object(state["_OPENER"], "open", side_effect=URLError(
        "private.example.test/private-token"
    )):
        with pytest.raises(state["NetworkRequestError"]) as error:
            state["_request"]("GET", "/v1/jobs/00000000-0000-0000-0000-000000001103",
                              authenticated=True)
    assert "private-token" not in str(error.value)
    assert "private.example.test" not in str(error.value)


@pytest.mark.parametrize("malformed", [
    None,
    [],
    {"status": "completed", "runs": [None]},
    {"status": "completed", "runs": {}},
    {"status": "completed", "runs": []},
    {"status": "completed", "runs": [{"model": "hy_mt2_30b", "status": None}]},
])
def test_real_poll_malformed_http_json_is_isolated_and_keeps_job_references(
    malformed, capsys,
):
    """Real helper: an invalid HTTP-200 payload must not suppress later jobs."""
    code = _code_by_id(_notebook())
    state = {"__name__": "__malformed_http_json_test__"}
    _run_helpers(code, state)
    first = "00000000-0000-0000-0000-000000008888"
    second = "00000000-0000-0000-0000-000000009999"
    state["submitted_single"] = {"job_id": first, "_gateway_origin": state["API_BASE_URL"]}
    state["submitted_multi"] = {"job_id": second, "_gateway_origin": state["API_BASE_URL"]}
    state["RUN_SUBMITTED_JOB_POLL"] = True
    state["SUBMITTED_JOB_TO_POLL"] = "both"
    requests = []
    valid = {
        "job_id": second, "status": "completed",
        "runs": [{"model": "hy_mt2_30b", "status": "completed",
                  "attempt_no": 1, "translation_text": "HIDDEN VALUE",
                  "is_mock_result": False}],
    }

    def fake_request(method, path, **kwargs):
        requests.append((method, path, kwargs.get("authenticated")))
        assert method == "GET" and kwargs.get("authenticated") is True
        return (200, malformed) if path.endswith(first) else (200, valid)

    state["_request"] = fake_request
    _bind_accepted_test_references(state)
    exec(compile(code["get-job"], str(NOTEBOOK), "exec"), state)

    assert len(requests) == 2
    assert requests[0][1].endswith(first) and requests[1][1].endswith(second)
    assert state["poll_failures"] == [{"reason": "invalid_response"}]
    assert state["job_results"] == [valid]
    assert state["submitted_single"]["job_id"] == first
    assert state["submitted_multi"]["job_id"] == second
    printed = capsys.readouterr().out
    assert "GET job invalid response" in printed
    assert "HIDDEN VALUE" not in printed
    assert first not in printed and second not in printed


@pytest.mark.parametrize("kind,cid,selector,path,key,flag", [
    ("single", "post-translation", "single", "/v1/jobs/translations",
     "SINGLE_MODEL_IDEMPOTENCY_KEY", "RUN_SINGLE_MODEL_POST"),
    ("multi", "post-benchmark", "multi", "/v1/jobs/benchmarks",
     "MULTI_MODEL_IDEMPOTENCY_KEY", "RUN_MULTI_MODEL_POST"),
])
@pytest.mark.parametrize("failed_stage", ["preflight", "network", "not_submitted"])
def test_new_request_cannot_poll_prior_accepted_job_but_can_recover(
    kind, cid, selector, path, key, flag, failed_stage, capsys
):
    guide = next(c["source"] for c in _notebook()["cells"] if c["id"] == "poll-md")
    assert "will **not** silently retrieve an older job" in guide
    assert "không** âm thầm lấy job cũ" in guide
    code = _code_by_id(_notebook())
    state = {"__name__": "__request_identity_guard_test__"}
    _run_helpers(code, state)
    a_id = "00000000-0000-0000-0000-000000009101"
    b_id = "00000000-0000-0000-0000-000000009102"
    state["ACKNOWLEDGE_PAID_GPU"] = True
    state[flag] = True
    state["_gpu_preflight"] = lambda models: None
    calls = []

    def accepted_a(method, endpoint, **kw):
        calls.append(method)
        assert method == "POST" and endpoint == path
        return 202, {"job_id": a_id, "status_url": "/v1/jobs/" + a_id}

    state["_request"] = accepted_a
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    saved = state["submitted_" + kind]
    original_key = state[key]
    assert saved["_request_fingerprint"] and saved["_gateway_origin"] == state["API_BASE_URL"]

    # A new sentence/key is a different logical request despite the same gateway.
    settings_b = code["settings"].replace(
        'TEXT_TO_TRANSLATE = "The little fox crossed the wooden bridge at sunrise."',
        'TEXT_TO_TRANSLATE = "Second synthetic sentence for job B."',
    )
    label = "NEW_SINGLE_REQUEST_ACTION" if kind == "single" else "NEW_BENCHMARK_REQUEST_ACTION"
    settings_b = settings_b.replace(label + ' = ""', label + ' = "second"')
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(settings_b, str(NOTEBOOK), "exec"), state)
    assert state[key] != original_key
    state["ACKNOWLEDGE_PAID_GPU"] = True
    state[flag] = True
    if failed_stage == "preflight":
        state["_gpu_preflight"] = lambda models: (_ for _ in ()).throw(
            RuntimeError("Synthetic preflight failure")
        )
    elif failed_stage == "network":
        state["_gpu_preflight"] = lambda models: None
        state["_request"] = lambda *args, **kw: (_ for _ in ()).throw(
            state["NetworkRequestError"]("Synthetic ambiguous network error")
        )
    # not_submitted represents changed settings with no POST attempt.
    if failed_stage != "not_submitted":
        with pytest.raises(RuntimeError):
            exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    assert state["submitted_" + kind] is saved
    assert calls == ["POST"]

    polled = []
    state["_poll"] = lambda jid: polled.append(jid) or {"job_id": jid, "runs": []}
    state["_show_summary"] = lambda _: None
    state["RUN_SUBMITTED_JOB_POLL"] = True
    state["SUBMITTED_JOB_TO_POLL"] = selector
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(code["get-job"], str(NOTEBOOK), "exec"), state)
    assert polled == []
    assert state["poll_failures"] == [{"reason": "request_mismatch"}]
    assert state["submitted_" + kind] is saved

    # Explicit UUID recovery reads A, without any extra paid POST.
    state["RUN_SUBMITTED_JOB_POLL"] = False
    state["RUN_EXISTING_JOB_POLL"] = True
    state["EXISTING_JOB_ID"] = a_id
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(code["get-job"], str(NOTEBOOK), "exec"), state)
    assert polled == [a_id]
    assert calls == ["POST"]

    # After uncertain B POST, do not resend it in this kernel; reconcile first.
    # Preflight-only/no-POST cases are still free to submit B normally.
    state["RUN_EXISTING_JOB_POLL"] = False
    state["RUN_SUBMITTED_JOB_POLL"] = True
    state["_gpu_preflight"] = lambda models: None

    def accepted_b(method, endpoint, **kw):
        calls.append(method)
        assert method == "POST" and endpoint == path
        assert kw["idempotency_key"] == state[key]
        return 202, {"job_id": b_id, "status_url": "/v1/jobs/" + b_id}

    state["_request"] = accepted_b
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
        exec(compile(code["get-job"], str(NOTEBOOK), "exec"), state)
    if failed_stage == "network":
        assert state["submitted_" + kind] is saved
        assert polled == [a_id]
        assert calls == ["POST"]
        assert state["poll_failures"] == [{"reason": "request_mismatch"}]
    else:
        assert state["submitted_" + kind]["job_id"] == b_id
        assert polled == [a_id, b_id]
        assert calls == ["POST", "POST"]
    assert a_id not in capsys.readouterr().out


@pytest.mark.parametrize("bad_body", [
    b"<html>private body; proxy error</html>",
    b'{"status":"completed",',
    b"\\xff\\xfe\\xfd",
])
def test_real_get_two_jobs_handles_unparseable_http_body_independently(
    monkeypatch, capsys, bad_body
):
    """Actual HTTP decoder, fake transport: first invalid, second valid, IDs retained."""
    code = _code_by_id(_notebook())
    state = {"__name__": "__invalid_json_get__"}
    _run_helpers(code, state)
    state["API_BASE_URL"] = "https://private-gateway.example.test"
    state["API_TOKEN"] = "private-hidden-token"
    first = "00000000-0000-0000-0000-000000007101"
    second = "00000000-0000-0000-0000-000000007102"
    state["submitted_single"] = {
        "job_id": first, "_gateway_origin": state["API_BASE_URL"]
    }
    state["submitted_multi"] = {
        "job_id": second, "_gateway_origin": state["API_BASE_URL"]
    }
    state["RUN_SUBMITTED_JOB_POLL"] = True
    state["SUBMITTED_JOB_TO_POLL"] = "both"
    _bind_accepted_test_references(state)
    good = {
        "job_id": second, "status": "completed", "kind": "benchmark",
        "runs": [{"model": "hy_mt2_30b", "status": "completed",
                  "attempt_no": 1, "translation_text": "HIDDEN TEXT",
                  "is_mock_result": False}],
    }
    class FakeResponse(io.BytesIO):
        status = 200

    calls = []
    def fake_open(request, timeout):
        path = request.full_url
        assert request.get_method() == "GET" and timeout == 30
        assert request.get_header("Authorization") == "Bearer private-hidden-token"
        calls.append(path)
        if path.endswith(first):
            return FakeResponse(bad_body)
        assert path.endswith(second)
        return FakeResponse(json.dumps(good).encode("utf-8"))

    monkeypatch.setattr(state["_OPENER"], "open", fake_open)
    exec(compile(code["get-job"], str(NOTEBOOK), "exec"), state)
    assert len(calls) == 2 and calls[0].endswith(first) and calls[1].endswith(second)
    assert state["poll_failures"] == [{"reason": "invalid_response"}]
    assert state["job_results"] == [good]
    assert state["submitted_single"]["job_id"] == first
    assert state["submitted_multi"]["job_id"] == second
    output = capsys.readouterr().out
    assert "GET job invalid response" in output
    for private in ("private-hidden-token", "private-gateway.example.test",
                    "proxy error", "HIDDEN TEXT", first, second):
        assert private not in output




@pytest.mark.parametrize("failure", ["incomplete", "disconnected", "reset"])
def test_body_read_failure_is_sanitized_and_does_not_abort_other_job(failure, capsys):
    from http.client import IncompleteRead, RemoteDisconnected

    code = _code_by_id(_notebook())
    state = {"__name__": "__body_read_failure__"}
    _run_helpers(code, state)
    state["API_TOKEN"] = "synthetic-transport-token"
    first = "00000000-0000-0000-0000-000000008101"
    second = "00000000-0000-0000-0000-000000008102"
    state.update(RUN_SUBMITTED_JOB_POLL=True, SUBMITTED_JOB_TO_POLL="both",
                 submitted_single={"job_id": first, "_gateway_origin": state["API_BASE_URL"]},
                 submitted_multi={"job_id": second, "_gateway_origin": state["API_BASE_URL"]})
    _bind_accepted_test_references(state)
    requests = []
    errors = {"incomplete": IncompleteRead(b"PRIVATE_RESPONSE_TEXT", 100),
              "disconnected": RemoteDisconnected("PRIVATE_RESPONSE_TEXT"),
              "reset": ConnectionResetError("PRIVATE_RESPONSE_TEXT")}

    class BrokenResponse(io.BytesIO):
        status = 200
        def read(self, *args):
            raise errors[failure]

    class GoodResponse(io.BytesIO):
        status = 200

    def open_response(request, timeout):
        requests.append(request.full_url.rsplit("/", 1)[-1])
        if requests[-1] == first:
            return BrokenResponse()
        return GoodResponse(json.dumps({"job_id": second, "kind": "benchmark", "status": "completed",
            "runs": [{"model": "hy_mt2_30b", "status": "completed", "translation_text": "private translation",
                      "is_mock_result": False, "error_code": None}]}).encode())

    with patch.object(state["_OPENER"], "open", side_effect=open_response):
        exec(compile(code["get-job"], str(NOTEBOOK), "exec"), state)
    assert requests == [first, second]
    assert [job["job_id"] for job in state["job_results"]] == [second]
    assert state["poll_failures"] == [{"reason": "network"}]
    assert state["submitted_single"]["job_id"] == first
    printed = capsys.readouterr().out
    assert "PRIVATE_RESPONSE_TEXT" not in printed and "private translation" not in printed


@pytest.mark.parametrize("returned", [None, "not-a-private-uuid", "00000000-0000-0000-0000-000000008104"])
def test_poll_rejects_missing_invalid_or_mismatched_response_uuid(returned):
    code = _code_by_id(_notebook())
    state = {"__name__": "__response_identity__"}
    _run_helpers(code, state)
    requested = "00000000-0000-0000-0000-000000008103"
    state["_request"] = lambda *args, **kwargs: (200, {"job_id": returned, "status": "completed",
        "runs": [{"model": "hy_mt2_30b", "status": "completed"}]})
    with pytest.raises(state["InvalidResponseError"]):
        state["_poll"](requested)


@pytest.mark.parametrize("language", ["en", "vi"])
@pytest.mark.parametrize("multi", [False, True])
@pytest.mark.parametrize("value", ["secret\x00input", "secret\ud800input", "secret\udfffinput"])
def test_unstorable_text_fails_before_any_paid_or_preflight_request(language, multi, value):
    code = _code_by_id(_notebook())
    state = {"__name__": "__unicode_boundary__"}
    _run_helpers(code, state)
    state.update(DISPLAY_LANGUAGE=language, TEXT_TO_TRANSLATE=value,
                 ACKNOWLEDGE_PAID_GPU=True, RUN_SINGLE_MODEL_POST=not multi, RUN_MULTI_MODEL_POST=multi)
    with patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("No HTTP allowed")) as outbound:
        with pytest.raises(ValueError) as caught:
            exec(code["post-benchmark" if multi else "post-translation"], state)
    assert "secret" not in str(caught.value)
    assert "NUL" in str(caught.value)
    outbound.assert_not_called()
    assert state["_PAID_POST_ATTEMPTS"] == set()
