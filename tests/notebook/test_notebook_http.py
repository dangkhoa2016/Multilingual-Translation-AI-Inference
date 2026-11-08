import pytest
from notebook_test_support import FakeGateway, execute, gpu_environment, initialize


def test_mock_only_gateway_blocks_gpu_before_post(monkeypatch):
    gpu_environment(monkeypatch)
    state, fake = initialize(), FakeGateway(phase="mock-only")
    with pytest.raises(RuntimeError, match="GPU"):
        execute(state, mode="gpu", fake=fake)
    assert fake.posts == []

def test_disabled_model_blocks_gpu_before_post(monkeypatch):
    gpu_environment(monkeypatch)
    state, fake = initialize(), FakeGateway(enabled={"hy_mt2_30b"})
    with pytest.raises(RuntimeError, match="enabled"):
        execute(state, mode="gpu", fake=fake)
    assert fake.posts == []

def test_insecure_base_url_rejected_before_post(monkeypatch):
    gpu_environment(monkeypatch)
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "http://insecure.example.test")
    state, fake = initialize(), FakeGateway()
    with pytest.raises(Exception):
        execute(state, mode="gpu", fake=fake)
    assert fake.posts == []

def test_unknown_demo_mode_not_allowed():
    with pytest.raises(ValueError, match="DEMO_MODE"):
        execute(initialize(), mode="unknown")


@pytest.mark.parametrize("status", [401, 403, 409, 422, 500])
def test_poll_http_fatal_error_does_not_retry_or_post(monkeypatch, status):
    gpu_environment(monkeypatch)
    state, fake = initialize(), FakeGateway()
    original = fake.__call__

    def reject_one_get(method, path, **kwargs):
        if method == "GET" and path.startswith("/v1/jobs/"):
            fake.calls.append((method, path, None))
            raise state["APIRequestError"](status)
        return original(method, path, **kwargs)

    with pytest.raises(state["APIRequestError"]) as error:
        execute(state, mode="gpu", fake=reject_one_get)
    assert error.value.status_code == status
    assert len(fake.posts) == 1
    assert sum(c[0] == "GET" and c[1].startswith("/v1/jobs/") for c in fake.calls) == 1


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_transient_poll_http_get_retries_with_no_paid_repost(monkeypatch, status):
    gpu_environment(monkeypatch)
    state, fake = initialize(), FakeGateway()
    original = fake.__call__
    failures = []
    slept = []

    def transient(method, path, **kwargs):
        if method == "GET" and path.startswith("/v1/jobs/") and not failures:
            failures.append(status)
            fake.calls.append((method, path, None))
            raise state["APIRequestError"](status, retry_after_seconds=3)
        return original(method, path, **kwargs)

    monkeypatch.setattr(state["time"], "sleep", slept.append)
    execute(state, mode="gpu", fake=transient)
    assert len(fake.posts) == 5
    assert failures == [status]
    assert slept == [3] if status == 429 else slept == [1]


def test_repeated_poll_429_is_bounded_no_repost(monkeypatch):
    gpu_environment(monkeypatch)
    state, fake = initialize(), FakeGateway()
    original = fake.__call__
    slept = []

    def always_rate_limited(method, path, **kwargs):
        if method == "GET" and path.startswith("/v1/jobs/"):
            raise state["APIRequestError"](429, retry_after_seconds=1)
        return original(method, path, **kwargs)

    monkeypatch.setattr(state["time"], "sleep", slept.append)
    with pytest.raises(RuntimeError, match="GET.*lỗi tạm thời|transient GET"):
        execute(state, mode="gpu", fake=always_rate_limited)
    assert len(fake.posts) == 1
    assert len(slept) == state["MAX_POLL_TRANSIENT_ERRORS"]


def test_network_glitch_during_get_is_retryable_but_post_never_retried(monkeypatch):
    gpu_environment(monkeypatch)
    state, fake = initialize(), FakeGateway()
    original = fake.__call__
    failures = []
    monkeypatch.setattr(state["time"], "sleep", lambda seconds: None)

    def flaky(method, path, **kwargs):
        if method == "GET" and path.startswith("/v1/jobs/") and not failures:
            failures.append(1)
            raise state["NetworkRequestError"]("safe synthetic failure")
        return original(method, path, **kwargs)

    execute(state, mode="gpu", fake=flaky)
    assert len(fake.posts) == 5
    assert failures == [1]


def test_poll_retry_after_longer_than_remaining_deadline_fails_early(monkeypatch):
    gpu_environment(monkeypatch)
    state, fake = initialize(), FakeGateway()
    original = fake.__call__

    def throttled(method, path, **kwargs):
        if method == "GET" and path.startswith("/v1/jobs/"):
            raise state["APIRequestError"](429, retry_after_seconds=86400)
        return original(method, path, **kwargs)

    state["POLL_TIMEOUT_SECONDS"] = 4
    with pytest.raises(TimeoutError, match="GET|Polling"):
        execute(state, mode="gpu", fake=throttled)
    assert len(fake.posts) == 1


@pytest.mark.parametrize("behavior", ["mismatched_uuid", "empty_runs", "wrong_kind"])
def test_invalid_job_responses_fail_safely_before_benchmark(monkeypatch, behavior):
    gpu_environment(monkeypatch)
    state, fake = initialize(), FakeGateway()
    original = fake.__call__

    def corrupted(method, path, **kwargs):
        status, result = original(method, path, **kwargs)
        if method == "GET" and path.startswith("/v1/jobs/"):
            result = dict(result)
            if behavior == "mismatched_uuid":
                result["job_id"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
            elif behavior == "empty_runs":
                result["runs"] = []
                # Avoid waiting for 20m; fail fast using short deadline.
            else:
                result["kind"] = "benchmark"
        return status, result

    if behavior == "empty_runs":
        state["POLL_TIMEOUT_SECONDS"] = 0.001
    with pytest.raises((ValueError, RuntimeError, TimeoutError)):
        execute(state, mode="gpu", fake=corrupted)
    assert len(fake.posts) == 1


@pytest.mark.parametrize("status", [401, 403, 409, 422, 429, 503, 504])
def test_real_request_http_errors_are_sanitized_and_do_not_echo_body(monkeypatch, status):
    from email.message import Message
    from urllib.error import HTTPError

    gpu_environment(monkeypatch)
    state = initialize()
    state["API_BASE_URL"] = "https://translation.example.test"
    state["API_TOKEN"] = "synthetic-private-test-token-123456"
    response_headers = Message()
    response_headers.add_header("Retry-After", "7")
    private = "SENSITIVE_REQUEST_BODY_DO_NOT_EXPOSE"

    class RejectedOpener:
        def open(self, request, timeout):
            raise HTTPError(
                request.full_url, status,
                "private " + private, response_headers, None,
            )

    state["_OPENER"] = RejectedOpener()
    with pytest.raises(state["APIRequestError"]) as error:
        state["_LIVE_REQUEST"]("GET", "/v1/jobs/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                               authenticated=True)
    assert str(status) in str(error.value)
    assert private not in str(error.value)
    assert "synthetic-private-test-token-123456" not in str(error.value)
    assert error.value.retry_after_seconds == (7 if status == 429 else None)


def test_live_client_sets_cloudflare_safe_user_agent_without_exposing_token(monkeypatch):
    """Use an explicit API client signature instead of urllib's default."""
    gpu_environment(monkeypatch)
    state = initialize()
    state["API_BASE_URL"] = "https://own-modal-gateway.example.test"
    state["API_TOKEN"] = "synthetic-private-test-token-123456"
    seen = []

    class Response:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def read(self):
            return b'{"status":"ok"}'

    class Opener:
        def open(self, request, timeout):
            seen.append(request)
            return Response()

    state["_OPENER"] = Opener()
    status, data = state["_LIVE_REQUEST"]("GET", "/health")
    assert (status, data["status"]) == (200, "ok")
    assert len(seen) == 1
    assert seen[0].get_header("User-agent") == "Multilingual-Translation-Notebook/1.0"
    assert seen[0].get_header("Authorization") is None


def test_http_403_gives_safe_troubleshooting_hint(monkeypatch):
    gpu_environment(monkeypatch)
    state = initialize()
    error = state["APIRequestError"](403)
    assert "Cloudflare" in str(error)
    assert "Modal" in str(error)
    assert "synthetic-private-test-token" not in str(error)
