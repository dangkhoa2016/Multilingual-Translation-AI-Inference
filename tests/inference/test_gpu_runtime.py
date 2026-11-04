"""Offline GPU routing, output and PostgreSQL fencing regression tests.

No NVIDIA device, Modal network call or downloaded model is required.
"""
import json
from types import SimpleNamespace

import modal
import pytest

import modal_app
from multilingual_translation_ai_inference.dispatcher import ModalGpuDispatcher
from multilingual_translation_ai_inference.gpu_runtime import (
    ExecutionUncertain,
    InferenceFailure,
    L40SModelRuntime,
    UnsupportedLanguagePair,
    build_translation_request,
    extract_translation,
    load_verified_spec,
)
from multilingual_translation_ai_inference.resource_names import (
    MODAL_APP_NAME,
    MODAL_GPU_INFERENCE_CLASS_NAMES,
    MODAL_GPU_WEIGHT_VOLUME_NAMES,
)
from multilingual_translation_ai_inference.settings import Settings


def test_real_modal_classes_map_1_to_1_with_volumes():
    assert len(MODAL_GPU_INFERENCE_CLASS_NAMES) == 4
    assert len(set(MODAL_GPU_INFERENCE_CLASS_NAMES.values())) == 4
    assert len(set(MODAL_GPU_WEIGHT_VOLUME_NAMES.values())) == 4
    for name in MODAL_GPU_INFERENCE_CLASS_NAMES.values():
        assert hasattr(modal_app, name)
    assert modal_app.app.name == MODAL_APP_NAME
    assert modal_app.gpu_worker_common["min_containers"] == 0
    assert modal_app.gpu_worker_common["buffer_containers"] == 0
    assert modal_app.gpu_worker_common["max_containers"] == 1
    assert modal_app.gpu_worker_common["gpu"] == "L40S"
    assert modal_app.gpu_worker_common["scaledown_window"] == 60


def test_verified_marker_required_before_gpu_model_load(tmp_path):
    manifest = {
        "models": {
            "index_35b": {
                "gguf_filename": "tiny.gguf",
                "gguf_size_bytes": 4,
                "gguf_revision": "a" * 40,
                "gguf_lfs_sha256": "b" * 64,
            }
        }
    }
    locked = tmp_path / "model_manifest.json"
    locked.write_text(json.dumps(manifest))
    weights = tmp_path / "weights"
    weights.mkdir()
    (weights / "tiny.gguf").write_bytes(b"GGUF")
    with pytest.raises(RuntimeError, match="marker"):
        load_verified_spec("index_35b", locked, weights)
    (weights / "verified_gguf_q8_0.json").write_text(json.dumps({
        "sha256_verified_locally": "wrong",
        "repo_revision": "a" * 40,
        "bytes": 4,
    }))
    with pytest.raises(RuntimeError, match="mismatch"):
        load_verified_spec("index_35b", locked, weights)
    (weights / "verified_gguf_q8_0.json").write_text(json.dumps({
        "sha256_verified_locally": "b" * 64,
        "repo_revision": "a" * 40,
        "bytes": 4,
    }))
    assert load_verified_spec("index_35b", locked, weights) == manifest["models"]["index_35b"]


def test_request_decoding_is_model_specific_and_language_names_are_clear():
    for key, expected in (
        ("hy_mt2_30b", (0.7, 1.0, -1)),
        ("index_35b", (0.0, 1.0, 20)),
        ("gemma4_31b_it", (1.0, 0.95, 64)),
        ("qwen35_35b", (0.7, 0.8, 20)),
    ):
        request = build_translation_request(
            key, "en", "vi", "The fox crossed the bridge.",
            '{"preserve_formatting": true}',
        )
        assert (request["temperature"], request["top_p"], request["top_k"]) == expected
        assert 'language labeled "en" into the language labeled "vi"' in request["messages"][0]["content"]
        assert "Keep paragraph breaks" in request["messages"][0]["content"]
        assert request["max_tokens"] == 1536
        assert len(request["messages"]) == 1


@pytest.mark.parametrize("pair,text,options", [
    (("", "vi"), "hello", '{"preserve_formatting": true}'),
    (("fr\nes", "vi"), "hello", '{"preserve_formatting": true}'),
    (("a" * 65, "vi"), "hello", '{"preserve_formatting": true}'),
    (("en", "en"), "hello", '{"preserve_formatting": true}'),
    (("en", "vi"), " ", '{"preserve_formatting": true}'),
    (("en", "vi"), "a" * 1001, '{"preserve_formatting": true}'),
    (("en", "vi"), "hello", '{"preserve_formatting": "false"}'),
    (("en", "vi"), "hello", '{"extra": true}'),
    (("en", "vi"), "hello\x00", '{"preserve_formatting": true}'),
    (("en", "vi"), "hello\ud800", '{"preserve_formatting": true}'),
    (("en", "vi"), "hello\udfff", '{"preserve_formatting": true}'),
])
def test_request_guards_invalid_language_size_and_options(pair, text, options):
    with pytest.raises(ValueError):
        build_translation_request("hy_mt2_30b", pair[0], pair[1], text, options)


def test_open_language_runtime_and_model_reported_unsupported():
    request = build_translation_request(
        "qwen35_35b", "zh-Hant", "Português (Brasil)", "早安",
        '{"preserve_formatting": true}',
    )
    user = request["messages"][0]["content"]
    assert '"zh-Hant"' in user
    assert '"Português (Brasil)"' in user
    assert "UNSUPPORTED_LANGUAGE_PAIR" in user
    with pytest.raises(UnsupportedLanguagePair, match="unsupported language pair"):
        extract_translation({"choices": [{
            "message": {"content": "UNSUPPORTED_LANGUAGE_PAIR"},
            "finish_reason": "stop",
        }]})


@pytest.mark.parametrize("response", [
    {"choices": []},
    {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]},
    {"choices": [{"message": {"content": "Part"}, "finish_reason": "length"}]},
    {"choices": [{"message": {"content": "<think>reason</think>Hi"}, "finish_reason": "stop"}]},
    {"choices": [{"message": {"content": "Hi"}, "finish_reason": "content_filter"}]},
])
def test_unusable_or_truncated_completions_are_never_saved(response):
    with pytest.raises(InferenceFailure):
        extract_translation(response)


def test_completion_preserves_user_translation_and_usage():
    text, in_tokens, out_tokens = extract_translation({
        "choices": [{"message": {"content": " Chào buổi sáng. "},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 72, "completion_tokens": 9},
    })
    assert (text, in_tokens, out_tokens) == (" Chào buổi sáng. ", 72, 9)


@pytest.mark.parametrize("translation", [
    "  Chào buổi sáng.  ",
    "\n  Dòng một\n    Dòng hai\n",
    "\tIndented result\t\n",
    "Đúng định dạng\n\n",
])
def test_completed_translation_preserves_exact_boundary_whitespace(translation):
    response = {"choices": [{
        "message": {"content": translation}, "finish_reason": "stop",
    }], "usage": {"prompt_tokens": 3, "completion_tokens": 5}}
    content, prompt_tokens, completion_tokens = extract_translation(response)
    assert content == translation
    assert (prompt_tokens, completion_tokens) == (3, 5)


def test_whitespace_only_completion_is_rejected():
    with pytest.raises(InferenceFailure, match="no translated content"):
        extract_translation({"choices": [{
            "message": {"content": " \n\t  "}, "finish_reason": "stop",
        }]})


def _queued_run(client_factory, payload):
    client, repo = client_factory(dispatcher_mode="record-only")
    submitted = client.post("/v1/jobs/translations",
                            headers={"Authorization": "Bearer unit-test-token-2026"},
                            json=payload)
    assert submitted.status_code == 202
    job_id = submitted.json()["job_id"]
    detail = repo.get(job_id, "single-tenant-api")
    run_id = detail.runs[0].id
    token = repo.claim_dispatch(run_id)
    assert token
    return repo, run_id, token


def test_real_worker_persists_nonmock_translation_and_token_usage(
    client_factory, translation_payload, monkeypatch,
):
    repo, run_id, token = _queued_run(client_factory, translation_payload)
    monkeypatch.setenv("TRANSLATION_INFERENCE_DATABASE_URL",
                       str(repo.session_factory.kw["bind"].url))
    worker = L40SModelRuntime("hy_mt2_30b")
    invocations = []

    def translate(source, target, text, options):
        invocations.append((source, target, text, options))
        return "Chào buổi sáng!", 30, 10

    monkeypatch.setattr(worker, "translate", translate)
    assert worker.process_job(run_id, token) is True
    assert worker.process_job(run_id, token) is False
    assert len(invocations) == 1
    state = repo.get(_job_for_run(repo, run_id), "single-tenant-api")
    assert state.runs[0].status == "completed"
    result = state.runs[0].result
    assert result.is_mock_result is False
    assert result.translation_text == "Chào buổi sáng!"
    assert result.input_tokens == 30 and result.output_tokens == 10


def _job_for_run(repo, run_id):
    from sqlalchemy import select

    from multilingual_translation_ai_inference.database import JobRun
    with repo.session_factory() as session:
        return session.scalar(select(JobRun.job_id).where(JobRun.id == run_id))


def test_worker_known_error_is_definite_failure(client_factory, translation_payload, monkeypatch):
    repo, run_id, token = _queued_run(client_factory, translation_payload)
    monkeypatch.setenv("TRANSLATION_INFERENCE_DATABASE_URL",
                       str(repo.session_factory.kw["bind"].url))
    worker = L40SModelRuntime("hy_mt2_30b")
    def unusable(*args):
        raise InferenceFailure("bad model output")
    monkeypatch.setattr(worker, "translate", unusable)
    assert worker.process_job(run_id, token) is False
    state = repo.get(_job_for_run(repo, run_id), "single-tenant-api")
    assert state.runs[0].status == "failed"
    assert state.runs[0].error_code == "GPU_INFERENCE_FAILED"


def test_worker_unknown_execution_is_not_automatically_retried(
    client_factory, translation_payload, monkeypatch,
):
    repo, run_id, token = _queued_run(client_factory, translation_payload)
    monkeypatch.setenv("TRANSLATION_INFERENCE_DATABASE_URL",
                       str(repo.session_factory.kw["bind"].url))
    worker = L40SModelRuntime("hy_mt2_30b")
    def uncertain(*args):
        raise ExecutionUncertain("request acknowledgement lost")
    monkeypatch.setattr(worker, "translate", uncertain)
    assert worker.process_job(run_id, token) is False
    state = repo.get(_job_for_run(repo, run_id), "single-tenant-api")
    assert state.runs[0].status == "execution_uncertain"
    assert state.runs[0].error_code == "GPU_EXECUTION_UNCERTAIN"
    assert repo.finish_run(run_id, token, "Delayed completion", mock=False) is True
    assert repo.get(_job_for_run(repo, run_id), "single-tenant-api").runs[0].status == "completed"


def test_dispatcher_routes_claimed_run_to_matching_gpu_class(
    client_factory, translation_payload, monkeypatch,
):
    repo, run_id, token = _queued_run(client_factory, translation_payload)
    captured = []

    def fake_from_name(app_name, cls_name):
        captured.append((app_name, cls_name))
        def make_instance():
            def spawn(_run_id, _token):
                captured.append((_run_id, _token))
                return SimpleNamespace(object_id="fc-request-id")
            return SimpleNamespace(process_job=SimpleNamespace(spawn=spawn))
        return make_instance

    monkeypatch.setattr(modal.Cls, "from_name", fake_from_name)
    result = ModalGpuDispatcher().submit(repo, run_id, token)
    assert result == "fc-request-id"
    assert captured == [
        (MODAL_APP_NAME, MODAL_GPU_INFERENCE_CLASS_NAMES["hy_mt2_30b"]),
        (run_id, token),
    ]


def test_real_mode_requires_explicit_environment_flag(monkeypatch):
    monkeypatch.setenv("TRANSLATION_INFERENCE_DATABASE_URL", "sqlite:///tmp/test.db")
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", "synthetic-long-test-token")
    monkeypatch.setenv("TRANSLATION_DISPATCHER_MODE", "modal-gpu")
    settings = Settings.from_environment()
    assert settings.dispatcher_mode == "modal-gpu"
    monkeypatch.setenv("TRANSLATION_DISPATCHER_MODE", "modal-cpu-mock")
    assert Settings.from_environment().dispatcher_mode == "modal-cpu-mock"


@pytest.mark.parametrize("usage,expected", [
    (None, (None, None)), ([1], (None, None)), ("optional", (None, None)),
    ({"prompt_tokens": "3", "completion_tokens": 7}, (None, 7)),
    ({"prompt_tokens": True, "completion_tokens": False}, (None, None)),
    ({"prompt_tokens": -1, "completion_tokens": 4.0}, (None, None)),
    ({"prompt_tokens": 2**31, "completion_tokens": 3}, (None, 3)),
    ({"prompt_tokens": 0, "completion_tokens": 2**31-1}, (0, 2**31-1)),
])
def test_optional_usage_cannot_invalidate_a_completed_translation(usage, expected):
    response = {"choices": [{"finish_reason": "stop", "message": {"content": "Valid output"}}],
                "usage": usage}
    assert extract_translation(response) == ("Valid output", *expected)

def test_same_gpu_container_reports_proven_reuse_and_engine_readiness(
    client_factory, translation_payload, monkeypatch,
):
    client, repo = client_factory(dispatcher_mode="record-only")
    monkeypatch.setenv("TRANSLATION_INFERENCE_DATABASE_URL",
                       str(repo.session_factory.kw["bind"].url))
    worker = L40SModelRuntime("hy_mt2_30b")
    worker.ready_seconds = 8.5
    monkeypatch.setattr(worker, "translate", lambda *args: ("Đã dịch.", 5, 7))
    statuses = []
    for i in range(2):
        payload = {**translation_payload, "text": f"Model phase {i}"}
        submitted = client.post(
            "/v1/jobs/translations",
            headers={"Authorization": "Bearer unit-test-token-2026"},
            json=payload,
        )
        assert submitted.status_code == 202
        rid = repo.get(submitted.json()["job_id"], "single-tenant-api").runs[0].id
        token = repo.claim_dispatch(rid)
        assert worker.process_job(rid, token)
        result = client.get(
            submitted.json()["status_url"],
            headers={"Authorization": "Bearer unit-test-token-2026"},
        )
        assert result.status_code == 200
        statuses.append(result.json()["runs"][0]["timings"])
    assert statuses[0]["worker_reuse_confirmed"] == 0.0
    assert statuses[0]["engine_ready_ms"] == 8500.0
    assert statuses[1]["worker_reuse_confirmed"] == 1.0
    assert "engine_ready_ms" not in statuses[1]
    assert worker._completed_jobs == 2


def test_failed_gpu_run_does_not_mark_worker_as_warm(
    client_factory, translation_payload, monkeypatch,
):
    repo, rid, token = _queued_run(client_factory, translation_payload)
    monkeypatch.setenv("TRANSLATION_INFERENCE_DATABASE_URL",
                       str(repo.session_factory.kw["bind"].url))
    worker = L40SModelRuntime("hy_mt2_30b")
    monkeypatch.setattr(worker, "translate",
                        lambda *args: (_ for _ in ()).throw(InferenceFailure("bad")))
    assert worker.process_job(rid, token) is False
    assert worker._completed_jobs == 0
