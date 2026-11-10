import pytest
from notebook_test_support import EXPECTED_MODELS, execute, initialize


def test_default_model_selection():
    state = initialize()
    assert tuple(state["MULTI_MODEL_KEYS"]) == EXPECTED_MODELS

@pytest.mark.parametrize("value", ["", " ", "a" * 1001])
def test_invalid_text_rejected_before_job(value):
    state = initialize()
    state["MEASUREMENT_TEXTS"][0] = value
    with pytest.raises(ValueError):
        execute(state)
    assert not state.get("_OFFLINE_JOBS")

def test_duplicate_benchmark_model_rejected_before_translation():
    state = initialize()
    state["MULTI_MODEL_KEYS"] = ["hy_mt2_30b", "hy_mt2_30b"]
    with pytest.raises(ValueError):
        execute(state)
    assert not state.get("_OFFLINE_JOBS")

def test_same_language_rejected():
    state = initialize()
    state["TARGET_LANGUAGE"] = state["SOURCE_LANGUAGE"]
    with pytest.raises(ValueError):
        execute(state)

def test_arbitrary_printable_language_names():
    state = initialize()
    state["SOURCE_LANGUAGE"] = "Arabic"
    state["TARGET_LANGUAGE"] = "Vietnamese"
    execute(state)
    assert state["translation_result"]["source_language"] == "Arabic"
