"""Notebook behavior regression tests."""
import contextlib
import io
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



def test_settings_actions_rotate_only_selected_kind_once_and_preserve_history():
    code = _code_by_id(_notebook())
    state = {"__name__": "__selective_keys_test__"}
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(code["settings"], str(NOTEBOOK), "exec"), state)
    single_old, multi_old = (
        state["SINGLE_MODEL_IDEMPOTENCY_KEY"], state["MULTI_MODEL_IDEMPOTENCY_KEY"]
    )
    single = code["settings"].replace(
        'NEW_SINGLE_REQUEST_ACTION = ""', 'NEW_SINGLE_REQUEST_ACTION = "second"'
    )
    with contextlib.redirect_stdout(io.StringIO()) as output:
        exec(compile(single, str(NOTEBOOK), "exec"), state)
        single_new = state["SINGLE_MODEL_IDEMPOTENCY_KEY"]
        exec(compile(single, str(NOTEBOOK), "exec"), state)
    assert single_new != single_old
    assert state["SINGLE_MODEL_IDEMPOTENCY_KEY"] == single_new
    assert state["MULTI_MODEL_IDEMPOTENCY_KEY"] == multi_old
    assert state["_PREVIOUS_REQUEST_KEYS"]["single"] == [single_old]
    assert state["_PREVIOUS_REQUEST_KEYS"]["benchmark"] == []
    assert output.getvalue().count("New single request key created") == 1
    assert single_old not in output.getvalue() and single_new not in output.getvalue()
    benchmark = code["settings"].replace(
        'NEW_BENCHMARK_REQUEST_ACTION = ""',
        'NEW_BENCHMARK_REQUEST_ACTION = "second"'
    )
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(benchmark, str(NOTEBOOK), "exec"), state)
        multi_new = state["MULTI_MODEL_IDEMPOTENCY_KEY"]
        exec(compile(benchmark, str(NOTEBOOK), "exec"), state)
    assert multi_new != multi_old
    assert state["MULTI_MODEL_IDEMPOTENCY_KEY"] == multi_new
    assert state["SINGLE_MODEL_IDEMPOTENCY_KEY"] == single_new
    assert state["_PREVIOUS_REQUEST_KEYS"]["benchmark"] == [multi_old]
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(code["settings"], str(NOTEBOOK), "exec"), state)
    assert state["SINGLE_MODEL_IDEMPOTENCY_KEY"] == single_new
    assert state["MULTI_MODEL_IDEMPOTENCY_KEY"] == multi_new



def test_new_persisted_keys_load_instead_of_rotating(monkeypatch):
    """An operator creates and privately stores fresh keys before new paid requests."""
    values = {
        "TRANSLATION_SINGLE_IDEMPOTENCY_KEY": "test-new-request-single-2026",
        "TRANSLATION_MULTI_IDEMPOTENCY_KEY": "test-new-request-multi-2026",
    }
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    code = _code_by_id(_notebook())
    state = {"__name__": "__new_persisted_request__"}
    output = io.StringIO()
    configured = code["settings"].replace(
        "LOAD_PERSISTED_IDEMPOTENCY_KEYS = False",
        "LOAD_PERSISTED_IDEMPOTENCY_KEYS = True",
    )
    with contextlib.redirect_stdout(output):
        exec(compile(configured, str(NOTEBOOK), "exec"), state)
        assert state["NEW_SINGLE_REQUEST_ACTION"] == ""
        state["RUN_SINGLE_MODEL_POST"] = True
        state["RUN_MULTI_MODEL_POST"] = True
        exec(compile(code["secret-loader"], str(NOTEBOOK), "exec"), state)
    assert state["SINGLE_MODEL_IDEMPOTENCY_KEY"] == values[
        "TRANSLATION_SINGLE_IDEMPOTENCY_KEY"
    ]
    assert state["MULTI_MODEL_IDEMPOTENCY_KEY"] == values[
        "TRANSLATION_MULTI_IDEMPOTENCY_KEY"
    ]
    assert not any(v in output.getvalue() for v in values.values())




def test_first_use_settings_are_grouped_before_advanced_and_stay_off_by_default():
    cells = _code_by_id(_notebook())
    settings = cells["settings"]
    assert settings.index("# Step 1") < settings.index("# Step 2")
    assert settings.index("# Step 2") < settings.index("# Step 3")
    assert settings.index("# Step 3") < settings.index("# Advanced")
    assert settings.index("MODEL_KEY =") < settings.index("NEW_SINGLE_REQUEST_ACTION =")
    assert "LOAD_PERSISTED_IDEMPOTENCY_KEYS = False" in next(
        c["source"] for c in _notebook()["cells"] if c["id"] == "advanced-settings")
    state = {"__name__": "__grouped_settings_test__"}
    exec(compile(settings, str(NOTEBOOK), "exec"), state)
    assert state["RUN_SINGLE_MODEL_POST"] is False
    assert state["RUN_MULTI_MODEL_POST"] is False
    assert state["RUN_SUBMITTED_JOB_POLL"] is False
    assert state["ACKNOWLEDGE_PAID_GPU"] is False




def test_unbound_legacy_submission_is_not_polled_after_gateway_change(monkeypatch):
    """A reference from an earlier notebook cannot silently acquire today's gateway."""
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://gateway-new.example.test")
    code = _code_by_id(_notebook())
    state = {"__name__": "__unbound_legacy_reference_test__"}
    _run_helpers(code, state)
    original = {"job_id": "00000000-0000-0000-0000-000000001414"}
    state["submitted_single"] = original
    state["RUN_SUBMITTED_JOB_POLL"] = True
    state["_poll"] = lambda jid: (_ for _ in ()).throw(
        AssertionError("Unbound legacy UUID was polled over wrong gateway")
    )
    exec(compile(code["get-job"], str(NOTEBOOK), "exec"), state)
    assert state["submitted_single"] is original
    assert state["job_results"] == []
    assert state["poll_failures"] == [{"reason": "gateway_mismatch"}]


def test_standalone_notebook_links_work_outside_the_repository():
    n = _notebook()
    polling = next(c["source"] for c in n["cells"] if c["id"] == "poll-md")
    for suffix in ("development.md", "development.vi.md"):
        assert ("https://github.com/dangkhoa2016/"
                "Multilingual-Translation-AI-Inference/blob/v1.0.0/docs/" + suffix) in polling
    assert "](../docs/" not in polling
    ids = [c["id"] for c in n["cells"]]
    assert ids.index("post-benchmark") < ids.index("get-job") < ids.index("saved-job-reference-guide")
    assert ids.index("show-saved-job-id") < ids.index("reset-submissions")


def test_first_run_places_settings_before_long_secrets_and_advanced_guides():
    notebook = _notebook()
    ids = [cell["id"] for cell in notebook["cells"]]
    assert ids[:4] == ["intro", "settings-guide", "request-key-internals", "settings"]
    assert ids.index("get-job") < ids.index("advanced-settings") < ids.index("http-client")
    introduction = notebook["cells"][0]["source"]
    settings_help = notebook["cells"][1]["source"]
    assert len(introduction.split()) < 700
    assert len((introduction + settings_help).split()) < 1000
    for anchor in ("#03-configure-private-secrets--thiết-lập-secrets-riêng-tư", "#14-advanced-usage-and-recovery--sử-dụng-nâng-cao-và-khôi-phục"):
        assert anchor in introduction
    advanced_help = next(c["source"] for c in notebook["cells"] if c["id"] == "advanced-settings-guide")
    assert "NEW_BENCHMARK_REQUEST_ACTION" in advanced_help
    assert "POST" in settings_help and "reconcil" in advanced_help
    assert ids.index("settings") < ids.index("secret-loader") < ids.index("post-translation")


def test_both_selection_checks_each_logical_request_independently():
    code = _code_by_id(_notebook())
    state = {"__name__": "__both_kinds_guard_test__"}
    _run_helpers(code, state)
    for kind, path, key, multi in (
        ("single", "/v1/jobs/translations", "SINGLE_MODEL_IDEMPOTENCY_KEY", False),
        ("multi", "/v1/jobs/benchmarks", "MULTI_MODEL_IDEMPOTENCY_KEY", True),
    ):
        jid = "00000000-0000-0000-0000-000000009" + ("201" if kind == "single" else "202")
        state["submitted_" + kind] = {
            "job_id": jid, "_gateway_origin": state["API_BASE_URL"],
            "_request_fingerprint": state["_request_fingerprint"](
                path, state["_payload"](multi_model=multi), state[key]
            ),
        }
    old_single = state["submitted_single"]
    state["TEXT_TO_TRANSLATE"] = "Updated input without a confirmed single POST"
    state["submitted_multi"]["_request_fingerprint"] = state["_request_fingerprint"](
        "/v1/jobs/benchmarks", state["_payload"](multi_model=True),
        state["MULTI_MODEL_IDEMPOTENCY_KEY"],
    )
    state["RUN_SUBMITTED_JOB_POLL"] = True
    state["SUBMITTED_JOB_TO_POLL"] = "both"
    jobs, errors = state["_select_submitted_jobs"]()
    assert jobs == [state["submitted_multi"]["job_id"]]
    assert errors == [{"reason": "request_mismatch"}]
    assert state["submitted_single"] is old_single






def test_basic_and_advanced_settings_initialize_keys_in_notebook_order():
    """Run All initializes key helpers; a later Basic-only edit preserves the key."""
    notebook = _notebook()
    codes = {c["id"]: c["source"] for c in notebook["cells"] if c["cell_type"] == "code"}
    ids = [cell["id"] for cell in notebook["cells"]]
    assert ids.index("request-key-internals") < ids.index("settings") < ids.index("advanced-settings")
    basic, advanced = codes["settings"], codes["advanced-settings"]
    assert "ACKNOWLEDGE_PAID_GPU = False" in basic
    assert "RUN_MULTI_MODEL_POST = False" in basic
    assert '_configure_request_keys(("single", "benchmark"))' in basic
    assert '_configure_request_keys(("benchmark",))' in advanced
    manager_cell = next(c for c in notebook["cells"] if c["id"] == "request-key-internals")
    assert manager_cell["metadata"]["jupyter"]["source_hidden"] is True
    state = {"__name__": "__new_notebook_kernel__"}
    with patch("urllib.request.OpenerDirector.open",
               side_effect=AssertionError("No network in settings")):
        for cid in ("request-key-internals", "settings", "advanced-settings"):
            exec(compile(codes[cid], str(NOTEBOOK), "exec"), state)
        original = state["SINGLE_MODEL_IDEMPOTENCY_KEY"]
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(basic, str(NOTEBOOK), "exec"), state)
        assert state["SINGLE_MODEL_IDEMPOTENCY_KEY"] == original
        assert state["RUN_SINGLE_MODEL_POST"] is False



@pytest.mark.parametrize(("cid", "flag", "key_name"), (
    ("post-translation", "RUN_SINGLE_MODEL_POST", "SINGLE_MODEL_IDEMPOTENCY_KEY"),
    ("post-benchmark", "RUN_MULTI_MODEL_POST", "MULTI_MODEL_IDEMPOTENCY_KEY"),
))
def test_invalid_persisted_key_format_is_rejected_before_preflight(cid, flag, key_name):
    """A malformed private key is a local failure, never a sent or bound POST."""
    code = _code_by_id(_notebook())
    state = {"__name__": "__invalid_key_header_test__"}
    _run_helpers(code, state)
    state["API_BASE_URL"] = "https://gateway.example.test"
    state["ACKNOWLEDGE_PAID_GPU"] = True
    state[flag] = True
    state[key_name] = "invalid" + chr(10) + "header"
    state["_request"] = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("Malformed header must not reach network or preflight")
    )
    with pytest.raises(ValueError, match="idempotency key"):
        exec(compile(code[cid], str(NOTEBOOK), "exec"), state)
    assert state["_REQUEST_IDENTITIES"] == {}




@pytest.mark.parametrize("language", ["VI", "", "fr"])
def test_basic_settings_reject_invalid_display_language_before_live_use(language):
    cells = {c["id"]: c["source"] for c in _notebook()["cells"] if c["cell_type"] == "code"}
    state = {"__name__": "__invalid_display_language__"}
    exec(compile(cells["request-key-internals"], str(NOTEBOOK), "exec"), state)
    configured = cells["settings"].replace('DISPLAY_LANGUAGE = "en"', f'DISPLAY_LANGUAGE = {language!r}')
    with pytest.raises(ValueError, match="DISPLAY_LANGUAGE"):
        exec(compile(configured, str(NOTEBOOK), "exec"), state)


def test_fresh_kernel_basic_settings_has_an_actionable_initialization_error():
    cells = {c["id"]: c["source"] for c in _notebook()["cells"] if c["cell_type"] == "code"}
    with pytest.raises(RuntimeError, match="Run All"):
        exec(compile(cells["settings"], str(NOTEBOOK), "exec"), {"__name__": "__fresh_kernel__"})


def test_kaggle_markdown_toc_has_consistent_bilingual_headings_and_links():
    """Kaggle and Jupyter should see Markdown headings, not platform-specific HTML IDs."""
    import re

    notebook = _notebook()
    markdown = [c["source"] for c in notebook["cells"] if c["cell_type"] == "markdown"]
    assert all("<a id=" not in source for source in markdown)
    headings = [
        (len(match.group(1)), match.group(2))
        for source in markdown
        for match in re.finditer(r"(?m)^(#{1,6}) (.+)$", source)
    ]
    assert headings[0][0] == 1
    assert sum(level == 2 and " / " in title for level, title in headings) >= 19
    assert all(level <= previous + 1 for (previous, _), (level, _)
               in zip(headings, headings[1:]))

    def slug(title):
        return re.sub(r"[^\w -]", "", title.lower().strip()).replace(" ", "-")

    anchors = [slug(title) for _, title in headings]
    assert len(anchors) == len(set(anchors))
    links = [
        target
        for source in markdown
        for target in re.findall(r"\]\(#([^)]+)\)", source)
    ]
    assert links
    assert set(links) <= set(anchors)
    assert all(cell["cell_type"] == "markdown" or cell.get("execution_count") is None
               for cell in notebook["cells"])
