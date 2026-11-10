"""Notebook behavior regression tests."""
import contextlib
import io
import sys
import types
from unittest.mock import patch

import pytest
from notebook_test_support import (
    NOTEBOOK,
    _code_by_id,
    _notebook,
    _run_helpers,
)


@pytest.fixture(autouse=True)
def _synthetic_gateway_for_isolated_notebook_tests(monkeypatch):
    # A stable test-only URL; all actual HTTP is mocked in the test cases.
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://gateway.example.test")



def test_persisted_idempotency_keys_survive_settings_rerun_without_output(monkeypatch):
    values = {
        "TRANSLATION_SINGLE_IDEMPOTENCY_KEY": "test-private-recovery-single-1",
        "TRANSLATION_MULTI_IDEMPOTENCY_KEY": "test-private-recovery-multi-2",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    code = _code_by_id(_notebook())
    state = {"__name__": "__idempotency_recovery_test__"}
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        for _ in range(2):
            exec(compile(code["settings"], str(NOTEBOOK), "exec"), state)
            state["LOAD_PERSISTED_IDEMPOTENCY_KEYS"] = True
            state["RUN_SINGLE_MODEL_POST"] = True
            state["RUN_MULTI_MODEL_POST"] = True
            exec(compile(code["secret-loader"], str(NOTEBOOK), "exec"), state)
            assert state["SINGLE_MODEL_IDEMPOTENCY_KEY"] == values[
                "TRANSLATION_SINGLE_IDEMPOTENCY_KEY"
            ]
            assert state["MULTI_MODEL_IDEMPOTENCY_KEY"] == values[
                "TRANSLATION_MULTI_IDEMPOTENCY_KEY"
            ]
    assert all(value not in output.getvalue() for value in values.values())


@pytest.mark.parametrize("platform", ("colab", "kaggle"))
def test_persisted_keys_load_from_private_platform_secrets(monkeypatch, platform):
    values = {
        "TRANSLATION_GATEWAY_BASE_URL": "https://private-gateway.example.test",
        "TRANSLATION_API_BEARER_TOKEN": "example-private-token",
        "TRANSLATION_SINGLE_IDEMPOTENCY_KEY": "example-single-key-1",
        "TRANSLATION_MULTI_IDEMPOTENCY_KEY": "example-multi-key-2",
    }
    requested = []

    def fake_get(name):
        requested.append(name)
        return values[name]

    for key in values:
        monkeypatch.delenv(key, raising=False)
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
    state = {"__name__": "__private_platform_recovery__"}
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exec(compile(code["settings"], str(NOTEBOOK), "exec"), state)
        state["LOAD_FROM_COLAB_SECRETS"] = platform == "colab"
        state["LOAD_FROM_KAGGLE_SECRETS"] = platform == "kaggle"
        state["LOAD_PERSISTED_IDEMPOTENCY_KEYS"] = True
        state["RUN_SINGLE_MODEL_POST"] = True
        state["RUN_MULTI_MODEL_POST"] = True
        exec(compile(code["secret-loader"], str(NOTEBOOK), "exec"), state)
    assert set(requested) == set(values)
    assert state["SINGLE_MODEL_IDEMPOTENCY_KEY"] == values[
        "TRANSLATION_SINGLE_IDEMPOTENCY_KEY"
    ]
    assert state["MULTI_MODEL_IDEMPOTENCY_KEY"] == values[
        "TRANSLATION_MULTI_IDEMPOTENCY_KEY"
    ]
    assert all(value not in output.getvalue() for value in values.values())


def test_second_translation_rotates_key_without_restart_or_extra_preflight(capsys):
    """A confirmed prior job and new text use a new idempotency key in the same kernel."""
    codes = _code_by_id(_notebook())
    state = {"__name__": "__second_translation__"}
    _run_helpers(codes, state)
    state["ACKNOWLEDGE_PAID_GPU"] = True
    state["RUN_SINGLE_MODEL_POST"] = True
    checks = []
    state["_gpu_preflight"] = lambda models: checks.append(tuple(models))
    posts = []

    def fake_request(method, path, *, payload=None, authenticated=False, idempotency_key=None):
        assert method == "POST" and authenticated
        assert path == "/v1/jobs/translations"
        posts.append((idempotency_key, payload.copy()))
        jid = f"00000000-0000-0000-0000-{len(posts):012d}"
        return 202, {"job_id": jid, "status_url": "/v1/jobs/" + jid}

    state["_request"] = fake_request
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(codes["post-translation"], str(NOTEBOOK), "exec"), state)
    original_ref = state["submitted_single"]
    first_key = posts[0][0]

    text_line = 'TEXT_TO_TRANSLATE = "The little fox crossed the wooden bridge at sunrise."'
    assert text_line in codes["settings"]
    new_settings = codes["settings"].replace(
        text_line, 'TEXT_TO_TRANSLATE = "A second, distinct public sentence."'
    ).replace('NEW_SINGLE_REQUEST_ACTION = ""',
              'NEW_SINGLE_REQUEST_ACTION = "second-translation"')
    old_multi = state["MULTI_MODEL_IDEMPOTENCY_KEY"]
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(new_settings, str(NOTEBOOK), "exec"), state)
    assert state["submitted_single"] is original_ref
    second_key = state["SINGLE_MODEL_IDEMPOTENCY_KEY"]
    assert second_key != first_key
    assert state["MULTI_MODEL_IDEMPOTENCY_KEY"] == old_multi
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(new_settings, str(NOTEBOOK), "exec"), state)
    assert state["SINGLE_MODEL_IDEMPOTENCY_KEY"] == second_key
    assert state["_PREVIOUS_REQUEST_KEYS"]["single"][-1] == first_key
    state["ACKNOWLEDGE_PAID_GPU"] = True
    state["RUN_SINGLE_MODEL_POST"] = True
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(codes["post-translation"], str(NOTEBOOK), "exec"), state)
    assert len(posts) == 2
    assert posts[0][0] == first_key and posts[1][0] == second_key
    assert posts[0][1]["text"] != posts[1][1]["text"]
    assert len(checks) == 2
    assert state["submitted_single"]["job_id"] != original_ref["job_id"]
    assert "private" not in capsys.readouterr().out.lower()


@pytest.mark.parametrize(("label_name", "key_name", "kind"), [
    ("NEW_SINGLE_REQUEST_ACTION", "SINGLE_MODEL_IDEMPOTENCY_KEY", "single"),
    ("NEW_BENCHMARK_REQUEST_ACTION", "MULTI_MODEL_IDEMPOTENCY_KEY", "benchmark"),
])
def test_action_label_history_restores_key_without_http(
    label_name, key_name, kind, capsys
):
    """F-01: 2 -> 2 -> 3 -> 2 must restore A, never create C."""
    code = _code_by_id(_notebook())
    state = {"__name__": "__f01_label_history__"}
    settings = code["settings"]
    other_name = ("MULTI_MODEL_IDEMPOTENCY_KEY" if kind == "single"
                  else "SINGLE_MODEL_IDEMPOTENCY_KEY")
    calls = []
    with patch("urllib.request.OpenerDirector.open",
               side_effect=lambda *a, **kw: calls.append(1)):
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(settings, str(NOTEBOOK), "exec"), state)
        base_key = state[key_name]
        other_key = state[other_name]
        def run(label):
            altered = settings.replace(
                label_name + ' = ""', label_name + ' = "' + label + '"'
            )
            with contextlib.redirect_stdout(io.StringIO()):
                exec(compile(altered, str(NOTEBOOK), "exec"), state)
            return state[key_name]
        key_a = run("2")
        assert key_a != base_key
        assert run("2") == key_a
        key_b = run("3")
        assert key_b != key_a
        assert run("2") == key_a
        assert run("3") == key_b
        assert state[other_name] == other_key
        assert state["_ACTION_KEYS"][kind] == {"2": key_a, "3": key_b}
        assert state["_PREVIOUS_REQUEST_KEYS"][kind] == [
            base_key, key_a, key_b,
        ]
        assert run("3") == key_b
        assert state["_PREVIOUS_REQUEST_KEYS"][kind] == [
            base_key, key_a, key_b,
        ]
    assert not calls
    assert all(k not in capsys.readouterr().out for k in (key_a, key_b, base_key))


@pytest.mark.parametrize("platform", ("environment", "colab", "kaggle"))
@pytest.mark.parametrize("kind", ("single", "multi"))
def test_only_selected_persisted_key_is_required_and_loaded(monkeypatch, platform, kind):
    values = {
        "TRANSLATION_GATEWAY_BASE_URL": "https://private.example.test",
        "TRANSLATION_API_BEARER_TOKEN": "private-test-token",
        "TRANSLATION_SINGLE_IDEMPOTENCY_KEY": "private-single-unique",
        "TRANSLATION_MULTI_IDEMPOTENCY_KEY": "private-multi-unique",
    }
    selected = ("TRANSLATION_SINGLE_IDEMPOTENCY_KEY" if kind == "single"
                else "TRANSLATION_MULTI_IDEMPOTENCY_KEY")
    unselected = ("TRANSLATION_MULTI_IDEMPOTENCY_KEY" if kind == "single"
                  else "TRANSLATION_SINGLE_IDEMPOTENCY_KEY")
    requested = []
    for name in values:
        monkeypatch.delenv(name, raising=False)
    if platform == "environment":
        for name in ("TRANSLATION_GATEWAY_BASE_URL", "TRANSLATION_API_BEARER_TOKEN", selected):
            monkeypatch.setenv(name, values[name])
    else:
        def get_secret(name):
            requested.append(name)
            if name == unselected:
                raise AssertionError("Unused key must never be requested")
            return values[name]
        if platform == "colab":
            google = types.ModuleType("google")
            colab = types.ModuleType("google.colab")
            colab.userdata = types.SimpleNamespace(get=get_secret)
            google.colab = colab
            monkeypatch.setitem(sys.modules, "google", google)
            monkeypatch.setitem(sys.modules, "google.colab", colab)
        else:
            kaggle = types.ModuleType("kaggle_secrets")
            kaggle.UserSecretsClient = lambda: types.SimpleNamespace(get_secret=get_secret)
            monkeypatch.setitem(sys.modules, "kaggle_secrets", kaggle)
    code = _code_by_id(_notebook())
    state = {"__name__": "__selective_persisted_key_test__"}
    with contextlib.redirect_stdout(io.StringIO()) as captured:
        exec(compile(code["settings"], str(NOTEBOOK), "exec"), state)
        state["LOAD_PERSISTED_IDEMPOTENCY_KEYS"] = True
        state["RUN_SINGLE_MODEL_POST"] = kind == "single"
        state["RUN_MULTI_MODEL_POST"] = kind == "multi"
        state["LOAD_FROM_COLAB_SECRETS"] = platform == "colab"
        state["LOAD_FROM_KAGGLE_SECRETS"] = platform == "kaggle"
        other_name = "MULTI_MODEL_IDEMPOTENCY_KEY" if kind == "single" else "SINGLE_MODEL_IDEMPOTENCY_KEY"
        old_other = state[other_name]
        exec(compile(code["secret-loader"], str(NOTEBOOK), "exec"), state)
    assert state["SINGLE_MODEL_IDEMPOTENCY_KEY" if kind == "single" else "MULTI_MODEL_IDEMPOTENCY_KEY"] == values[selected]
    assert state[other_name] == old_other
    assert state["_LOADED_PERSISTED_KEYS"] == {kind}
    assert unselected not in requested
    assert all(value not in captured.getvalue() for value in values.values())


@pytest.mark.parametrize(
    ("kind", "cid", "flag", "label", "path", "key_name"),
    (
        ("single", "post-translation", "RUN_SINGLE_MODEL_POST",
         "NEW_SINGLE_REQUEST_ACTION", "/v1/jobs/translations", "SINGLE_MODEL_IDEMPOTENCY_KEY"),
        ("multi", "post-benchmark", "RUN_MULTI_MODEL_POST",
         "NEW_BENCHMARK_REQUEST_ACTION", "/v1/jobs/benchmarks", "MULTI_MODEL_IDEMPOTENCY_KEY"),
    ),
)
def test_accepted_submission_history_restores_first_uuid_after_second_request(
    monkeypatch, kind, cid, flag, label, path, key_name,
):
    """Actual Jupyter cells: A -> B -> restore A -> GET, without a third POST."""
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://gateway.example.test")
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", "secret-never-in-output")
    raw = {cell["id"]: cell["source"] for cell in _notebook()["cells"]
           if cell["cell_type"] == "code"}
    state = {"__name__": "__accepted_submission_history_workflow__"}
    def run(cell_id, override=None):
        exec(compile(override if override is not None else raw[cell_id],
                     str(NOTEBOOK), "exec"), state)
    first_text = 'TEXT_TO_TRANSLATE = "The little fox crossed the wooden bridge at sunrise."'
    second_text = 'TEXT_TO_TRANSLATE = "A second synthetic sentence to translate."'
    assert first_text in raw["settings"]
    basic = raw["settings"].replace(
        "RUN_SUBMITTED_JOB_POLL = False", "RUN_SUBMITTED_JOB_POLL = True")
    basic = basic.replace("ACKNOWLEDGE_PAID_GPU = False", "ACKNOWLEDGE_PAID_GPU = True")
    if kind == "single":
        basic = basic.replace("RUN_SINGLE_MODEL_POST = False", "RUN_SINGLE_MODEL_POST = True")
    advanced = raw["advanced-settings"]
    if kind == "multi":
        basic = basic.replace("RUN_MULTI_MODEL_POST = False", "RUN_MULTI_MODEL_POST = True")
        basic = basic.replace('SUBMITTED_JOB_TO_POLL = "single"',
                              'SUBMITTED_JOB_TO_POLL = "multi"')
    first_advanced = advanced
    second_advanced = advanced
    first_basic = basic.replace(label + ' = ""', label + ' = "first"')
    second_basic = first_basic.replace(first_text, second_text)
    second_basic = second_basic.replace(label + ' = "first"', label + ' = "second"')
    events = []
    one = "00000000-0000-0000-0000-000000005101"
    two = "00000000-0000-0000-0000-000000005102"
    def fake_request(method, endpoint, **kwargs):
        if method == "POST":
            assert endpoint == path
            number = len([event for event in events if event[0] == "POST"]) + 1
            assert number <= 2, "History retrieval must never submit a third paid POST"
            events.append(("POST", endpoint, kwargs["idempotency_key"]))
            job_id = one if number == 1 else two
            return 202, {"job_id": job_id, "status_url": "/v1/jobs/" + job_id}
        assert method == "GET" and endpoint.startswith("/v1/jobs/")
        events.append(("GET", endpoint))
        return 200, {
            "job_id": endpoint.rsplit("/", 1)[-1], "status": "completed",
            "kind": "benchmark" if kind == "multi" else "translation",
            "runs": [{"model": "hy_mt2_30b", "status": "completed",
                      "attempt_no": 1, "is_mock_result": True,
                      "translation_text": "[MOCK ONLY]"}],
        }
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        run("request-key-internals")
        run("settings", first_basic)
        run("advanced-settings", first_advanced)
        for helper in ("secret-loader", "http-client", "validation-payload",
                       "submit-preflight", "poll-summary"):
            run(helper)
        state["_gpu_preflight"] = lambda selected: None
        state["_request"] = fake_request

        run(cid)
        key_a = state[key_name]
        assert state["submitted_" + kind]["job_id"] == one
        assert len(state["_SUBMISSION_HISTORY"][kind]) == 1

        run("settings", second_basic)
        run("advanced-settings", second_advanced)
        run(cid)
        key_b = state[key_name]
        assert key_b != key_a
        assert state["submitted_" + kind]["job_id"] == two
        assert len(state["_SUBMISSION_HISTORY"][kind]) == 2

        # The next action has not been submitted: it must not poll B.
        third_basic = first_basic.replace(first_text, 'TEXT_TO_TRANSLATE = "Unsent request."')
        third_basic = third_basic.replace(label + ' = "first"', label + ' = "third"')
        third_advanced = advanced
        run("settings", third_basic)
        run("advanced-settings", third_advanced)
        selected, errors = state["_select_submitted_jobs"]()
        assert selected == [] and errors == [{"reason": "request_mismatch"}]

        # Restore A with both paid POST flags off; GET and explicit reveal work.
        first_get_only = first_basic.replace("RUN_SINGLE_MODEL_POST = True",
                                       "RUN_SINGLE_MODEL_POST = False")
        first_get_only = first_get_only.replace("RUN_MULTI_MODEL_POST = True", "RUN_MULTI_MODEL_POST = False")
        a_advanced = first_advanced
        a_advanced = a_advanced.replace("SHOW_JOB_IDS = False", "SHOW_JOB_IDS = True")
        run("settings", first_get_only)
        run("advanced-settings", a_advanced)
        assert state[key_name] == key_a
        assert state["RUN_SINGLE_MODEL_POST"] is False
        assert state["RUN_MULTI_MODEL_POST"] is False
        selected, errors = state["_select_submitted_jobs"]()
        assert selected == [one] and errors == []
        run("get-job")
        assert state["job_results"][0]["job_id"] == one
        run("show-saved-job-id")

        # Switching back to B also remains possible without a POST.
        second_get_only = first_get_only.replace(first_text, second_text)
        second_get_only = second_get_only.replace(label + ' = "first"', label + ' = "second"')
        run("settings", second_get_only)
        run("advanced-settings", a_advanced.replace(
            label + ' = "first"', label + ' = "second"'))
        assert state[key_name] == key_b
        run("get-job")
        assert state["job_results"][0]["job_id"] == two

    assert [event[0] for event in events] == ["POST", "POST", "GET", "GET"]
    assert one in output.getvalue()  # Only because SHOW_JOB_IDS=True was explicit.
    assert two not in output.getvalue()
    assert "secret-never-in-output" not in output.getvalue()
    history = state["_SUBMISSION_HISTORY"][kind]
    assert all(set(entry) == {
        "job_id", "_gateway_origin", "_request_fingerprint",
    } for entry in history.values())
    assert all("text" not in entry and "token" not in entry
               for entry in history.values())


