"""Notebook behavior regression tests."""
import contextlib
import io

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



def test_retrying_post_cells_reuses_idempotency_with_real_local_api(client_factory, monkeypatch):
    """The notebook client must not repeat paid HTTP POSTs in one kernel.

    Use the real local FastAPI mock dispatcher and in-memory database.
    Never send a network request or allocate GPU.
    """
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://gateway.example.test")
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", "synthetic-local-test-token")
    client, _ = client_factory()
    codes = _code_by_id(_notebook())
    state = {"__name__": "__offline_idempotency_test__"}
    _run_helpers(codes, state)
    state["RUN_SINGLE_MODEL_POST"] = True
    state["RUN_MULTI_MODEL_POST"] = False
    state["ACKNOWLEDGE_PAID_GPU"] = True
    state["_gpu_preflight"] = lambda models: None  # mocked local server is not a live GPU
    requests = []

    def local_request(method, path, *, payload=None, authenticated=False, idempotency_key=None):
        assert method == "POST" and authenticated and idempotency_key
        assert path in ("/v1/jobs/translations", "/v1/jobs/benchmarks")
        request = client.post(
            path,
            headers={
                "Authorization": "Bearer unit-test-token-2026",
                "Idempotency-Key": idempotency_key,
            },
            json=payload,
        )
        requests.append((path, idempotency_key, request.status_code))
        return request.status_code, request.json()

    state["_request"] = local_request
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(codes["post-translation"], str(NOTEBOOK), "exec"), state)
        first_translation_job = state["submitted_single"]["job_id"]
        exec(compile(codes["post-translation"], str(NOTEBOOK), "exec"), state)
        assert state["submitted_single"]["job_id"] == first_translation_job
        # Switch modes explicitly: conflicting paid POST flags are now rejected.
        state["RUN_SINGLE_MODEL_POST"] = False
        state["RUN_MULTI_MODEL_POST"] = True
        exec(compile(codes["post-benchmark"], str(NOTEBOOK), "exec"), state)
        first_benchmark_job = state["submitted_multi"]["job_id"]
        exec(compile(codes["post-benchmark"], str(NOTEBOOK), "exec"), state)
        assert state["submitted_multi"]["job_id"] == first_benchmark_job
    assert first_translation_job != first_benchmark_job
    # Duplicate paid POST cells do not send duplicate HTTP requests in one kernel.
    assert len(requests) == 2
    assert requests[0][1] != requests[1][1]
    assert all(code == 202 for _, _, code in requests)
    assert len(state["SINGLE_MODEL_IDEMPOTENCY_KEY"]) <= 200
    assert len(state["MULTI_MODEL_IDEMPOTENCY_KEY"]) <= 200


def test_uncertain_paid_post_cannot_be_automatically_replayed_in_same_kernel(monkeypatch):
    """If the network failed after submission, repeated POST cannot duplicate GPU work."""
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://gateway.example.test")
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", "synthetic-local-token")
    code = _code_by_id(_notebook())
    state = {"__name__": "__one_shot_guard_test__"}
    _run_helpers(code, state)
    state["RUN_SINGLE_MODEL_POST"] = True
    state["ACKNOWLEDGE_PAID_GPU"] = True
    state["_gpu_preflight"] = lambda models: None
    attempts = []

    def uncertain_request(method, path, **kwargs):
        attempts.append((method, path))
        raise RuntimeError("Synthetic uncertain network outcome")

    state["_request"] = uncertain_request
    with pytest.raises(RuntimeError, match="uncertain"):
        exec(compile(code["post-translation"], str(NOTEBOOK), "exec"), state)
    with contextlib.redirect_stdout(io.StringIO()) as stdout:
        exec(compile(code["post-translation"], str(NOTEBOOK), "exec"), state)
    assert attempts == [("POST", "/v1/jobs/translations")]
    assert "SKIPPED repeated paid POST" in stdout.getvalue()
    assert len(state["_PAID_POST_ATTEMPTS"]) == 1


@pytest.mark.parametrize("kind", ("single", "multi"))
def test_confirmed_quota_rejection_allows_manual_same_request_after_quota_reset(
    client_factory, monkeypatch, kind
):
    """A rejected admission creates no job; manual recovery keeps its original key."""
    import json
    from urllib.error import HTTPError
    from urllib.parse import urlsplit

    from sqlalchemy import select, update

    from multilingual_translation_ai_inference.database import Job, UsageWindow

    # This exercises a deployed-compatible client token (minimum 16 ASCII characters).
    valid_token = "unit-test-token-2026"
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", valid_token)
    client, repo = client_factory(max_jobs_per_day=1, api_bearer_token=valid_token)
    headers = {"Authorization": f"Bearer {valid_token}", "Idempotency-Key": "quota-fixture"}
    assert client.post("/v1/jobs/translations", headers=headers, json={
        "model": "hy_mt2_30b", "source_language": "en", "target_language": "vi", "text": "Fixture",
    }).status_code == 202
    code = _code_by_id(_notebook())
    state = {"__name__": "__confirmed_quota_rejection__"}
    _run_helpers(code, state)
    state.update(ACKNOWLEDGE_PAID_GPU=True)
    state["RUN_SINGLE_MODEL_POST" if kind == "single" else "RUN_MULTI_MODEL_POST"] = True
    state["_gpu_preflight"] = lambda models: None  # Local mock API intentionally has no GPU.
    key = state["SINGLE_MODEL_IDEMPOTENCY_KEY" if kind == "single" else "MULTI_MODEL_IDEMPOTENCY_KEY"]
    path = "/v1/jobs/translations" if kind == "single" else "/v1/jobs/benchmarks"
    cid = "post-translation" if kind == "single" else "post-benchmark"
    requests = []

    class Response(io.BytesIO):
        status = 202

    def local_open(request, timeout):
        assert request.method == "POST" and urlsplit(request.full_url).path == path
        response = client.post(path, headers=dict(request.header_items()), json=json.loads(request.data))
        requests.append((request.get_header("Idempotency-key"), request.data, response.status_code))
        if response.status_code >= 400:
            raise HTTPError(request.full_url, response.status_code, "Rejected", response.headers,
                            io.BytesIO(response.content))
        return Response(response.content)

    monkeypatch.setattr(state["_OPENER"], "open", local_open)
    with pytest.raises(state["APIRequestError"]) as failure:
        exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    assert failure.value.status_code == 429
    assert len(requests) == 1  # No automatic retries.
    assert state["submitted_" + kind] is None
    with repo.session_factory() as session:
        assert session.scalar(select(Job).where(Job.idempotency_key == key)) is None
        # Simulate the quota window becoming available, without sleeping or external I/O.
        session.execute(update(UsageWindow).values(used=0))
        session.commit()

    exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    assert state["submitted_" + kind] is not None
    assert [status for _, _, status in requests] == [429, 202]
    assert requests[0][:2] == requests[1][:2]  # Same key and exact serialized payload.
    exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    assert len(requests) == 2  # Accepted requests remain protected from duplicate POSTs.
    with repo.session_factory() as session:
        assert len(session.scalars(select(Job).where(Job.idempotency_key == key)).all()) == 1


@pytest.mark.parametrize("status", (409, 500, 503))
def test_other_http_post_failures_remain_blocked_until_reconciled(status):
    code = _code_by_id(_notebook())
    state = {"__name__": "__http_post_guard__"}
    _run_helpers(code, state)
    state.update(ACKNOWLEDGE_PAID_GPU=True, RUN_SINGLE_MODEL_POST=True)
    state["_gpu_preflight"] = lambda models: None
    attempts = []

    def request(method, path, **kwargs):
        attempts.append((method, path))
        raise state["APIRequestError"](status)

    state["_request"] = request
    with pytest.raises(state["APIRequestError"]):
        exec(compile(code["post-translation"], str(NOTEBOOK), "exec"), state)
    exec(compile(code["post-translation"], str(NOTEBOOK), "exec"), state)
    assert attempts == [("POST", "/v1/jobs/translations")]


def test_restored_job_polls_without_running_paid_post_cells(monkeypatch, capsys):
    """A fresh kernel can resume with a saved job ID via GET only."""
    job_id = "00000000-0000-0000-0000-000000000888"
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://gateway.example.test")
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", "private-test-token")
    monkeypatch.setenv("TRANSLATION_EXISTING_JOB_ID", job_id)
    code = _code_by_id(_notebook())
    state = {"__name__": "__fresh_recovery_kernel_test__"}
    _run_helpers(code, state)
    state["RUN_EXISTING_JOB_POLL"] = True
    assert not state["RUN_HEALTH_GET"] and not state["RUN_MODEL_CATALOG_GET"]

    def mock_get(method, path, **kwargs):
        assert method == "GET"
        assert kwargs.get("authenticated") is True
        assert path == "/v1/jobs/" + job_id
        return 200, {
            "job_id": job_id, "kind": "translation", "status": "completed",
            "runs": [{"model": "hy_mt2_30b", "status": "completed",
                      "translation_text": "private-result", "is_mock_result": False}],
        }

    state["_request"] = mock_get
    assert "submitted_single" not in state and "submitted_multi" not in state
    exec(compile(code["get-job"], str(NOTEBOOK), "exec"), state)
    assert len(state["job_results"]) == 1
    printed = capsys.readouterr().out
    assert "private-result" not in printed
    assert job_id not in printed


def test_paid_preflight_is_independent_of_optional_get_display_flags():
    code = _code_by_id(_notebook())
    state = {"__name__": "__preflight_independent_test__"}
    _run_helpers(code, state)
    assert state["RUN_HEALTH_GET"] is False
    assert state["RUN_MODEL_CATALOG_GET"] is False
    state["ACKNOWLEDGE_PAID_GPU"] = True
    requested = []

    def fake_request(method, path, **kwargs):
        requested.append((method, path, kwargs))
        if path == "/health":
            return 200, {"inference_enabled": True, "phase": "gpu"}
        return 200, {"models": [
            {"key": "hy_mt2_30b", "enabled": True, "runtime_verified": True}
        ]}

    state["_request"] = fake_request
    state["_gpu_preflight"](["hy_mt2_30b"])
    assert [(method, path) for method, path, _ in requested] == [
        ("GET", "/health"), ("GET", "/v1/models")
    ]
    assert requested[1][2]["authenticated"] is True


@pytest.mark.parametrize("cid,reference,flag", [
    ("post-translation", "submitted_single", "RUN_SINGLE_MODEL_POST"),
    ("post-benchmark", "submitted_multi", "RUN_MULTI_MODEL_POST"),
])
@pytest.mark.parametrize("scenario", ["skip", "preflight_error", "post_error", "invalid_response"])
def test_post_rerun_preserves_previous_job_and_get_can_poll(
    cid, reference, flag, scenario, capsys
):
    code = _code_by_id(_notebook())
    state = {"__name__": "__rerun_test__"}
    _run_helpers(code, state)
    old_id = "00000000-0000-0000-0000-000000000123"
    original = {"job_id": old_id, "status_url": "/v1/jobs/" + old_id,
                "_gateway_origin": state["API_BASE_URL"]}
    state[reference] = original
    state["_request"] = lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("Unexpected network request")
    )
    if scenario != "skip":
        state[flag] = True
        state["ACKNOWLEDGE_PAID_GPU"] = True
        if scenario == "preflight_error":
            state["_gpu_preflight"] = lambda models: (_ for _ in ()).throw(
                RuntimeError("Mock preflight error")
            )
        else:
            state["_gpu_preflight"] = lambda models: None
            if scenario == "post_error":
                state["_submit"] = lambda *a, **kw: (_ for _ in ()).throw(
                    RuntimeError("Mock uncertain POST")
                )
            else:
                state["_request"] = lambda *a, **kw: (
                    202, {"job_id": old_id, "status_url": "/invalid"}
                )
    with contextlib.redirect_stdout(io.StringIO()):
        if scenario == "skip":
            exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
        else:
            with pytest.raises((RuntimeError, ValueError)):
                exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    assert state[reference] is original
    polled = []
    state["_poll"] = lambda jid: polled.append(jid) or {
        "job_id": jid, "runs": [], "status": "completed"
    }
    state["_show_summary"] = lambda job: None
    state["RUN_SUBMITTED_JOB_POLL"] = True
    state["SUBMITTED_JOB_TO_POLL"] = "both"
    _bind_accepted_test_references(state)
    exec(compile(code["get-job"], str(NOTEBOOK), "exec"), state)
    assert polled == [old_id]
    assert old_id not in capsys.readouterr().out


def test_submission_gateway_binding_survives_secret_loader_switch(monkeypatch, capsys):
    """A job accepted on A is never polled on B and remains recoverable on A."""
    gateway_a = "https://gateway-a.example.test"
    gateway_b = "https://gateway-b.example.test"
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", gateway_a)
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", "synthetic-private-token")
    code = _code_by_id(_notebook())
    state = {"__name__": "__gateway_binding_test__"}
    _run_helpers(code, state)
    state["RUN_SINGLE_MODEL_POST"] = True
    state["ACKNOWLEDGE_PAID_GPU"] = True
    state["_gpu_preflight"] = lambda models: None
    jid = "00000000-0000-0000-0000-000000001313"
    state["_request"] = lambda method, path, **kwargs: (
        202, {"job_id": jid, "status_url": "/v1/jobs/" + jid}
    )
    exec(compile(code["post-translation"], str(NOTEBOOK), "exec"), state)
    previous = state["submitted_single"]
    assert previous["_gateway_origin"] == gateway_a

    state["RUN_SUBMITTED_JOB_POLL"] = True
    state["RUN_SINGLE_MODEL_POST"] = False
    requested = []
    state["_poll"] = lambda job_id: requested.append((state["API_BASE_URL"], job_id)) or {
        "kind": "translation", "status": "completed", "runs": [
            {"model": "hy_mt2_30b", "status": "completed",
             "translation_text": "PRIVATE RESULT", "is_mock_result": False},
        ],
    }
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", gateway_b)
    exec(compile(code["secret-loader"], str(NOTEBOOK), "exec"), state)
    exec(compile(code["get-job"], str(NOTEBOOK), "exec"), state)
    assert requested == []
    assert state["poll_failures"] == [{"reason": "gateway_mismatch"}]
    assert state["submitted_single"] is previous
    output = capsys.readouterr().out
    assert gateway_a not in output and gateway_b not in output
    assert jid not in output and "synthetic-private-token" not in output

    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", gateway_a)
    exec(compile(code["secret-loader"], str(NOTEBOOK), "exec"), state)
    exec(compile(code["get-job"], str(NOTEBOOK), "exec"), state)
    assert requested == [(gateway_a, jid)]
    assert state["poll_failures"] == []
    assert state["submitted_single"] is previous


def test_changed_payload_cannot_reuse_original_key_as_uncertain_retry():
    codes = _code_by_id(_notebook())
    state = {"__name__": "__uncertain_post_guard__"}
    _run_helpers(codes, state)
    state["ACKNOWLEDGE_PAID_GPU"] = True
    state["RUN_SINGLE_MODEL_POST"] = True
    state["_gpu_preflight"] = lambda models: None
    calls = []
    jid = "00000000-0000-0000-0000-000000001515"

    def fake_request(method, path, **kwargs):
        calls.append(method)
        return 202, {"job_id": jid, "status_url": "/v1/jobs/" + jid}

    state["_request"] = fake_request
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(codes["post-translation"], str(NOTEBOOK), "exec"), state)
    first_reference = state["submitted_single"]
    original_key = state["SINGLE_MODEL_IDEMPOTENCY_KEY"]
    state["TEXT_TO_TRANSLATE"] = "Different text, must never be silently retried"
    with pytest.raises(ValueError, match="For uncertain POST") as failure:
        exec(compile(codes["post-translation"], str(NOTEBOOK), "exec"), state)
    assert "basic settings" in str(failure.value).lower()
    assert "Different text" not in str(failure.value)
    assert len(calls) == 1
    assert state["SINGLE_MODEL_IDEMPOTENCY_KEY"] == original_key
    assert state["submitted_single"] is first_reference


def test_paid_post_guides_warn_of_kernel_only_recovery_before_submission():
    notebook = _notebook()
    ids = [c["id"] for c in notebook["cells"]]
    cells = {c["id"]: c["source"] for c in notebook["cells"]}
    assert ids.index("translation-md") < ids.index("post-translation")
    assert ids.index("post-translation") < ids.index("after-translation-guide")
    assert ids.index("post-benchmark") < ids.index("get-job") < ids.index("after-translation-guide")
    for token in ("kernel memory only", "before submitting", "LOAD_PERSISTED_IDEMPOTENCY_KEYS=True",
                  "#141-request-identity-and-persistent-keys--định-danh-và-lưu-khóa-yêu-cầu"):
        assert token in cells["translation-md"]
    for token in ("kernel-only", "#141-request-identity-and-persistent-keys--định-danh-và-lưu-khóa-yêu-cầu"):
        assert token in cells["benchmark-md"]
    assert "#09-save-an-accepted-job-uuid--lưu-uuid-job-đã-được-nhận" in cells["after-translation-guide"]
    assert "POST" in cells["after-translation-guide"]
    for token in ("SHOW_JOB_IDS=True", "no HTTP or GPU request", "Lưu kín UUID"):
        assert token in cells["saved-job-reference-guide"]
    assert "Never blindly replay" in _advanced_guide(notebook)
    assert "## 09. Save an accepted job UUID / Lưu UUID job đã được nhận" in cells["saved-job-reference-guide"]
    basic = cells["settings"]
    advanced = cells["advanced-settings"]
    assert "# BASIC" in basic and "# Advanced" in advanced
    assert "RUN_SINGLE_MODEL_POST = False" in basic
    assert "RUN_MULTI_MODEL_POST = False" in basic
    for toggle in ("LOAD_PERSISTED_IDEMPOTENCY_KEYS = False", "SHOW_JOB_IDS = False"):
        assert toggle in advanced

@pytest.mark.parametrize("kind", ("single", "multi"))
def test_paid_post_fails_closed_until_selected_persisted_key_is_loaded(kind):
    code = _code_by_id(_notebook())
    state = {"__name__": "__persisted_key_guard_test__"}
    exec(compile(code["settings"], str(NOTEBOOK), "exec"), state)
    state["LOAD_PERSISTED_IDEMPOTENCY_KEYS"] = True
    state["RUN_SINGLE_MODEL_POST"] = kind == "single"
    state["RUN_MULTI_MODEL_POST"] = kind == "multi"
    state["_request"] = lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("No HTTP should precede loading persisted keys")
    )
    cid = "post-translation" if kind == "single" else "post-benchmark"
    with pytest.raises(RuntimeError, match="persisted key"):
        exec(compile(code[cid], str(NOTEBOOK), "exec"), state)


@pytest.mark.parametrize(("cid", "flag", "multi"), (
    ("post-translation", "RUN_SINGLE_MODEL_POST", False),
    ("post-benchmark", "RUN_MULTI_MODEL_POST", True),
))
def test_failed_preflight_does_not_bind_key_but_uncertain_post_does(cid, flag, multi):
    """F1: existing identities remain protected; new ones bind only at POST boundary."""
    code = _code_by_id(_notebook())
    state = {"__name__": "__f1_preflight_boundary__"}
    _run_helpers(code, state)
    state["ACKNOWLEDGE_PAID_GPU"] = True
    state[flag] = True
    state["API_BASE_URL"] = "https://first.example.test"
    key = state["MULTI_MODEL_IDEMPOTENCY_KEY" if multi else "SINGLE_MODEL_IDEMPOTENCY_KEY"]
    preflight_calls = []
    def fail_preflight(method, path, **kwargs):
        preflight_calls.append((method, path))
        raise state["APIRequestError"](503)
    state["_request"] = fail_preflight
    with pytest.raises(state["APIRequestError"]):
        exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    assert preflight_calls == [("GET", "/health")]
    assert key not in state["_REQUEST_IDENTITIES"]

    # A failed GET can be followed by a corrected gateway without key rotation.
    state["API_BASE_URL"] = "https://second.example.test"
    calls = []
    def uncertain_post(method, path, **kwargs):
        calls.append((method, path))
        if method == "POST":
            raise state["NetworkRequestError"]("Synthetic network ambiguity")
        if path == "/health":
            return 200, {"phase": "gpu", "inference_enabled": True}
        return 200, {"models": [
            {"key": name, "enabled": True, "runtime_verified": True}
            for name in state["MODEL_KEYS"]
        ]}
    state["_request"] = uncertain_post
    with pytest.raises(state["NetworkRequestError"]):
        exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    assert [m for m, _ in calls] == ["GET", "GET", "POST"]
    bound = state["_REQUEST_IDENTITIES"][key]

    # The POST may already have been processed; do not allow another gateway/payload.
    state["API_BASE_URL"] = "https://third.example.test"
    state["_request"] = lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("A bound key must be checked before preflight")
    )
    with pytest.raises(ValueError, match="same key"):
        exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    assert state["_REQUEST_IDENTITIES"][key] == bound

    state["API_BASE_URL"] = "https://second.example.test"
    state["_request"] = uncertain_post
    # Even the same key/payload is not automatically re-sent after an uncertain POST.
    with contextlib.redirect_stdout(io.StringIO()) as output:
        exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    assert "SKIPPED repeated paid POST" in output.getvalue()
    assert [m for m, _ in calls] == ["GET", "GET", "POST"]
    assert state["_REQUEST_IDENTITIES"][key] == bound


