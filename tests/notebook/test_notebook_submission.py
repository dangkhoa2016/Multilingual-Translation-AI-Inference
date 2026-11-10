import pytest
from notebook_test_support import FakeGateway, execute, gpu_environment, initialize, source


def test_gpu_full_run_all_posts_single_and_benchmark_once(monkeypatch):
    gpu_environment(monkeypatch)
    state, fake = initialize(), FakeGateway()
    output = execute(state, mode="gpu", fake=fake)
    assert [call[1] for call in fake.posts] == [
        "/v1/jobs/translations", *["/v1/jobs/benchmarks"] * 4,
    ]
    assert len(state["benchmark_result"]["runs"]) == 4
    assert "FULL DEMO COMPLETED" in output

def test_repeat_gpu_run_all_does_not_post_again(monkeypatch):
    gpu_environment(monkeypatch)
    state, fake = initialize(), FakeGateway()
    execute(state, mode="gpu", fake=fake)
    execute(state, mode="gpu", fake=fake)
    assert len(fake.posts) == 5

def test_new_demo_run_id_starts_new_paid_requests(monkeypatch):
    gpu_environment(monkeypatch)
    state, fake = initialize(), FakeGateway()
    execute(state, mode="gpu", fake=fake)
    keys = [call[2] for call in fake.posts]
    state["DEMO_RUN_ID"] = "separate-evaluation"
    execute(state, mode="gpu", fake=fake)
    assert len(fake.posts) == 10
    assert keys != [call[2] for call in fake.posts][5:]

def test_uncertain_post_cannot_be_repeated_in_same_kernel(monkeypatch):
    gpu_environment(monkeypatch)
    state, fake = initialize(), FakeGateway()
    fake.fail_next_post = True
    with pytest.raises(RuntimeError, match="Ambiguous"):
        execute(state, mode="gpu", fake=fake)
    with pytest.raises(RuntimeError, match="uncertain|chưa rõ"):
        execute(state, mode="gpu", fake=fake)
    assert len(fake.posts) == 1


def test_cost_budget_is_exactly_four_warmups_plus_twelve_measured_model_runs(monkeypatch):
    import copy

    gpu_environment(monkeypatch)
    state, fake = initialize(), FakeGateway()
    original = fake.__call__
    submitted = []

    def recorded(method, path, **kwargs):
        if method == "POST":
            submitted.append((path, copy.deepcopy(kwargs["payload"]), kwargs["idempotency_key"]))
        return original(method, path, **kwargs)

    output = execute(state, mode="gpu", fake=recorded)
    assert "FULL DEMO COMPLETED" in output
    assert len(submitted) == 5
    assert len({key for _, _, key in submitted}) == 5
    assert [path for path, _, _ in submitted] == [
        "/v1/jobs/translations", *["/v1/jobs/benchmarks"] * 4
    ]
    assert submitted[0][1]["text"] == state["WARMUP_TEXT"]
    assert submitted[0][1]["model"] == state["MODEL_KEY"]
    assert submitted[1][1]["models"] == list(state["MODEL_KEYS"][1:])
    assert submitted[1][1]["text"] == state["WARMUP_TEXT"]
    for index, (_, payload, _) in enumerate(submitted[2:]):
        assert payload["text"] == state["MEASUREMENT_TEXTS"][index]
        assert payload["models"] == list(state["MODEL_KEYS"])
    assert sum(len(job["runs"]) for job in (
        state["translation_result"], state["warmup_result"], *state["benchmark_results"]
    )) == 16
    assert len(state["benchmark_results"]) == 3
    assert all(job["status"] == "completed" for job in state["benchmark_results"])


def test_distinct_stage_key_even_when_payload_text_is_unchanged():
    state = initialize()
    state["API_BASE_URL"] = "https://translation.example.test"
    payload = state["_payload"](multi_model=True)
    k1 = state["_stable_key"]("/v1/jobs/benchmarks", payload, stage="measure-1")
    k2 = state["_stable_key"]("/v1/jobs/benchmarks", payload, stage="measure-2")
    assert k1 != k2
    assert k1 == state["_stable_key"]("/v1/jobs/benchmarks", payload, stage="measure-1")


def test_three_round_run_all_reuses_all_five_jobs_not_just_the_latest(monkeypatch):
    gpu_environment(monkeypatch)
    state, fake = initialize(), FakeGateway()
    execute(state, mode="gpu", fake=fake)
    old = [job["job_id"] for job in state["benchmark_results"]]
    old_posts = len(fake.posts)
    execute(state, mode="gpu", fake=fake)
    assert len(fake.posts) == old_posts == 5
    assert [job["job_id"] for job in state["benchmark_results"]] == old


def test_new_run_id_creates_distinct_stage_keys_and_jobs(monkeypatch):
    gpu_environment(monkeypatch)
    state, fake = initialize(), FakeGateway()
    execute(state, mode="gpu", fake=fake)
    before = [job["job_id"] for job in state["benchmark_results"]]
    state["DEMO_RUN_ID"] = "fresh-evaluation"
    execute(state, mode="gpu", fake=fake)
    assert len(fake.posts) == 10
    assert before != [job["job_id"] for job in state["benchmark_results"]]


def test_three_round_workflow_fails_before_paid_work_on_malformed_config(monkeypatch):
    gpu_environment(monkeypatch)
    for field, bad in (
        ("MEASUREMENT_TEXTS", ["first", "second"]),
        ("MEASUREMENT_TEXTS", ["first", "first", "third"]),
        ("MEASUREMENT_TEXTS", ["valid", "second", "x" * 1001]),
        ("WARMUP_TEXT", ""),
        ("MULTI_MODEL_KEYS", ["hy_mt2_30b", "hy_mt2_30b"]),
    ):
        state, fake = initialize(), FakeGateway()
        state[field] = bad
        with pytest.raises(ValueError):
            execute(state, mode="gpu", fake=fake)
        assert fake.posts == []


def test_second_measured_round_failure_stops_third_paid_benchmark(monkeypatch):
    gpu_environment(monkeypatch)
    state, fake = initialize(), FakeGateway()
    original = fake.__call__
    second_text = state["MEASUREMENT_TEXTS"][1]
    failed_job_ids = set()

    def fail_second_round(method, path, **kwargs):
        code, data = original(method, path, **kwargs)
        if method == "POST" and path.endswith("/benchmarks") and kwargs["payload"]["text"] == second_text:
            failed_job_ids.add(data["job_id"])
        if method == "GET" and path.startswith("/v1/jobs/") and data.get("job_id") in failed_job_ids:
            data["status"] = "failed"
            data["runs"][0]["status"] = "failed"
        return code, data

    with pytest.raises(RuntimeError, match="failed|uncertain"):
        execute(state, mode="gpu", fake=fail_second_round)
    assert len(fake.posts) == 4
    assert len(state["benchmark_results"]) == 2
    assert state["comparison_summary"] is None


def test_one_selected_model_gets_one_warmup_and_three_rounds(monkeypatch):
    gpu_environment(monkeypatch)
    state, fake = initialize(), FakeGateway()
    state["MULTI_MODEL_KEYS"] = ["qwen35_35b"]
    execute(state, mode="gpu", fake=fake)
    assert state["warmup_result"] is None
    assert state["translation_result"]["runs"][0]["model"] == "qwen35_35b"
    assert len(fake.posts) == 4
    assert [len(job["runs"]) for job in state["benchmark_results"]] == [1, 1, 1]


# Separate model-phase acceptance tests, in the same A-only test source file.


def per_model_state():
    state = initialize()
    state["BENCHMARK_SEQUENCE"] = "per_model"
    return state


def test_public_default_english_and_per_model():
    config = source("config")
    assert 'DISPLAY_LANGUAGE = "en"' in config
    assert 'BENCHMARK_SEQUENCE = "per_model"' in config


def test_per_model_has_one_warmup_followed_immediately_by_three_measurements(monkeypatch):
    gpu_environment(monkeypatch)
    state, fake = per_model_state(), FakeGateway()
    execute(state, mode="gpu", fake=fake)
    assert len(fake.posts) == 16
    assert len({call[2] for call in fake.posts}) == 16
    post_paths = [x[1] for x in fake.posts]
    for index in (0, 4, 8, 12):
        assert post_paths[index] == "/v1/jobs/translations"
        assert post_paths[index + 1:index + 4] == ["/v1/jobs/benchmarks"] * 3
    assert len(state["warmup_jobs"]) == 4
    assert len(state["measured_api_jobs"]) == 12
    assert len(state["benchmark_results"]) == 3
    assert state["benchmark_result"]["kind"] == "comparison_view"
    assert "job_id" not in state["benchmark_result"]  # no fabricated API UUID
    assert all(job["kind"] == "benchmark" and "job_id" in job
               for job in state["measured_api_jobs"])
    assert set(run["model"] for run in state["benchmark_results"][0]["runs"]) == set(state["MODEL_KEYS"])


def test_same_inputs_and_order_for_all_four_model_phases(monkeypatch):
    import copy
    gpu_environment(monkeypatch)
    state, fake = per_model_state(), FakeGateway()
    original = fake.__call__
    recorded = []
    def capture(method, path, **kwargs):
        if method == "POST":
            recorded.append((path, copy.deepcopy(kwargs["payload"])))
        return original(method, path, **kwargs)
    execute(state, mode="gpu", fake=capture)
    for idx, model in enumerate(state["MODEL_KEYS"]):
        segment = recorded[idx * 4: idx * 4 + 4]
        assert segment[0][1]["model"] == model
        assert segment[0][1]["text"] == state["WARMUP_TEXT"]
        assert [x[1]["models"] for x in segment[1:]] == [[model]] * 3
        assert [x[1]["text"] for x in segment[1:]] == state["MEASUREMENT_TEXTS"]


def test_same_run_id_does_not_send_duplicate_paid_jobs(monkeypatch):
    gpu_environment(monkeypatch)
    state, fake = per_model_state(), FakeGateway()
    execute(state, mode="gpu", fake=fake)
    ids = [j["job_id"] for j in state["measured_api_jobs"]]
    execute(state, mode="gpu", fake=fake)
    assert len(fake.posts) == 16
    assert [j["job_id"] for j in state["measured_api_jobs"]] == ids


def test_new_run_id_is_new_evaluation(monkeypatch):
    gpu_environment(monkeypatch)
    state, fake = per_model_state(), FakeGateway()
    execute(state, mode="gpu", fake=fake)
    first = [call[2] for call in fake.posts]
    state["DEMO_RUN_ID"] = "another-evaluation"
    execute(state, mode="gpu", fake=fake)
    assert len(fake.posts) == 32
    assert first != [call[2] for call in fake.posts][16:]


def test_failed_first_measurement_stops_later_paid_jobs(monkeypatch):
    gpu_environment(monkeypatch)
    state, fake = per_model_state(), FakeGateway()
    original = fake.__call__
    def failed(method, path, **kwargs):
        status, result = original(method, path, **kwargs)
        if method == "GET" and path.startswith("/v1/jobs/") and result["kind"] == "benchmark":
            result["status"] = "failed"
            result["runs"][0]["status"] = "failed"
        return status, result
    with pytest.raises(RuntimeError, match="failed|uncertain"):
        execute(state, mode="gpu", fake=failed)
    assert len(fake.posts) == 2


def test_one_selected_model_uses_four_real_jobs(monkeypatch):
    gpu_environment(monkeypatch)
    state, fake = per_model_state(), FakeGateway()
    state["MULTI_MODEL_KEYS"] = ["qwen35_35b"]
    execute(state, mode="gpu", fake=fake)
    assert len(fake.posts) == 4
    assert state["translation_result"]["runs"][0]["model"] == "qwen35_35b"
    assert len(state["benchmark_results"]) == 3
    assert len(state["warmup_jobs"]) == 1


def test_invalid_sequence_stops_without_request(monkeypatch):
    gpu_environment(monkeypatch)
    state, fake = per_model_state(), FakeGateway()
    state["BENCHMARK_SEQUENCE"] = "unknown"
    with pytest.raises(ValueError, match="BENCHMARK_SEQUENCE"):
        execute(state, mode="gpu", fake=fake)
    assert not fake.calls


def test_model_phase_report_uses_missing_warm_evidence_as_na():
    state = per_model_state()
    execute(state)
    markup = state["_summary_html"](state["comparison_summary"])
    assert "Warm reuse" in markup
    assert "N/A" in markup
    assert markup.count("<details") == 3
    assert all(x["kind"] == "comparison_view" for x in state["benchmark_results"])


def test_default_per_model_paces_sixteen_jobs_with_real_api_quota(
    client_factory, monkeypatch,
):
    """Real FastAPI/SQLite admission, synthetic CPU completions, no GPU/network."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    import multilingual_translation_ai_inference.quotas as quotas
    from multilingual_translation_ai_inference.database import UsageWindow

    class Clock:
        seconds = 0.0

        def monotonic(self):
            return self.seconds

        def sleep(self, delay):
            self.seconds += delay

    clock = Clock()
    base = datetime(2026, 11, 18, tzinfo=timezone.utc)

    class QuotaClock:
        @staticmethod
        def now(tz):
            return (base + timedelta(seconds=clock.seconds)).astimezone(tz)

    monkeypatch.setattr(quotas, "datetime", QuotaClock)
    gpu_environment(monkeypatch)
    client, repo = client_factory(
        dispatcher_mode="inline-mock", max_jobs_per_minute=10,
    )
    state = per_model_state()
    state["_gpu_monotonic"] = clock.monotonic
    state["_gpu_sleep"] = clock.sleep
    state["_pace_gpu_submissions"] = state["_pace_gpu_submissions_real"]
    posts = []

    def local_request(method, path, *, payload=None, authenticated=False,
                      idempotency_key=None):
        if path == "/health":
            return 200, {"status": "ok", "phase": "gpu",
                         "inference_enabled": True}
        if path == "/v1/models":
            response = client.get(path)
            result = response.json()
            for model in result["models"]:
                model["enabled"] = True
                model["runtime_verified"] = True
            return response.status_code, result
        headers = {}
        if authenticated:
            headers["Authorization"] = "Bearer unit-test-token-2026"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        response = client.request(method, path, json=payload, headers=headers)
        if method == "POST":
            posts.append((clock.seconds, response.status_code))
        if response.status_code >= 400:
            hint = response.headers.get("Retry-After")
            raise state["APIRequestError"](
                response.status_code, int(hint) if hint is not None else None
            )
        result = response.json()
        if method == "GET" and path.startswith("/v1/jobs/"):
            # The actual server still uses CPU mock. Only the test adapter
            # presents these synthetic completions as if they were GPU results.
            # This is NOT production inference evidence.
            for run in result["runs"]:
                run["is_mock_result"] = False
        return response.status_code, result

    output = execute(state, mode="gpu", fake=local_request)
    assert "FULL DEMO COMPLETED" in output
    assert len(posts) == 16
    assert all(status == 202 for _, status in posts)
    assert all(b - a >= 6.24 for (a, _), (b, _) in zip(posts, posts[1:]))
    assert len(state["measured_api_jobs"]) == 12
    with repo.session_factory() as session:
        windows = list(session.scalars(select(UsageWindow).where(
            UsageWindow.scope == "jobs-per-minute"
        )))
    assert sum(row.used for row in windows) == 16
    assert max(row.used for row in windows) <= 10


def test_gpu_pacer_does_not_automatically_replay_a_definite_post_429(
    monkeypatch,
):
    gpu_environment(monkeypatch)
    state = per_model_state()
    fake = FakeGateway()
    original = fake.__call__
    first_429 = []

    def rate_limited(method, path, **kwargs):
        if method == "POST" and len(fake.posts) == 10:
            first_429.append(kwargs["idempotency_key"])
            fake.calls.append((method, path, kwargs["idempotency_key"]))
            raise state["APIRequestError"](429, 30)
        return original(method, path, **kwargs)

    with pytest.raises(state["APIRequestError"], match="429"):
        execute(state, mode="gpu", fake=rate_limited)
    assert len(first_429) == 1
    assert len(fake.posts) == 11  # 10 accepted and exactly 1 rejected
    assert len({call[2] for call in fake.posts}) == 11
