from translation_ai_inference.worker import process_mock_translation_run


def test_claim_token_fences_duplicate_execution(client_factory, headers, translation_payload):
    client, repo = client_factory(dispatcher_mode="record-only")
    job = client.post("/v1/jobs/translations", headers=headers, json=translation_payload).json()
    run_id = str(client.get(job["status_url"], headers=headers).json()["runs"][0]["run_id"])
    token = repo.claim_dispatch(run_id)
    assert token and repo.claim_dispatch(run_id) is None
    assert process_mock_translation_run(repo, run_id, "incorrect-token") is False
    assert process_mock_translation_run(repo, run_id, token) is True
    assert process_mock_translation_run(repo, run_id, token) is False
    result = client.get(job["status_url"], headers=headers).json()
    assert result["status"] == "completed"
    assert result["runs"][0]["is_mock_result"] is True
