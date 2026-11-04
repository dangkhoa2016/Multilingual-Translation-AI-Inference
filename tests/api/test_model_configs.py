"""Per-model inference config contracts: validation, persistence and replay safety.

All tests use a CPU-only database and offline llama.cpp payload construction.
"""
import json

import pytest

from multilingual_translation_ai_inference.gpu_runtime import build_translation_request
from multilingual_translation_ai_inference.model_options import (
    DEFAULT_DECODING,
    MAX_MAX_TOKENS,
    SUPPORTED_MODEL_OPTIONS,
    effective_decoding,
    validate_model_config,
)
from multilingual_translation_ai_inference.repository import payload_hash
from multilingual_translation_ai_inference.schemas import SubmitBenchmark, SubmitTranslation

HEADERS = {"Authorization": "Bearer unit-test-token-2026"}
BASE = {"source_language": "en", "target_language": "vi",
        "text": "The fox crossed the bridge.", "options": {"preserve_formatting": True}}


@pytest.mark.parametrize("key", DEFAULT_DECODING)
def test_default_model_decoding_is_preserved_without_overrides(key):
    result = effective_decoding(key, {})
    assert result["max_tokens"] == 1536
    assert result["seed"] == 42
    assert result["stream"] is False
    for option, expected in DEFAULT_DECODING[key].items():
        assert result[option] == expected


def test_independent_model_overrides_and_legacy_payload():
    options = {
        "preserve_formatting": True,
        "model_configs": {
            "hy_mt2_30b": {"temperature": 0.15, "top_k": 100,
                           "seed": 123, "max_tokens": 700,
                           "repeat_penalty": 1.3, "stop": ["[END]"]},
            "qwen35_35b": {"temperature": 0.95, "top_p": 0.55, "min_p": 0.05,
                          "enable_thinking": False},
        },
    }
    def en(key):
        return build_translation_request(
            key, "en", "vi", BASE["text"], json.dumps(options)
        )
    hy, qw, idx = en("hy_mt2_30b"), en("qwen35_35b"), en("index_35b")
    assert hy["temperature"] == 0.15
    assert hy["seed"] == 123 and hy["max_tokens"] == 700
    assert hy["stop"] == ["[END]"]
    assert qw["temperature"] == 0.95 and qw["top_p"] == 0.55
    assert qw["chat_template_kwargs"] == {"enable_thinking": False}
    assert "chat_template_kwargs" not in hy
    assert idx["temperature"] == DEFAULT_DECODING["index_35b"]["temperature"]
    assert idx["max_tokens"] == 1536
    legacy = build_translation_request(
        "hy_mt2_30b", "en", "vi", BASE["text"], '{"preserve_formatting":true}'
    )
    assert legacy["temperature"] == 0.7
    assert legacy["max_tokens"] == 1536


@pytest.mark.parametrize(("option", "value"), [
    ("temperature", True), ("temperature", float("nan")),
    ("temperature", float("inf")), ("temperature", -0.01),
    ("top_p", 1.01), ("top_k", 1001), ("top_k", True),
    ("max_tokens", MAX_MAX_TOKENS + 1), ("max_tokens", 0),
    ("seed", 4294967296), ("seed", False),
    ("repeat_penalty", -1), ("min_p", 1.1),
    ("presence_penalty", -3), ("enable_thinking", "yes"),
    ("mirostat", 3), ("ignore_eos", 1),
    ("stop", []), ("stop", ["x" * 101]),
    ("stop", ["valid", "\x00"]), ("stop", [1]),
    ("stream", True), ("ctx_size", 8192),
    ("n_gpu_layers", 1), ("model", "other"),
    ("messages", []), ("logit_bias", {"1": -100}),
])
def test_invalid_and_engine_level_overrides_are_rejected(option, value):
    with pytest.raises(ValueError):
        validate_model_config({option: value})


def test_all_supported_sampler_options_have_bounded_validation():
    assert len(SUPPORTED_MODEL_OPTIONS) >= 20
    assert validate_model_config({
        "max_tokens": 2048, "temperature": 0, "top_p": 1,
        "top_k": -1, "repeat_penalty": 1.1, "mirostat": 0,
        "ignore_eos": False, "dry_multiplier": 0, "stop": ["\n\n"],
    })["max_tokens"] == 2048


def test_api_accepts_per_model_configs_and_keeps_old_request_hash_stable(client_factory):
    client, repo = client_factory(dispatcher_mode="record-only")
    request = {**BASE, "model": "hy_mt2_30b"}
    key = "legacy-stable-config-hash"
    resp = client.post("/v1/jobs/translations", headers={**HEADERS, "Idempotency-Key": key},
                       json=request)
    assert resp.status_code == 202
    saved = repo.get(resp.json()["job_id"], "single-tenant-api")
    assert json.loads(saved.options_json) == {"preserve_formatting": True}
    assert saved.request_hash == payload_hash(
        "translation", BASE, ["hy_mt2_30b"]
    )
    config = {"model_configs": {"hy_mt2_30b": {"temperature": 0.1, "seed": 7}}}
    new = client.post("/v1/jobs/translations",
                      headers={**HEADERS, "Idempotency-Key": "custom-1"},
                      json={**request, **config})
    assert new.status_code == 202
    saved = repo.get(new.json()["job_id"], "single-tenant-api")
    assert json.loads(saved.options_json)["model_configs"] == config["model_configs"]
    replay = client.post("/v1/jobs/translations",
                         headers={**HEADERS, "Idempotency-Key": "custom-1"},
                         json={**request, **config})
    assert replay.status_code == 202 and replay.json()["job_id"] == new.json()["job_id"]
    conflict = client.post("/v1/jobs/translations",
                           headers={**HEADERS, "Idempotency-Key": "custom-1"},
                           json={**request, "model_configs": {
                               "hy_mt2_30b": {"temperature": 0.2, "seed": 7}}})
    assert conflict.status_code == 409


def test_benchmark_persists_distinct_model_overrides(client_factory):
    client, repo = client_factory(dispatcher_mode="record-only")
    overrides = {
        "hy_mt2_30b": {"temperature": 0.1, "max_tokens": 650},
        "qwen35_35b": {"temperature": 0.8, "top_p": 0.65},
    }
    resp = client.post("/v1/jobs/benchmarks",
                       headers={**HEADERS, "Idempotency-Key": "custom-bench"},
                       json={**BASE, "models": list(overrides), "model_configs": overrides})
    assert resp.status_code == 202, resp.text
    saved = repo.get(resp.json()["job_id"], "single-tenant-api")
    assert len(saved.runs) == 2
    opts = json.loads(saved.options_json)
    for run in saved.runs:
        req = build_translation_request(run.model_key, "en", "vi", BASE["text"],
                                        json.dumps(opts))
        for k, v in overrides[run.model_key].items():
            assert req[k] == v


@pytest.mark.parametrize(("endpoint", "selection", "configs"), [
    ("/v1/jobs/translations", {"model": "hy_mt2_30b"},
     {"index_35b": {"temperature": 0.2}}),
    ("/v1/jobs/benchmarks", {"models": ["hy_mt2_30b"]},
     {"qwen35_35b": {"temperature": 0.2}}),
    ("/v1/jobs/benchmarks", {"models": ["hy_mt2_30b"]},
     {"hy_mt2_30b": {"max_tokens": 6000}}),
    ("/v1/jobs/translations", {"model": "hy_mt2_30b"},
     {"hy_mt2_30b": {"stream": True}}),
])
def test_config_rejections_do_not_create_jobs(client_factory, endpoint, selection, configs):
    client, _ = client_factory(dispatcher_mode="record-only")
    response = client.post(endpoint, headers=HEADERS,
                           json={**BASE, **selection, "model_configs": configs})
    assert response.status_code == 422
    assert "model_configs" in response.text or "Value error" in response.text


def test_schema_defaults_and_selected_model_enforcement():
    single = SubmitTranslation.model_validate({**BASE, "model": "index_35b"})
    assert single.model_configs == {}
    benchmark = SubmitBenchmark.model_validate({**BASE, "models": ["hy_mt2_30b"]})
    assert benchmark.model_configs == {}
    with pytest.raises(ValueError):
        SubmitTranslation.model_validate({**BASE, "model": "index_35b",
            "model_configs": {"qwen35_35b": {"top_p": 0.5}}})


def test_cannot_inject_unvalidated_options_into_runtime():
    with pytest.raises(ValueError):
        build_translation_request("hy_mt2_30b", "en", "vi", BASE["text"],
                                  json.dumps({"preserve_formatting": True,
                                              "model_configs": {
                                                  "hy_mt2_30b": {"ctx_size": 999999}}}))


def test_retry_uses_original_per_model_config(client_factory):
    client, repo = client_factory(dispatcher_mode="record-only")
    request = {**BASE, "model": "hy_mt2_30b",
               "model_configs": {"hy_mt2_30b": {"temperature": 0.4, "max_tokens": 768}}}
    response = client.post("/v1/jobs/translations",
                           headers={**HEADERS, "Idempotency-Key": "retry-config-job"},
                           json=request)
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    first = repo.get(job_id, "single-tenant-api").runs[0]
    claim = repo.claim_dispatch(first.id)
    assert claim
    assert repo.start_run(first.id, claim) is not None
    repo.fail_run(first.id, claim, "MODEL_OUTPUT_UNUSABLE")
    assert repo.get(job_id, "single-tenant-api").runs[0].status == "failed"
    after_failure = repo.get(job_id, "single-tenant-api")
    original_options = after_failure.options_json
    new_run_id = repo.retry_failed_run(
        job_id=job_id, owner="single-tenant-api", run_id=first.id,
        expected_dispatch_mode="record-only",
    )
    retry = repo.get(job_id, "single-tenant-api")
    assert retry.options_json == original_options
    assert len(retry.runs) == 2
    assert any(r.id == new_run_id and r.attempt_no == 2 for r in retry.runs)
    params = build_translation_request(
        "hy_mt2_30b", "en", "vi", BASE["text"], retry.options_json
    )
    assert params["temperature"] == 0.4 and params["max_tokens"] == 768


@pytest.mark.parametrize("endpoint,selection", [
    ("/v1/jobs/translations", {"model": "hy_mt2_30b"}),
    ("/v1/jobs/benchmarks", {"models": ["hy_mt2_30b"]}),
])
def test_every_float_override_rejects_extremely_large_integer_without_http_500(
    client_factory, endpoint, selection
):
    from multilingual_translation_ai_inference.model_options import _FLOAT_RANGES

    client, _ = client_factory(dispatcher_mode="record-only")
    for index, name in enumerate(_FLOAT_RANGES):
        huge_number = 10 ** 400
        with pytest.raises(ValueError):
            validate_model_config({name: huge_number})
        request = {
            **BASE, **selection,
            "model_configs": {"hy_mt2_30b": {name: huge_number}},
        }
        response = client.post(endpoint, json=request, headers={
            **HEADERS, "Idempotency-Key": f"rejected-huge-number-{index}"
        })
        assert response.status_code == 422, (endpoint, name, response.status_code)
        assert "job_id" not in response.json(), (endpoint, name)
