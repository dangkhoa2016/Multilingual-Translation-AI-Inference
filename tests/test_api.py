from translation_ai_inference.resource_names import (
    MODAL_APP_NAME,
    MODAL_GPU_INFERENCE_FUNCTION_NAMES,
    MODAL_GPU_WEIGHT_VOLUME_NAMES,
)


def test_health_is_public_and_does_not_claim_gpu(client_factory):
    client, _ = client_factory()
    assert client.get("/health").json() == {
        "status": "ok", "inference_enabled": False, "phase": "mock-only"
    }


def test_routes_require_bearer_token(client_factory, translation_payload):
    client, _ = client_factory()
    assert client.get("/v1/models").status_code == 401
    assert client.get("/v1/models", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post("/v1/jobs/translations", json=translation_payload).status_code == 401


def test_models_have_unverified_flag(client_factory, headers):
    client, _ = client_factory()
    models = client.get("/v1/models", headers=headers).json()["models"]
    assert len(models) == 4
    assert all(model["runtime_verified"] is False and model["enabled"] is False for model in models)


def test_translation_inline_mock_is_explicitly_fake(client_factory, headers, translation_payload):
    client, _ = client_factory()
    submitted = client.post("/v1/jobs/translations", headers=headers, json=translation_payload)
    assert submitted.status_code == 202
    assert submitted.json()["status"] == "completed"
    result = client.get(submitted.json()["status_url"], headers=headers)
    assert result.status_code == 200
    runs = result.json()["runs"]
    assert len(runs) == 1 and runs[0]["is_mock_result"] is True
    assert runs[0]["translation_text"].startswith("[MOCK ONLY — NOT A TRANSLATION")


def test_idempotency_same_key_same_payload_returns_same_job(client_factory, headers, translation_payload):
    client, _ = client_factory()
    first = client.post("/v1/jobs/translations", headers=headers, json=translation_payload)
    second = client.post("/v1/jobs/translations", headers=headers, json=translation_payload)
    assert first.json()["job_id"] == second.json()["job_id"]


def test_idempotency_key_conflict_for_different_payload(client_factory, headers, translation_payload):
    client, _ = client_factory()
    first = client.post("/v1/jobs/translations", headers=headers, json=translation_payload)
    translation_payload["text"] = "Good evening!"
    second = client.post("/v1/jobs/translations", headers=headers, json=translation_payload)
    assert first.status_code == 202 and second.status_code == 409


def test_without_key_new_submission_creates_new_job(client_factory, translation_payload):
    client, _ = client_factory()
    headers = {"Authorization": "Bearer unit-test-token"}
    first = client.post("/v1/jobs/translations", headers=headers, json=translation_payload)
    second = client.post("/v1/jobs/translations", headers=headers, json=translation_payload)
    assert first.json()["job_id"] != second.json()["job_id"]


def test_benchmark_partial_model_subset_and_all_models(client_factory, headers):
    client, _ = client_factory()
    body = {"source_language": "en", "target_language": "vi", "text": "Hello"}
    submitted = client.post("/v1/jobs/benchmarks", headers=headers, json=body)
    assert submitted.status_code == 202
    detail = client.get(submitted.json()["status_url"], headers=headers).json()
    assert detail["kind"] == "benchmark" and detail["status"] == "completed"
    assert len(detail["runs"]) == 4
    assert {run["model"] for run in detail["runs"]} == set(MODAL_GPU_WEIGHT_VOLUME_NAMES)


def test_record_only_does_not_claim_or_execute(client_factory, headers, translation_payload):
    client, _ = client_factory(dispatcher_mode="record-only")
    response = client.post("/v1/jobs/translations", headers=headers, json=translation_payload)
    assert response.status_code == 202 and response.json()["status"] == "queued"
    run = client.get(response.json()["status_url"], headers=headers).json()["runs"][0]
    assert run["status"] == "queued" and run["translation_text"] is None


def test_limits_languages_and_model_restrictions(client_factory, headers, translation_payload):
    client, _ = client_factory()
    invalid = [
        {**translation_payload, "model": "fake"},
        {**translation_payload, "source_language": "xx"},
        {**translation_payload, "target_language": "en"},
        {**translation_payload, "text": "\n\t "},
        {**translation_payload, "text": "あ" * 1001},
        {**translation_payload, "options": {"malicious": True}},
    ]
    for payload in invalid:
        assert client.post("/v1/jobs/translations", headers=headers, json=payload).status_code == 422
    good = {**translation_payload, "text": "ạ" * 1000}
    assert client.post("/v1/jobs/translations", headers=headers, json=good).status_code == 202


def test_benchmark_rejects_duplicate_model(client_factory, headers):
    client, _ = client_factory()
    response = client.post("/v1/jobs/benchmarks", headers=headers,
                           json={"source_language": "en", "target_language": "vi", "text": "Hello",
                                 "models": ["hy_mt2_30b", "hy_mt2_30b"]})
    assert response.status_code == 422


def test_unknown_job_is_404(client_factory, headers):
    client, _ = client_factory()
    assert client.get("/v1/jobs/00000000-0000-0000-0000-000000000000",
                      headers=headers).status_code == 404


def test_names_are_explicit_and_unique():
    assert MODAL_APP_NAME == "translation-ai-inference-api-and-model-workers"
    assert len(MODAL_GPU_WEIGHT_VOLUME_NAMES) == len(set(MODAL_GPU_WEIGHT_VOLUME_NAMES.values())) == 4
    assert len(MODAL_GPU_INFERENCE_FUNCTION_NAMES) == len(set(MODAL_GPU_INFERENCE_FUNCTION_NAMES.values())) == 4
    for key, volume_name in MODAL_GPU_WEIGHT_VOLUME_NAMES.items():
        assert volume_name.startswith("translation-ai-inference-")
        assert volume_name.endswith("-gguf-weights")
        assert key in MODAL_GPU_INFERENCE_FUNCTION_NAMES
