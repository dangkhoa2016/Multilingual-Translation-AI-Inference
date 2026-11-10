"""Notebook behavior regression tests."""
import contextlib
import io
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



@pytest.mark.parametrize("single,multi", [
    ("", "valid-multi"),
    ("reused-key", "reused-key"),
    ("x" * 201, "valid-multi"),
])
def test_invalid_persisted_idempotency_keys_are_rejected(monkeypatch, single, multi):
    monkeypatch.setenv("TRANSLATION_SINGLE_IDEMPOTENCY_KEY", single)
    monkeypatch.setenv("TRANSLATION_MULTI_IDEMPOTENCY_KEY", multi)
    code = _code_by_id(_notebook())
    state = {"__name__": "__invalid_private_idempotency__"}
    exec(compile(code["settings"], str(NOTEBOOK), "exec"), state)
    state["LOAD_PERSISTED_IDEMPOTENCY_KEYS"] = True
    state["RUN_SINGLE_MODEL_POST"] = True
    state["RUN_MULTI_MODEL_POST"] = True
    with pytest.raises(ValueError, match="(Missing or invalid persisted key|two distinct persistent)"):
        exec(compile(code["secret-loader"], str(NOTEBOOK), "exec"), state)


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_dry_run_accepts_one_to_four_selected_models_without_http(count):
    code = _code_by_id(_notebook())
    state = {"__name__": "__count_aware_offline_demo__"}
    _run_helpers(code, state)
    state["MULTI_MODEL_KEYS"] = list(state["MODEL_KEYS"])[:count]
    with (
        patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("HTTP not allowed")),
        contextlib.redirect_stdout(io.StringIO()),
    ):
        exec(compile(code["dry-run"], str(NOTEBOOK), "exec"), state)
    assert state["multi_payload"]["models"] == list(state["MODEL_KEYS"])[:count]


@pytest.mark.parametrize("invalid", [
    ["hy_mt2_30b", "hy_mt2_30b"],
    ["hy_mt2_30b", "unknown-model"],
    [],
])
def test_dry_run_rejects_invalid_model_selection_without_http(invalid):
    code = _code_by_id(_notebook())
    state = {"__name__": "__invalid_multimodel_demo__"}
    _run_helpers(code, state)
    state["MULTI_MODEL_KEYS"] = invalid
    with patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("HTTP not allowed")):
        with pytest.raises(ValueError, match="Choose between|duplicate"):
            exec(compile(code["dry-run"], str(NOTEBOOK), "exec"), state)


def test_changed_payload_same_key_fails_locally_before_http():
    code = _code_by_id(_notebook())
    state = {"__name__": "__payload_guard_test__"}
    _run_helpers(code, state)
    key = state["MULTI_MODEL_IDEMPOTENCY_KEY"]
    original = state["_payload"](multi_model=True)
    state["_check_request_identity"]("/v1/jobs/benchmarks", original, key)
    state["MULTI_MODEL_KEYS"] = list(state["MODEL_KEYS"])[:3]
    state["RUN_MULTI_MODEL_POST"] = True
    state["ACKNOWLEDGE_PAID_GPU"] = True

    def no_network(*args, **kwargs):
        raise AssertionError("Payload drift must be caught before preflight HTTP")

    state["_request"] = no_network
    with pytest.raises(ValueError, match="Payload changed under the same key"):
        exec(compile(code["post-benchmark"], str(NOTEBOOK), "exec"), state)

    # The guard must remain present even after rerunning settings.
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(code["settings"], str(NOTEBOOK), "exec"), state)
    assert state["MULTI_MODEL_IDEMPOTENCY_KEY"] == key
    assert state["_REQUEST_IDENTITIES"][key]
    changed = {**original, "models": list(state["MODEL_KEYS"])[:3]}
    with pytest.raises(ValueError, match="Payload changed"):
        state["_check_request_identity"]("/v1/jobs/benchmarks", changed, key)
    assert state["_REQUEST_IDENTITIES"][key]


def test_idempotency_request_identity_reused_only_for_same_endpoint_and_payload():
    code = _code_by_id(_notebook())
    state = {"__name__": "__idempotency_paths__"}
    _run_helpers(code, state)
    payload = state["_payload"](multi_model=False)
    key = state["SINGLE_MODEL_IDEMPOTENCY_KEY"]
    state["_check_request_identity"]("/v1/jobs/translations", payload, key)
    state["_check_request_identity"]("/v1/jobs/translations", payload, key)
    with pytest.raises(ValueError, match="Payload changed"):
        state["_check_request_identity"]("/v1/jobs/benchmarks", payload, key)


@pytest.mark.parametrize("cid,reference,flag", [
    ("post-translation", "submitted_single", "RUN_SINGLE_MODEL_POST"),
    ("post-benchmark", "submitted_multi", "RUN_MULTI_MODEL_POST"),
])
def test_valid_new_submission_replaces_previous_reference(cid, reference, flag):
    code = _code_by_id(_notebook())
    state = {"__name__": "__new_submission_test__"}
    _run_helpers(code, state)
    state[reference] = {"job_id": "00000000-0000-0000-0000-000000000234"}
    new_id = "00000000-0000-0000-0000-000000000235"
    state[flag] = True
    state["ACKNOWLEDGE_PAID_GPU"] = True
    state["_gpu_preflight"] = lambda models: None
    def fake_request(method, path, **kwargs):
        assert method == "POST"
        return 202, {"job_id": new_id, "status_url": "/v1/jobs/" + new_id}
    state["_request"] = fake_request
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    assert state[reference]["job_id"] == new_id


def test_only_selected_job_translation_is_revealed(capsys):
    """Previously accepted private benchmark must not leak with a new public single job."""
    code = _code_by_id(_notebook())
    state = {"__name__": "__selected_job_privacy_test__"}
    _run_helpers(code, state)
    state["submitted_single"] = {
        "job_id": "00000000-0000-0000-0000-000000001211",
        "_gateway_origin": state["API_BASE_URL"],
    }
    state["submitted_multi"] = {
        "job_id": "00000000-0000-0000-0000-000000001212",
        "_gateway_origin": state["API_BASE_URL"],
    }
    state["RUN_SUBMITTED_JOB_POLL"] = True
    state["SHOW_TRANSLATIONS"] = True  # Explicitly safe only for new public text.
    assert state["SUBMITTED_JOB_TO_POLL"] == "single"
    requested = []

    def fake_poll(jid):
        requested.append(jid)
        return {
            "job_id": jid, "status": "completed", "kind": "translation",
            "runs": [{
                "model": "hy_mt2_30b", "status": "completed",
                "translation_text": (
                    "NEW PUBLIC TEXT" if jid.endswith("1211") else "OLD PRIVATE TEXT"
                ),
                "is_mock_result": False,
            }],
        }

    state["_poll"] = fake_poll
    _bind_accepted_test_references(state)
    exec(compile(code["get-job"], str(NOTEBOOK), "exec"), state)
    out = capsys.readouterr().out
    assert requested == [state["submitted_single"]["job_id"]]
    assert "NEW PUBLIC TEXT" in out and "OLD PRIVATE TEXT" not in out
    assert state["submitted_multi"]["job_id"].endswith("1212")

    state["SUBMITTED_JOB_TO_POLL"] = "multi"  # Explicitly select previous job.
    state["SHOW_TRANSLATIONS"] = False  # Review status without exposing old text.
    exec(compile(code["get-job"], str(NOTEBOOK), "exec"), state)
    out = capsys.readouterr().out
    assert requested[-1] == state["submitted_multi"]["job_id"]
    assert "OLD PRIVATE TEXT" not in out


def test_progress_masks_untrusted_model_and_status_strings(capsys):
    code = _code_by_id(_notebook())
    state = {"__name__": "__progress_safe_labels__"}
    _run_helpers(code, state)
    state["_request"] = lambda *args, **kwargs: (
        200, {"job_id": "00000000-0000-0000-0000-000000008885", "status": "completed", "runs": [
            {"model": "https://private.example/secret-token", "status": "completed"}
        ]}
    )
    state["_poll"]("00000000-0000-0000-0000-000000008885", timeout_seconds=5)
    output = capsys.readouterr().out
    assert "unknown_model" in output
    assert "private.example" not in output and "secret-token" not in output


def test_job_polling_keeps_waiting_when_one_model_is_uncertain_and_another_runs():
    """The summarized job status must not be a reason to stop polling early."""
    codes = _code_by_id(_notebook())
    state = {"__name__": "__mixed_model_poll__"}
    _run_helpers(codes, state)
    state["POLL_INTERVAL_SECONDS"] = 0
    requests = []
    def response(method, path, **kwargs):
        requests.append(path)
        second_status = "running" if len(requests) == 1 else "completed"
        return 200, {"job_id": path.rsplit("/", 1)[-1], "status": "execution_uncertain", "runs": [
            {"model": "hy_mt2_30b", "attempt_no": 1, "status": "execution_uncertain"},
            {"model": "index_35b", "attempt_no": 1, "status": second_status},
        ]}
    state["_request"] = response
    with contextlib.redirect_stdout(io.StringIO()):
        result = state["_poll"]("00000000-0000-0000-0000-000000001616", timeout_seconds=10)
    assert len(requests) == 2
    assert result["status"] == "execution_uncertain"
    assert result["runs"][1]["status"] == "completed"


@pytest.mark.parametrize("previous_single", [False, True])
def test_benchmark_documented_selector_polls_only_multi_job_without_extra_post(
    previous_single
):
    """Reproduce the reviewer F02 workflow with and without an old single job."""
    notebook = _notebook()
    guide = next(c["source"] for c in notebook["cells"] if c["id"] == "benchmark-md")
    assert 'SUBMITTED_JOB_TO_POLL="multi"' in guide
    assert "RUN_SUBMITTED_JOB_POLL=True" in guide

    codes = _code_by_id(notebook)
    state = {"__name__": "__benchmark_selected_job__"}
    _run_helpers(codes, state)
    previous = "00000000-0000-0000-0000-000000000777"
    if previous_single:
        state["submitted_single"] = {"job_id": previous,
                                      "_gateway_origin": state["API_BASE_URL"]}
    multi_id = "00000000-0000-0000-0000-000000000888"
    configure = codes["settings"]
    for old, new in (
        ('SUBMITTED_JOB_TO_POLL = "single"', 'SUBMITTED_JOB_TO_POLL = "multi"'),
        ("RUN_SUBMITTED_JOB_POLL = False", "RUN_SUBMITTED_JOB_POLL = True"),
        ("RUN_MULTI_MODEL_POST = False", "RUN_MULTI_MODEL_POST = True"),
        ("ACKNOWLEDGE_PAID_GPU = False", "ACKNOWLEDGE_PAID_GPU = True"),
    ):
        assert old in configure
        configure = configure.replace(old, new)
    exec(compile(configure, str(NOTEBOOK), "exec"), state)
    assert state["SUBMITTED_JOB_TO_POLL"] == "multi"
    state["_gpu_preflight"] = lambda models: None
    methods = []

    def fake_post(method, path, **kwargs):
        methods.append(method)
        assert method == "POST"
        assert path == "/v1/jobs/benchmarks"
        return 202, {"job_id": multi_id, "status_url": "/v1/jobs/" + multi_id}

    state["_request"] = fake_post
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(codes["post-benchmark"], str(NOTEBOOK), "exec"), state)
    assert state["submitted_multi"]["job_id"] == multi_id
    selected = []
    state["_poll"] = lambda jid: selected.append(jid) or {
        "kind": "benchmark", "status": "completed", "runs": [],
    }
    state["_show_summary"] = lambda job: None
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(codes["get-job"], str(NOTEBOOK), "exec"), state)
    assert selected == [multi_id]
    assert methods == ["POST"]  # GET polling code didn't submit a new job.
    if previous_single:
        assert state["submitted_single"]["job_id"] == previous
    else:
        assert state.get("submitted_single") is None


@pytest.mark.parametrize(("kind", "label_name", "key_name", "path", "multi"), [
    ("single", "NEW_SINGLE_REQUEST_ACTION", "SINGLE_MODEL_IDEMPOTENCY_KEY",
     "/v1/jobs/translations", False),
    ("benchmark", "NEW_BENCHMARK_REQUEST_ACTION", "MULTI_MODEL_IDEMPOTENCY_KEY",
     "/v1/jobs/benchmarks", True),
])
def test_revisit_label_with_changed_payload_cannot_submit(
    kind, label_name, key_name, path, multi
):
    """Restored key must keep its original request identity and block paid work."""
    code = _code_by_id(_notebook())
    state = {"__name__": "__f01_payload_mismatch__"}
    _run_helpers(code, state)
    settings = code["settings"]
    first = settings.replace(label_name + ' = ""', label_name + ' = "2"')
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(first, str(NOTEBOOK), "exec"), state)
    key_a = state[key_name]
    original_payload = state["_payload"](multi_model=multi)
    state["_check_request_identity"](path, original_payload, key_a)

    second = settings.replace(label_name + ' = ""', label_name + ' = "3"')
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(second, str(NOTEBOOK), "exec"), state)
    assert state[key_name] != key_a
    changed = first.replace(
        'TEXT_TO_TRANSLATE = "The little fox crossed the wooden bridge at sunrise."',
        'TEXT_TO_TRANSLATE = "A different, synthetic translation request."',
    )
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(changed, str(NOTEBOOK), "exec"), state)
    assert state[key_name] == key_a

    state["ACKNOWLEDGE_PAID_GPU"] = True
    state["RUN_MULTI_MODEL_POST" if multi else "RUN_SINGLE_MODEL_POST"] = True
    state["_request"] = lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("No preflight GET or billable POST is permitted")
    )
    cid = "post-benchmark" if multi else "post-translation"
    with pytest.raises(ValueError, match="Payload changed under the same key"):
        exec(compile(code[cid], str(NOTEBOOK), "exec"), state)


