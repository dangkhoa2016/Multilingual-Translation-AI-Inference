from translation_ai_inference.adapters import CANDIDATE_ADAPTERS, TranslationTask
from translation_ai_inference.model_registry import MODEL_REGISTRY


def test_all_models_have_distinct_candidate_policies():
    assert set(CANDIDATE_ADAPTERS) == set(MODEL_REGISTRY)
    assert CANDIDATE_ADAPTERS["hy_mt2_30b"].decoding.temperature == 0.7
    assert CANDIDATE_ADAPTERS["index_35b"].decoding.temperature == 0.0
    assert CANDIDATE_ADAPTERS["qwen35_35b"].decoding.enable_thinking is False


def test_prompt_preserves_unicode_and_formatting():
    sample = "Xin chào!\nHello <PLACEHOLDER>"
    for adapter in CANDIDATE_ADAPTERS.values():
        prompt = adapter.build_prompt(TranslationTask("vi", "en", sample))
        assert sample in prompt.user
        assert "vi to en" in prompt.user
        assert "Preserve" in prompt.user
        assert "only the translated text" in prompt.system
        assert "unverified" in prompt.prompt_version
