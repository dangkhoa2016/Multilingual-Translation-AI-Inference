"""Notebook behavior regression tests."""
import contextlib
import io
import os
import sys
import types
from unittest.mock import patch

import pytest
from notebook_test_support import (
    NOTEBOOK,
    _advanced_guide,
    _code_by_id,
    _code_cells,
    _notebook,
    _run_helpers,
)


@pytest.fixture(autouse=True)
def _synthetic_gateway_for_isolated_notebook_tests(monkeypatch):
    # A stable test-only URL; all actual HTTP is mocked in the test cases.
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://gateway.example.test")


@pytest.mark.parametrize("platform", ("colab", "kaggle"))
@pytest.mark.parametrize("kind", ("single", "multi"))
@pytest.mark.parametrize("failed_secret", ("gateway", "token", "job_id", "key"))
def test_failed_secret_reload_blocks_old_gateway_and_preserves_accepted_jobs(
    monkeypatch, platform, kind, failed_secret
):
    """A failed switch A -> B must never send new input using A's credentials."""
    import json
    from urllib.parse import urlsplit

    gateway_a, gateway_b = "https://gateway-a.example.test", "https://gateway-b.example.test"
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", gateway_a)
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", "synthetic-token-a")
    code = _code_by_id(_notebook())
    state = {"__name__": "__atomic_secret_reload__"}
    _run_helpers(code, state)
    state.update(ACKNOWLEDGE_PAID_GPU=True)
    state["RUN_SINGLE_MODEL_POST" if kind == "single" else "RUN_MULTI_MODEL_POST"] = True
    cid = "post-translation" if kind == "single" else "post-benchmark"
    calls = []
    job_a, job_b = "00000000-0000-0000-0000-000000007001", "00000000-0000-0000-0000-000000007002"

    class Response(io.BytesIO):
        def __init__(self, status, body):
            super().__init__(json.dumps(body).encode())
            self.status = status

    def open_request(request, timeout):
        parsed = urlsplit(request.full_url)
        origin = "https://" + parsed.netloc
        calls.append((request.method, origin))
        if parsed.path == "/health":
            return Response(200, {"phase": "gpu", "inference_enabled": True})
        assert request.get_header("Authorization") == (
            "Bearer synthetic-token-a" if origin == gateway_a else "Bearer synthetic-token-b"
        )
        if parsed.path == "/v1/models":
            return Response(200, {"models": [
                {"key": key, "enabled": True, "runtime_verified": True} for key in state["MODEL_KEYS"]
            ]})
        assert request.method == "POST"
        job_id = job_a if origin == gateway_a else job_b
        return Response(202, {"job_id": job_id, "status_url": "/v1/jobs/" + job_id})

    monkeypatch.setattr(state["_OPENER"], "open", open_request)
    exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    old_submission = state["submitted_" + kind]
    old_history = dict(state["_SUBMISSION_HISTORY"][kind])
    state["TEXT_TO_TRANSLATE"] = "New input intended only for gateway B."
    key_name = "TRANSLATION_SINGLE_IDEMPOTENCY_KEY" if kind == "single" else "TRANSLATION_MULTI_IDEMPOTENCY_KEY"
    values = {"TRANSLATION_GATEWAY_BASE_URL": gateway_b,
              "TRANSLATION_API_BEARER_TOKEN": "synthetic-token-b",
              "TRANSLATION_EXISTING_JOB_ID": job_b, key_name: "synthetic-persisted-key-b"}
    failing_name = {"gateway": "TRANSLATION_GATEWAY_BASE_URL", "token": "TRANSLATION_API_BEARER_TOKEN",
                    "job_id": "TRANSLATION_EXISTING_JOB_ID", "key": key_name}[failed_secret]
    fail = True

    def secret(name):
        if fail and name == failing_name:
            raise RuntimeError("Synthetic missing Secrets permission")
        return values[name]

    if platform == "colab":
        google, colab = types.ModuleType("google"), types.ModuleType("google.colab")
        colab.userdata = types.SimpleNamespace(get=secret)
        google.colab = colab
        monkeypatch.setitem(sys.modules, "google", google)
        monkeypatch.setitem(sys.modules, "google.colab", colab)
    else:
        kaggle = types.ModuleType("kaggle_secrets")
        kaggle.UserSecretsClient = lambda: types.SimpleNamespace(get_secret=secret)
        monkeypatch.setitem(sys.modules, "kaggle_secrets", kaggle)
    state["LOAD_FROM_COLAB_SECRETS"] = platform == "colab"
    state["LOAD_FROM_KAGGLE_SECRETS"] = platform == "kaggle"
    state["LOAD_EXISTING_JOB_ID_FROM_SECRETS"] = failed_secret == "job_id"
    state["LOAD_PERSISTED_IDEMPOTENCY_KEYS"] = failed_secret == "key"
    if failed_secret != "key":
        state["NEW_SINGLE_REQUEST_ACTION" if kind == "single" else "NEW_BENCHMARK_REQUEST_ACTION"] = "2"
        state["_configure_request_keys"](("single" if kind == "single" else "benchmark",))
    else:
        state["_LOADED_PERSISTED_KEYS"] = {kind}  # A stale successful load must not survive failure.

    with pytest.raises(RuntimeError, match="permission"):
        exec(compile(code["secret-loader"], str(NOTEBOOK), "exec"), state)
    before = list(calls)
    with pytest.raises((ValueError, RuntimeError)):
        state["_request"]("GET", "/health")
    with pytest.raises((ValueError, RuntimeError)):
        exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    assert calls == before
    assert state["submitted_" + kind] is old_submission
    assert state["_SUBMISSION_HISTORY"][kind] == old_history
    assert not state["_LOADED_PERSISTED_KEYS"]
    if failed_secret != "key":
        assert (os.environ["TRANSLATION_GATEWAY_BASE_URL"], os.environ["TRANSLATION_API_BEARER_TOKEN"]) == (
            gateway_a, "synthetic-token-a"
        )

    fail = False
    exec(compile(code["secret-loader"], str(NOTEBOOK), "exec"), state)
    exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    assert calls[len(before):] == [("GET", gateway_b), ("GET", gateway_b), ("POST", gateway_b)]
    assert state["submitted_" + kind]["job_id"] == job_b
    for fingerprint, record in old_history.items():
        assert state["_SUBMISSION_HISTORY"][kind][fingerprint] == record



def test_secrets_loaders_are_opt_in_and_guarded():
    notebook = _notebook()
    code = _code_by_id(notebook)
    settings = code["settings"]
    loader = code["secret-loader"]
    assert "LOAD_FROM_COLAB_SECRETS = False" in settings
    assert "LOAD_FROM_KAGGLE_SECRETS = False" in settings
    assert "SHOW_JOB_IDS = False" in settings
    assert "LOAD_EXISTING_JOB_ID_FROM_SECRETS = False" in settings
    assert "RUN_HEALTH_GET = False" in settings
    assert "RUN_MODEL_CATALOG_GET = False" in settings
    assert "RUN_SUBMITTED_JOB_POLL = False" in settings
    assert "LOAD_PERSISTED_IDEMPOTENCY_KEYS = False" in settings
    assert "ACKNOWLEDGE_PAID_GPU = False" in settings
    assert "os.environ[name]" not in settings
    assert 'if LOAD_FROM_COLAB_SECRETS and LOAD_FROM_KAGGLE_SECRETS:' in loader
    assert len(next(c["source"] for c in notebook["cells"] if c["id"] == "settings").splitlines()) <= 60
    assert "_LOADED_PERSISTED_KEYS" in loader
    ids = [cell["id"] for cell in notebook["cells"]]
    assert ids.index("settings") < ids.index("secret-loader")
    assert ids.index("secret-loader") < ids.index("get-job") < ids.index("sample-response")
    assert ids.index("privacy") < ids.index("secret-guide") < ids.index("secret-loader")
    assert "## 01. Basic settings / Cấu hình cơ bản" in next(
        cell["source"] for cell in notebook["cells"] if cell["id"] == "settings-guide"
    )
    assert "## 04. Load private Secrets / Nạp Secrets riêng tư" in next(
        cell["source"] for cell in notebook["cells"] if cell["id"] == "secret-loader-guide"
    )
    intro = next(cell["source"] for cell in notebook["cells"] if cell["id"] == "intro")
    assert "### First run" in intro
    assert "ACKNOWLEDGE_PAID_GPU=True" in intro
    assert "RUN_SINGLE_MODEL_POST=True" in intro
    advanced = _advanced_guide(notebook)
    assert "RUN_EXISTING_JOB_POLL=True" in advanced
    assert "RUN_SUBMITTED_JOB_POLL=True" in intro
    assert "SHOW_TRANSLATIONS=True" in intro


@pytest.mark.parametrize("platform", ("colab", "kaggle"))
def test_secret_providers_load_recovery_id_without_exposing_secrets(monkeypatch, platform):
    """Run the actual notebook loader using synthetic platform secret providers."""
    fake_id = "00000000-0000-0000-0000-000000000777"
    values = {
        "TRANSLATION_GATEWAY_BASE_URL": "https://private-gateway.example.test",
        "TRANSLATION_API_BEARER_TOKEN": "non-public-test-token",
        "TRANSLATION_EXISTING_JOB_ID": fake_id,
    }
    for key in values:
        monkeypatch.setenv(key, "")
    requested = []

    def fake_get(name):
        requested.append(name)
        return values[name]

    if platform == "colab":
        google = types.ModuleType("google")
        colab = types.ModuleType("google.colab")
        colab.userdata = types.SimpleNamespace(get=fake_get)
        google.colab = colab
        monkeypatch.setitem(sys.modules, "google", google)
        monkeypatch.setitem(sys.modules, "google.colab", colab)
    else:
        kaggle = types.ModuleType("kaggle_secrets")
        kaggle.UserSecretsClient = lambda: types.SimpleNamespace(get_secret=fake_get)
        monkeypatch.setitem(sys.modules, "kaggle_secrets", kaggle)

    code = _code_by_id(_notebook())
    state = {"__name__": "__safe_secret_loader_test__"}
    with contextlib.redirect_stdout(io.StringIO()) as output:
        exec(compile(code["settings"], str(NOTEBOOK), "exec"), state)
        state["LOAD_FROM_COLAB_SECRETS"] = platform == "colab"
        state["LOAD_FROM_KAGGLE_SECRETS"] = platform == "kaggle"
        state["LOAD_EXISTING_JOB_ID_FROM_SECRETS"] = True
        exec(compile(code["secret-loader"], str(NOTEBOOK), "exec"), state)

    assert set(requested) == set(values)
    assert state["API_BASE_URL"] == values["TRANSLATION_GATEWAY_BASE_URL"]
    assert state["API_TOKEN"] == values["TRANSLATION_API_BEARER_TOKEN"]
    assert state["EXISTING_JOB_ID"] == fake_id
    assert all(secret not in output.getvalue() for secret in values.values())
    assert not state["RUN_SINGLE_MODEL_POST"] and not state["RUN_MULTI_MODEL_POST"]
    # Initialize the shared GET helper, as offline Run All does, before replacing I/O.
    exec(compile(code["poll-summary"], str(NOTEBOOK), "exec"), state)
    state["RUN_EXISTING_JOB_POLL"] = True
    polled = []
    state["_poll"] = lambda jid: polled.append(jid) or {
        "job_id": jid, "runs": [], "status": "completed"
    }
    state["_show_summary"] = lambda job: None
    state["_request"] = lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("Provider recovery must stay offline")
    )
    exec(compile(code["get-job"], str(NOTEBOOK), "exec"), state)
    assert polled == [fake_id]


def test_optional_job_id_secret_requires_a_provider():
    code = _code_by_id(_notebook())
    state = {"__name__": "__job_recovery_gate_test__"}
    exec(compile(code["settings"], str(NOTEBOOK), "exec"), state)
    state["LOAD_EXISTING_JOB_ID_FROM_SECRETS"] = True
    with pytest.raises(ValueError, match="Select a secrets provider"):
        exec(compile(code["secret-loader"], str(NOTEBOOK), "exec"), state)


def test_public_health_get_can_run_without_a_bearer_token(monkeypatch):
    """Health-only mode must not force authenticated catalog or job GETs."""
    import io
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://gateway.example.test")
    monkeypatch.delenv("TRANSLATION_API_BEARER_TOKEN", raising=False)
    code = _code_by_id(_notebook())
    state = {"__name__": "__health_only_test__"}
    _run_helpers(code, state)
    state["RUN_HEALTH_GET"] = True
    paths = []

    def fake_get(request, timeout):
        assert timeout == 30
        assert request.get_header("Authorization") is None
        paths.append(request.full_url)
        reply = io.BytesIO(b'{"status":"ok","inference_enabled":false,"phase":"cpu"}')
        reply.status = 200
        return reply

    monkeypatch.setattr(state["_OPENER"], "open", fake_get)
    with contextlib.redirect_stdout(io.StringIO()):
        for cid in ("get-health", "get-models", "get-job"):
            exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    assert paths == ["https://gateway.example.test/health"]
    assert state["health_result"]["status"] == "ok"
    assert state["catalog_result"] is None
    assert state["job_results"] == []


def test_local_environment_recovery_polls_without_platform_secrets(monkeypatch):
    job_id = "00000000-0000-0000-0000-000000000567"
    monkeypatch.setenv("TRANSLATION_EXISTING_JOB_ID", job_id)
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://gateway.example.test")
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", "example-local-token")
    code = _code_by_id(_notebook())
    state = {"__name__": "__local_recovery_test__"}
    _run_helpers(code, state)
    assert state["LOAD_EXISTING_JOB_ID_FROM_SECRETS"] is False
    assert state["LOAD_FROM_COLAB_SECRETS"] is False
    assert state["LOAD_FROM_KAGGLE_SECRETS"] is False
    assert state["EXISTING_JOB_ID"] == job_id
    assert not state["RUN_SINGLE_MODEL_POST"] and not state["RUN_MULTI_MODEL_POST"]
    state["RUN_EXISTING_JOB_POLL"] = True
    polled = []
    state["_poll"] = lambda jid: polled.append(jid) or {
        "job_id": jid, "status": "completed", "runs": []
    }
    state["_show_summary"] = lambda job: None
    state["_request"] = lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("Mock recovery must not access the network")
    )
    exec(compile(code["get-job"], str(NOTEBOOK), "exec"), state)
    assert polled == [job_id]


def test_bilingual_onboarding_covers_private_secrets_and_live_polling_without_dotenv():
    notebook = _notebook()
    by_id = {cell["id"]: cell["source"] for cell in notebook["cells"]}
    guide = by_id["secret-guide"]
    for expected in (
        "Local Jupyter", "Colab", "Kaggle",
        "TRANSLATION_GATEWAY_BASE_URL", "TRANSLATION_API_BEARER_TOKEN",
        "LOAD_FROM_COLAB_SECRETS=True", "LOAD_FROM_KAGGLE_SECRETS=True",
        "LOAD_FROM_COLAB_SECRETS=False", "LOAD_FROM_KAGGLE_SECRETS=False",
        "does not auto-load", "không tự nạp", ".env",
        "authorize", "cấp quyền", "Internet",
    ):
        assert expected in guide
    intro = by_id["intro"]
    assert "RUN_SINGLE_MODEL_POST=True" in intro
    assert "RUN_SUBMITTED_JOB_POLL=True" in intro
    assert "SHOW_TRANSLATIONS=True" in intro
    assert "Tiếng Việt" in intro or "Lần đầu sử dụng" in intro
    for step in ("Basic settings", "Load private Secrets", "helpers",
                 "POST translation", "GET job"):
        assert step in intro
    assert all(anchor in intro for anchor in (
        "#08-translate-another-sentence--dịch-câu-tiếp-theo", "#14-advanced-usage-and-recovery--sử-dụng-nâng-cao-và-khôi-phục", "#09-save-an-accepted-job-uuid--lưu-uuid-job-đã-được-nhận",
    ))


@pytest.mark.parametrize("bad_token", [
    "private test token", "private\ntest", "private\rtest",
    "private\x01test", "private\u2028test",
])
@pytest.mark.parametrize("reused_kernel", [False, True])
def test_invalid_secret_loader_token_is_ignored_until_authenticated_http(
    monkeypatch, bad_token, reused_kernel
):
    """Run All offline must remain safe even with malformed env credentials."""
    import traceback

    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", bad_token)
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://private-gateway.example.test")
    codes = _code_by_id(_notebook())
    state = {"__name__": "__loader_invalid__"}
    if reused_kernel:
        _run_helpers(codes, state)
        # Simulate a prior accepted job without enabling any live flags.
        state["submitted_single"] = {"job_id": "00000000-0000-0000-0000-000000009001"}
    stdout = io.StringIO()
    with (
        patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("No HTTP")),
        contextlib.redirect_stdout(stdout),
    ):
        for source in _code_cells(_notebook()):
            exec(compile(source, str(NOTEBOOK), "exec"), state)
    assert state["API_TOKEN"] == bad_token
    assert state["job_results"] == []
    assert state["RUN_SUBMITTED_JOB_POLL"] is False
    assert (state.get("submitted_single") is not None) is reused_kernel
    assert bad_token not in stdout.getvalue()
    with patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("No HTTP")):
        with pytest.raises(ValueError, match="Invalid private Bearer token format") as exc:
            state["_request"]("GET", "/v1/models", authenticated=True)
    assert bad_token not in "".join(traceback.format_exception(exc.value))
    assert "private-gateway.example.test" not in str(exc.value)

    # Public health GET bypasses malformed Bearer tokens; authenticated POST does not.
    class FakeHealthResponse(io.BytesIO):
        status = 200

    received = []
    def fake_health_open(req, timeout):
        received.append((req.get_method(), req.get_header("Authorization")))
        return FakeHealthResponse(b'{"status": "ok"}')

    state["_OPENER"] = types.SimpleNamespace(open=fake_health_open)
    status, result = state["_request"]("GET", "/health", authenticated=False)
    assert status == 200 and result["status"] == "ok"
    assert received == [("GET", None)]
    with pytest.raises(ValueError, match="Invalid private Bearer token format"):
        state["_request"]("POST", "/v1/jobs/translations",
                          payload={"text": "demo"}, authenticated=True,
                          idempotency_key="synthetic-safe-key")
    assert received == [("GET", None)]



@pytest.mark.parametrize(("kind", "post_cell", "label", "key_name"), [
    ("single", "post-translation", "NEW_SINGLE_REQUEST_ACTION",
     "SINGLE_MODEL_IDEMPOTENCY_KEY"),
    ("multi", "post-benchmark", "NEW_BENCHMARK_REQUEST_ACTION",
     "MULTI_MODEL_IDEMPOTENCY_KEY"),
])
def test_default_blank_label_can_select_first_accepted_job(
    monkeypatch, kind, post_cell, label, key_name, capsys,
):
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://gateway.example.test")
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", "hidden-secret")
    code = _code_by_id(_notebook())
    state = {"__name__": "__blank_label_recovery__"}

    def run(cid, override=None):
        exec(compile(override if override is not None else code[cid],
                     str(NOTEBOOK), "exec"), state)

    text_a = 'TEXT_TO_TRANSLATE = "The little fox crossed the wooden bridge at sunrise."'
    text_b = 'TEXT_TO_TRANSLATE = "Second sentence for regression."'
    basic = (code["settings"].replace(
        "ACKNOWLEDGE_PAID_GPU = False", "ACKNOWLEDGE_PAID_GPU = True"
    ).replace("RUN_SUBMITTED_JOB_POLL = False", "RUN_SUBMITTED_JOB_POLL = True"))
    advanced = code["advanced-settings"]
    assert "SAVED_SUBMISSION_NUMBER = 0" in advanced
    if kind == "single":
        basic = basic.replace("RUN_SINGLE_MODEL_POST = False", "RUN_SINGLE_MODEL_POST = True")
    else:
        basic = basic.replace("RUN_MULTI_MODEL_POST = False", "RUN_MULTI_MODEL_POST = True")
        basic = basic.replace('SUBMITTED_JOB_TO_POLL = "single"',
                              'SUBMITTED_JOB_TO_POLL = "multi"')
    job_a = "00000000-0000-0000-0000-000000006101"
    job_b = "00000000-0000-0000-0000-000000006102"
    posts = []

    def fake_request(method, endpoint, **kwargs):
        assert method == "POST"
        posts.append(kwargs["idempotency_key"])
        assert len(posts) <= 2
        job_id = (job_a, job_b)[len(posts) - 1]
        return 202, {"job_id": job_id, "status_url": "/v1/jobs/" + job_id}

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        run("request-key-internals")
        run("settings", basic)
        run("advanced-settings", advanced)  # Blank action label is the original default.
        for cid in ("secret-loader", "http-client", "validation-payload",
                    "submit-preflight", "poll-summary"):
            run(cid)
        state["_gpu_preflight"] = lambda _: None
        state["_request"] = fake_request
        run(post_cell)
        key_a = state[key_name]
        assert state["submitted_" + kind]["job_id"] == job_a
        next_basic = basic.replace(text_a, text_b)
        next_basic = next_basic.replace(label + ' = ""', label + ' = "2"')
        run("settings", next_basic)
        run("advanced-settings", advanced.replace(label + ' = ""', label + ' = "2"'))
        run(post_cell)
        key_b = state[key_name]
        assert key_a != key_b
        assert state["submitted_" + kind]["job_id"] == job_b

        basic_get = basic.replace("RUN_SINGLE_MODEL_POST = True",
                                  "RUN_SINGLE_MODEL_POST = False")
        basic_get = basic_get.replace("RUN_MULTI_MODEL_POST = True", "RUN_MULTI_MODEL_POST = False")
        advanced_get = advanced
        run("settings", basic_get)
        run("advanced-settings", advanced_get)
        assert state[key_name] == key_b  # Blank means keep current, never rotate.
        assert state["_select_submitted_jobs"]() == ([], [{"reason": "request_mismatch"}])

        select_old = advanced_get.replace("SAVED_SUBMISSION_NUMBER = 0",
                                           "SAVED_SUBMISSION_NUMBER = 1")
        run("advanced-settings", select_old)
        assert state[key_name] == key_b
        assert state["_select_submitted_jobs"]() == ([job_a], [])
        state["_poll"] = lambda jid: {"job_id": jid, "runs": []}
        state["_show_summary"] = lambda _: None
        run("get-job")
        assert state["job_results"][0]["job_id"] == job_a

        run("show-saved-job-id")  # No UUID until explicit opt-in.
        state["SHOW_JOB_IDS"] = True
        run("show-saved-job-id")
        state["API_BASE_URL"] = "https://other-gateway.example.test"
        assert state["_select_submitted_jobs"]() == ([], [{"reason": "gateway_mismatch"}])
        state["API_BASE_URL"] = "https://gateway.example.test"
        state["SAVED_SUBMISSION_NUMBER"] = 3
        assert state["_select_submitted_jobs"]() == ([], [{"reason": "request_mismatch"}])
        state["SAVED_SUBMISSION_NUMBER"] = 1
        state["RUN_SINGLE_MODEL_POST"] = True
        assert state["_select_submitted_jobs"]() == ([], [{"reason": "request_mismatch"}])
    out = output.getvalue()
    assert job_a in out and job_b not in out
    assert "hidden-secret" not in out
    assert len(posts) == 2
