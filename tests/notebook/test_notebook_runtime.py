from notebook_test_support import EXPECTED_MODELS, execute, initialize


def test_offline_run_all_executes_single_and_four_model_demo():
    state = initialize()
    output = execute(state)
    assert state["translation_result"]["status"] == "completed"
    assert state["benchmark_result"]["status"] == "completed"
    assert [r["model"] for r in state["benchmark_result"]["runs"]] == list(EXPECTED_MODELS)
    assert all(r["is_mock_result"] for j in (state["translation_result"], state["benchmark_result"]) for r in j["runs"])
    assert "FULL DEMO COMPLETED" in output

def test_offline_run_all_never_calls_external_api():
    state = initialize()
    def forbidden(*args, **kwargs):
        raise AssertionError("HTTP not allowed in offline mode")
    state["_LIVE_REQUEST"] = forbidden
    execute(state)
    assert len(state["_OFFLINE_JOBS"]) == 5

def test_repeat_offline_run_all_stable_job_id():
    state = initialize()
    execute(state)
    first = state["translation_result"]["job_id"]
    execute(state)
    assert state["translation_result"]["job_id"] == first
    state["DEMO_RUN_ID"] = "new-demo"
    execute(state)
    assert state["translation_result"]["job_id"] != first
