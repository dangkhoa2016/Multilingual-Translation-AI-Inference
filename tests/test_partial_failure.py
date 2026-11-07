from translation_ai_inference.worker import process_mock_translation_run


def test_failed_one_model_other_model_is_visible(client_factory, headers):
    client, repo = client_factory(dispatcher_mode="record-only")
    response = client.post("/v1/jobs/benchmarks", headers=headers, json={
        "source_language": "en", "target_language": "vi", "text": "Hello",
        "models": ["hy_mt2_30b", "index_35b"],
    })
    details = client.get(response.json()["status_url"], headers=headers).json()
    first, second = [r["run_id"] for r in details["runs"]]
    first_token = repo.claim_dispatch(first)
    second_token = repo.claim_dispatch(second)
    assert process_mock_translation_run(repo, first, first_token)
    repo.fail_run(second, second_token, "MODEL_FAILED_TEST")
    result = client.get(response.json()["status_url"], headers=headers).json()
    assert result["status"] == "partial_failed"
    assert {r["status"] for r in result["runs"]} == {"completed", "failed"}
    assert [r for r in result["runs"] if r["status"] == "completed"][0]["is_mock_result"]


def test_unknown_modal_dispatch_is_not_retried_blindly(client_factory, headers, translation_payload):
    class AmbiguousDispatcher:
        def submit(self, repo, run_id, claim_token):
            raise ConnectionError("Simulated unclear Modal spawn result")

    client, repo = client_factory(dispatcher=AmbiguousDispatcher())
    response = client.post("/v1/jobs/translations", headers=headers, json=translation_payload)
    assert response.status_code == 202
    assert response.json()["status"] == "dispatch_uncertain"
    repeated = client.post("/v1/jobs/translations", headers=headers, json=translation_payload)
    assert repeated.status_code == 202
    assert repeated.json()["job_id"] == response.json()["job_id"]
    assert repeated.json()["status"] == "dispatch_uncertain"
