from notebook_test_support import notebook, source


def test_visible_config_has_single_demo_mode_not_flag_matrix():
    s = source("config")
    assert "DEMO_MODE = " in s
    assert "RUN_SINGLE_MODEL_POST" not in s
    assert "RUN_MULTI_MODEL_POST" not in s

def test_bilingual_introduction_explains_secrets_cost_and_reruns():
    intro = source("intro")
    for term in ("English", "Tiếng Việt", "TRANSLATION_GATEWAY_BASE_URL",
                 "TRANSLATION_API_BEARER_TOKEN", "DEMO_RUN_ID", "GPU"):
        assert term in intro
    assert "16 GPU model runs" in intro or "16 model runs" in intro
    assert "warm-up" in intro
    assert "three" in intro

def test_no_provider_selection_or_manual_cell_order():
    assert "LOAD_FROM_COLAB_SECRETS" not in source("config")
    assert "LOAD_FROM_KAGGLE_SECRETS" not in source("config")
    assert "Run All" in source("intro")

def test_helper_cell_is_collapsed_but_auditable():
    helpers = next(c for c in notebook()["cells"] if c["id"] == "helpers")
    assert helpers["metadata"]["jupyter"]["source_hidden"] is True
    assert len("".join(helpers["source"])) > 2000
