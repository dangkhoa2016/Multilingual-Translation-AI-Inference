import pytest
from notebook_test_support import FakeGateway, execute, gpu_environment, initialize


def test_offline_does_not_require_notebook_credentials(monkeypatch):
    monkeypatch.delenv("TRANSLATION_GATEWAY_BASE_URL", raising=False)
    monkeypatch.delenv("TRANSLATION_API_BEARER_TOKEN", raising=False)
    assert "FULL DEMO COMPLETED" in execute(initialize())

def test_gpu_uses_private_environment_credentials(monkeypatch):
    gpu_environment(monkeypatch)
    state = initialize()
    output = execute(state, mode="gpu", fake=FakeGateway())
    assert state["API_BASE_URL"] == "https://translation.example.test"
    assert "synthetic-private-test-token-123456" not in output

def test_missing_private_credential_is_rejected(monkeypatch):
    monkeypatch.delenv("TRANSLATION_UNKNOWN_TEST_KEY", raising=False)
    state = initialize()
    with pytest.raises(Exception):
        state["_secret"]("TRANSLATION_UNKNOWN_TEST_KEY")


def _unavailable_platform_secrets(monkeypatch):
    """Emulate Colab userdata timeout and missing Kaggle Secret, no real I/O."""
    import sys
    import types

    class TimeoutException(Exception):
        pass

    def colab_timeout(name):
        raise TimeoutException("PRIVATE_PROVIDER_DIAGNOSTIC_SHOULD_NOT_LEAK")

    google = types.ModuleType("google")
    google.__path__ = []
    colab = types.ModuleType("google.colab")
    colab.userdata = types.SimpleNamespace(get=colab_timeout)
    google.colab = colab
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.colab", colab)

    kaggle = types.ModuleType("kaggle_secrets")

    class EmptyKaggle:
        def get_secret(self, name):
            raise KeyError("not set")

    kaggle.UserSecretsClient = EmptyKaggle
    monkeypatch.setitem(sys.modules, "kaggle_secrets", kaggle)


def test_colab_timeout_falls_back_to_hidden_url_and_token_prompts(monkeypatch):
    import getpass

    for name in ("TRANSLATION_GATEWAY_BASE_URL", "TRANSLATION_API_BEARER_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    _unavailable_platform_secrets(monkeypatch)
    prompts = []

    def private_prompt(label):
        prompts.append(label)
        return ("https://translation.example.test" if len(prompts) == 1
                else "synthetic-private-test-token-123456")

    monkeypatch.setattr(getpass, "getpass", private_prompt)
    state, fake = initialize(), FakeGateway()
    output = execute(state, mode="gpu", fake=fake)
    assert len(prompts) == 2
    assert "URL" in prompts[0] and "Bearer" in prompts[1]
    assert len(fake.posts) == 5
    assert "FULL DEMO COMPLETED" in output
    assert "synthetic-private-test-token-123456" not in output
    assert "translation.example.test" not in output
    assert "PRIVATE_PROVIDER_DIAGNOSTIC_SHOULD_NOT_LEAK" not in output

    # No second prompt and no extra billable POST in the same kernel.
    execute(state, mode="gpu", fake=fake)
    assert len(prompts) == 2
    assert len(fake.posts) == 5


def test_only_missing_credential_is_prompted(monkeypatch):
    import getpass
    monkeypatch.setenv("TRANSLATION_GATEWAY_BASE_URL", "https://translation.example.test")
    monkeypatch.delenv("TRANSLATION_API_BEARER_TOKEN", raising=False)
    _unavailable_platform_secrets(monkeypatch)
    prompts = []

    def private_prompt(label):
        prompts.append(label)
        return "synthetic-private-test-token-123456"

    monkeypatch.setattr(getpass, "getpass", private_prompt)
    output = execute(initialize(), mode="gpu", fake=FakeGateway())
    assert len(prompts) == 1 and "Bearer" in prompts[0]
    assert "synthetic-private-test-token-123456" not in output


def test_environment_credentials_are_preferred_without_any_prompt(monkeypatch):
    import getpass
    gpu_environment(monkeypatch)
    _unavailable_platform_secrets(monkeypatch)

    def forbidden_prompt(label):
        raise AssertionError("Environment credentials should win")

    monkeypatch.setattr(getpass, "getpass", forbidden_prompt)
    execute(initialize(), mode="gpu", fake=FakeGateway())


def test_prompt_cancellation_fails_without_network_or_private_details(monkeypatch):
    import getpass
    monkeypatch.delenv("TRANSLATION_GATEWAY_BASE_URL", raising=False)
    monkeypatch.delenv("TRANSLATION_API_BEARER_TOKEN", raising=False)
    _unavailable_platform_secrets(monkeypatch)

    def interrupted(label):
        raise EOFError("SENSITIVE_BACKEND_DETAILS_SHOULD_NOT_LEAK")

    monkeypatch.setattr(getpass, "getpass", interrupted)
    fake = FakeGateway()
    with pytest.raises(RuntimeError) as error:
        execute(initialize(), mode="gpu", fake=fake)
    assert "SENSITIVE_BACKEND_DETAILS_SHOULD_NOT_LEAK" not in str(error.value)
    assert fake.calls == []


def test_empty_hidden_input_is_rejected_before_http(monkeypatch):
    import getpass
    monkeypatch.delenv("TRANSLATION_GATEWAY_BASE_URL", raising=False)
    monkeypatch.delenv("TRANSLATION_API_BEARER_TOKEN", raising=False)
    _unavailable_platform_secrets(monkeypatch)
    monkeypatch.setattr(getpass, "getpass", lambda label: "   ")
    fake = FakeGateway()
    with pytest.raises(RuntimeError, match="empty"):
        execute(initialize(), mode="gpu", fake=fake)
    assert fake.calls == []


def test_offline_run_all_never_opens_prompt_even_after_timeout(monkeypatch):
    import getpass
    _unavailable_platform_secrets(monkeypatch)

    def forbidden_prompt(label):
        raise AssertionError("Offline mode must not prompt for credentials")

    monkeypatch.setattr(getpass, "getpass", forbidden_prompt)
    execute(initialize(), mode="offline")


def test_noninteractive_getpass_warning_fails_without_echo_or_http(monkeypatch):
    import getpass

    monkeypatch.delenv("TRANSLATION_GATEWAY_BASE_URL", raising=False)
    monkeypatch.delenv("TRANSLATION_API_BEARER_TOKEN", raising=False)
    _unavailable_platform_secrets(monkeypatch)

    def no_hidden_input(label):
        raise getpass.GetPassWarning("PRIVATE_BACKEND_DETAIL_SHOULD_NOT_LEAK")

    monkeypatch.setattr(getpass, "getpass", no_hidden_input)
    fake = FakeGateway()
    with pytest.raises(RuntimeError) as raised:
        execute(initialize(), mode="gpu", fake=fake)
    assert "PRIVATE_BACKEND_DETAIL_SHOULD_NOT_LEAK" not in str(raised.value)
    assert not fake.calls


def test_manual_credential_reset_forces_next_hidden_prompt(monkeypatch):
    import getpass

    for name in ("TRANSLATION_GATEWAY_BASE_URL", "TRANSLATION_API_BEARER_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    _unavailable_platform_secrets(monkeypatch)
    supplied = iter((
        "https://translation.example.test", "synthetic-private-test-token-123456",
        "https://translation.example.test", "synthetic-private-test-token-123456",
    ))
    count = []
    def private_prompt(label):
        count.append(label)
        return next(supplied)
    monkeypatch.setattr(getpass, "getpass", private_prompt)
    state = initialize()
    fake = FakeGateway()
    execute(state, mode="gpu", fake=fake)
    assert len(count) == 2
    state["reset_demo_credentials"]()
    assert state["API_TOKEN"] == ""
    assert state["API_BASE_URL"] == ""
    execute(state, mode="gpu", fake=fake)
    assert len(count) == 4
    assert len(fake.posts) == 5


@pytest.mark.parametrize("code", [401, 403])
def test_rejected_manual_token_is_discarded_without_exposing_it(monkeypatch, code):
    from urllib.error import HTTPError

    gpu_environment(monkeypatch)
    state = initialize()
    token = "synthetic-private-test-token-123456"
    state["API_BASE_URL"] = "https://translation.example.test"
    state["API_TOKEN"] = token
    state["_NOTEBOOK_SESSION_SECRETS"]["TRANSLATION_API_BEARER_TOKEN"] = token
    class RejectedOpener:
        def open(self, request, timeout):
            raise HTTPError(request.full_url, code, "PRIVATE ERROR BODY", None, None)

    state["_OPENER"] = RejectedOpener()
    with pytest.raises(state["APIRequestError"]) as error:
        state["_LIVE_REQUEST"]("GET", "/v1/jobs/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", authenticated=True)
    assert str(code) in str(error.value)
    assert "TRANSLATION_API_BEARER_TOKEN" not in state["_NOTEBOOK_SESSION_SECRETS"]
    assert "PRIVATE ERROR BODY" not in str(error.value)
