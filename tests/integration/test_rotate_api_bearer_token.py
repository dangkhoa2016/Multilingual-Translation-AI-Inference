"""Offline tests for token rotation; no Modal SDK, network, or GPU is required."""

import io
import sys
import types
import urllib.error
from pathlib import Path

import pytest

from scripts.deployment import rotate_api_bearer_token as token_rotation


@pytest.fixture
def rotation():
    return token_rotation


def private_token(path, value, *, extra=""):
    path.write_text(f"TRANSLATION_API_BEARER_TOKEN={value}\n{extra}")
    path.chmod(0o600)
    return str(path)


def test_dry_run_never_contacts_modal_or_http(rotation, monkeypatch, tmp_path, capsys):
    old = private_token(tmp_path / "old.env", "old-secret-token-012345")
    new = private_token(tmp_path / "new.env", "new-secret-token-123456")
    monkeypatch.setattr(rotation, "_http_status", lambda *a, **kw: pytest.fail("called HTTP"))
    monkeypatch.setattr(rotation, "_update_token", lambda *a, **kw: pytest.fail("called Modal"))
    monkeypatch.setattr(rotation, "_rollover", lambda *a, **kw: pytest.fail("called rollover"))
    assert rotation.main([
        "--current-token-env-file", old, "--new-token-env-file", new,
        "--profile", "test-profile", "--environment", "staging",
    ]) == 0
    out = capsys.readouterr().out
    assert "Dry-run only" in out
    assert "old-secret-token" not in out and "new-secret-token" not in out


@pytest.mark.parametrize("secret", ["short", "a" * 15, "a" * 4097, "a" * 12 + " " + "b" * 12,
                                   "a" * 20 + "\u00e9", "abc\n" + "x" * 20])
def test_rejects_invalid_token_without_echo(rotation, tmp_path, secret):
    file = private_token(tmp_path / "bad.env", secret)
    with pytest.raises(rotation.RotationError) as error:
        rotation._read_private_token(file, new_file=True)
    assert secret not in str(error.value)


def test_rejects_world_readable_symlink_and_extraneous_new_keys(rotation, tmp_path):
    file = Path(private_token(tmp_path / "secret.env", "synthetic-strong-secret-123"))
    file.chmod(0o644)
    with pytest.raises(rotation.RotationError, match="permissions"):
        rotation._read_private_token(str(file), new_file=True)
    file.chmod(0o600)
    symlink = tmp_path / "symlink"
    symlink.symlink_to(file)
    with pytest.raises(rotation.RotationError, match="regular files"):
        rotation._read_private_token(str(symlink), new_file=True)
    private_token(file, "synthetic-strong-secret-123", extra="OTHER_VARIABLE=secret-value\n")
    with pytest.raises(rotation.RotationError, match="only the API token key"):
        rotation._read_private_token(str(file), new_file=True)
    assert rotation._read_private_token(str(file), new_file=False) == "synthetic-strong-secret-123"


def test_same_old_and_new_token_is_safe_noop(rotation, tmp_path, capsys):
    old = private_token(tmp_path / "old.env", "same-secret-0123456789")
    new = private_token(tmp_path / "new.env", "same-secret-0123456789")
    assert rotation.main(["--current-token-env-file", old, "--new-token-env-file", new,
                          "--profile", "test", "--environment", "dev"]) == 1
    assert "same-secret" not in capsys.readouterr().out


def test_apply_requires_operator_confirmation(rotation, tmp_path):
    old = private_token(tmp_path / "old.env", "old-secret-token-012345")
    new = private_token(tmp_path / "new.env", "new-secret-token-123456")
    assert rotation.main(["--current-token-env-file", old, "--new-token-env-file", new,
                          "--profile", "test", "--environment", "dev",
                          "--base-url", "https://gateway.modal.run", "--apply"]) == 1


def test_safe_preflight_never_posts_or_calls_gpu(rotation, monkeypatch):
    observed = []

    def fake_open(request, timeout):
        observed.append((request.get_method(), request.full_url, request.get_header("Authorization")))
        raise urllib.error.HTTPError(request.full_url, 422, "validation", {}, io.BytesIO(b""))

    monkeypatch.setattr(rotation, "_credential_open", fake_open)
    assert rotation._http_status("https://gateway.example", "synthetic-token-0123456789") == 422
    assert observed == [("GET", "https://gateway.example/v1/jobs/not-a-uuid",
                         "Bearer synthetic-token-0123456789")]


def test_single_key_modal_merge_respects_profile_and_environment(rotation, monkeypatch):
    recorded = []

    class FakeSecret:
        def update(self, payload):
            recorded.append(("update", payload.copy()))

    class FakeModalSecret:
        @staticmethod
        def from_name(name, *, environment_name, required_keys):
            recorded.append(("lookup", name, environment_name, required_keys.copy()))
            return FakeSecret()

    monkeypatch.setitem(sys.modules, "modal", types.SimpleNamespace(Secret=FakeModalSecret))
    rotation._update_token("synthetic-new-token-12345", profile="profile-1", environment="prod")
    assert recorded == [
        ("lookup", "multilingual-translation-ai-inference-api-authentication", "prod",
         ["TRANSLATION_API_BEARER_TOKEN"]),
        ("update", {"TRANSLATION_API_BEARER_TOKEN": "synthetic-new-token-12345"}),
    ]
    assert rotation.os.environ["MODAL_PROFILE"] == "profile-1"
    assert rotation.os.environ["MODAL_ENVIRONMENT"] == "prod"


def test_rollover_recreates_containers_and_hides_failed_cli_output(rotation, monkeypatch):
    captured = []

    def fake_run(command, **kwargs):
        captured.append((command, kwargs))
        return types.SimpleNamespace(returncode=1, stdout="private-token", stderr="private-token")

    monkeypatch.setattr(rotation.subprocess, "run", fake_run)
    with pytest.raises(rotation.RotationError) as error:
        rotation._rollover(profile="p", environment="e")
    assert "private-token" not in str(error.value)
    assert captured[0][0] == [
        "modal", "app", "rollover",
        "multilingual-translation-ai-inference-api-and-model-workers",
        "--strategy", "recreate", "--profile", "p", "--env", "e",
    ]
    assert captured[0][1]["capture_output"] is True


def test_rotation_success_and_old_token_rejection(rotation, monkeypatch, capsys):
    events = []
    current = {"value": "old-token"}

    def status(_, token):
        return 422 if token == current["value"] else 401

    def update(token, **kwargs):
        events.append(("update", token))
        current["value"] = token

    def rollover(**kwargs):
        events.append(("rollover", kwargs["environment"]))

    monkeypatch.setattr(rotation, "_health", lambda _: {"status": "ok", "inference_enabled": False})
    monkeypatch.setattr(rotation, "_http_status", status)
    monkeypatch.setattr(rotation, "_update_token", update)
    monkeypatch.setattr(rotation, "_rollover", rollover)
    rotation.rotate(base_url="https://gateway.example", profile="p", environment="e",
                    old_token="old-token", new_token="new-token")
    assert events == [("update", "new-token"), ("rollover", "e")]
    assert "old-token" not in capsys.readouterr().out


def test_failed_rotation_attempts_old_token_rollback(rotation, monkeypatch, capsys):
    events = []
    active = {"value": "old-token"}
    monkeypatch.setattr(rotation, "_health", lambda _: {"status": "ok"})
    monkeypatch.setattr(rotation, "_http_status", lambda _, token: 422 if token == active["value"] else 401)

    def update(token, **kwargs):
        events.append(("update", token))
        active["value"] = token

    def rollover(**kwargs):
        events.append(("rollover", "recreate"))
        if active["value"] == "new-token":
            raise RuntimeError("secret:new-token")

    monkeypatch.setattr(rotation, "_update_token", update)
    monkeypatch.setattr(rotation, "_rollover", rollover)
    with pytest.raises(rotation.RotationError, match="details withheld") as error:
        rotation.rotate(base_url="https://gateway.example", profile="p", environment="e",
                        old_token="old-token", new_token="new-token")
    assert "new-token" not in str(error.value)
    assert active["value"] == "old-token"
    assert events == [("update", "new-token"), ("rollover", "recreate"),
                      ("update", "old-token"), ("rollover", "recreate")]
    assert "new-token" not in capsys.readouterr().out

@pytest.mark.parametrize('url', [
    'http://gateway.modal.run',
    'https://gateway.modal.run/v1/models',
    'https://user:secret@gateway.modal.run',
    'https://gateway.modal.run?token=private',
    'https://gateway.modal.run#fragment',
    'https://example.com',
])
def test_apply_rejects_unsafe_or_unexpected_gateway_url(rotation, tmp_path, url, monkeypatch):
    old = private_token(tmp_path / 'old.env', 'old-synthetic-token-123456')
    new = private_token(tmp_path / 'new.env', 'new-synthetic-token-123456')
    monkeypatch.setattr(rotation, 'rotate', lambda **kw: pytest.fail('Network/apply should be denied'))
    assert rotation.main([
        '--current-token-env-file', old, '--new-token-env-file', new,
        '--profile', 'p', '--environment', 'e', '--base-url', url,
        '--apply', '--confirm-job-interruption',
    ]) == 1


def test_custom_gateway_host_requires_explicit_ack(rotation, tmp_path, monkeypatch):
    old = private_token(tmp_path / 'old.env', 'old-synthetic-token-123456')
    new = private_token(tmp_path / 'new.env', 'new-synthetic-token-123456')
    received = []
    monkeypatch.setattr(rotation, 'rotate', lambda **kw: received.append(kw))
    assert rotation.main([
        '--current-token-env-file', old, '--new-token-env-file', new,
        '--profile', 'p', '--environment', 'e', '--base-url', 'https://api.example.com',
        '--apply', '--confirm-job-interruption', '--allow-custom-gateway-host',
    ]) == 0
    assert len(received) == 1


@pytest.mark.parametrize("target", ["rotation", "dispatcher"])
def test_credential_probe_never_follows_cross_origin_redirect(monkeypatch, target):
    """Exercise a real urllib opener, simulated HTTPS, and a 302 Location."""
    import urllib.request
    import urllib.response

    from scripts.deployment import set_dispatch_mode as dispatcher

    module = token_rotation if target == "rotation" else dispatcher
    actual_build_opener = urllib.request.build_opener
    observed = []

    class FakeHTTPSHandler(urllib.request.HTTPSHandler):
        def https_open(self, request):
            observed.append((request.full_url, request.get_header("Authorization")))
            headers = {"Location": "https://another-origin.example.test/credential-target"}
            response = urllib.response.addinfourl(
                io.BytesIO(b""), headers, request.full_url, code=302
            )
            response.msg = "Found"
            return response

    def fake_build_opener(*handlers):
        return actual_build_opener(*handlers, FakeHTTPSHandler())

    monkeypatch.setattr(module.urllib.request, "build_opener", fake_build_opener)
    if target == "rotation":
        assert module._http_status("https://gateway.modal.run",
                                   "synthetic-bearer-123456") == 302
    else:
        with pytest.raises(RuntimeError, match="authentication check failed"):
            module._check_authenticated(
                "https://gateway.modal.run", "synthetic-bearer-123456"
            )
    assert len(observed) == 1
    assert observed[0][0].startswith("https://gateway.modal.run/")
    assert observed[0][1] == "Bearer synthetic-bearer-123456"


@pytest.mark.parametrize("policy", ["auth-failure-limit-one", "peer-limit-one"])
def test_throttled_revocation_keeps_verified_new_token_without_rollback(
    rotation, monkeypatch, capsys, policy
):
    """429 can precede auth; it never confirms revocation or triggers rollback."""
    current = {"token": "old-token"}
    updates = []

    def status(_, token):
        if token == current["token"]:
            return 422
        return 429 if policy in ("auth-failure-limit-one", "peer-limit-one") else 401

    monkeypatch.setattr(rotation, "_health", lambda _: {"status": "ok"})
    monkeypatch.setattr(rotation, "_http_status", status)
    monkeypatch.setattr(rotation.time, "sleep", lambda seconds: None)

    def update(token, **kwargs):
        current["token"] = token
        updates.append(token)

    monkeypatch.setattr(rotation, "_update_token", update)
    monkeypatch.setattr(rotation, "_rollover", lambda **kwargs: None)
    with pytest.raises(rotation.RotationVerificationThrottled):
        rotation.rotate(base_url="https://gateway.example", profile="p", environment="e",
                        old_token="old-token", new_token="new-token")
    assert updates == ["new-token"]
    assert current["token"] == "new-token"
    output = capsys.readouterr().out
    assert "revocation could not be verified" in output
    assert "old-token" not in output and "new-token" not in output


def test_new_token_rate_limit_remains_unconfirmed_without_restoring_old(
    rotation, monkeypatch, capsys
):
    current = {"token": "old-token"}
    updates = []
    monkeypatch.setattr(rotation, "_health", lambda _: {"status": "ok"})

    def status(_, token):
        if current["token"] == "old-token":
            return 422 if token == "old-token" else 401
        return 429

    monkeypatch.setattr(rotation, "_http_status", status)
    monkeypatch.setattr(rotation.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(rotation, "_update_token",
                        lambda token, **kwargs: (updates.append(token), current.update(token=token)))
    monkeypatch.setattr(rotation, "_rollover", lambda **kwargs: None)
    with pytest.raises(rotation.RotationVerificationThrottled):
        rotation.rotate(base_url="https://gateway.example", profile="p", environment="e",
                        old_token="old-token", new_token="new-token")
    assert updates == ["new-token"]
    assert "unconfirmed" in capsys.readouterr().out


@pytest.mark.parametrize("throttle", ["new", "previous"])
def test_rotation_cli_returns_unverified_exit_code_without_rollback(
    rotation, monkeypatch, tmp_path, capsys, throttle
):
    old, new = "old-secret-token-012345", "new-secret-token-123456"
    old_file = private_token(tmp_path / "old.env", old)
    new_file = private_token(tmp_path / "new.env", new)
    current = {"value": old}
    updates = []

    def status(_, candidate):
        if current["value"] == old:
            return 422 if candidate == old else 401
        if throttle == "new":
            return 429
        return 422 if candidate == new else 429

    def update(token, **kwargs):
        current["value"] = token
        updates.append(token)

    monkeypatch.setattr(rotation, "_health", lambda _: {"status": "ok"})
    monkeypatch.setattr(rotation, "_http_status", status)
    monkeypatch.setattr(rotation, "_update_token", update)
    monkeypatch.setattr(rotation, "_rollover", lambda **kwargs: None)
    monkeypatch.setattr(rotation.time, "sleep", lambda _: None)
    code = rotation.main([
        "--current-token-env-file", old_file,
        "--new-token-env-file", new_file,
        "--profile", "synthetic-profile",
        "--environment", "synthetic-environment",
        "--base-url", "https://gateway.modal.run",
        "--apply", "--confirm-job-interruption",
    ])
    assert code == 2
    assert updates == [new]
    assert current["value"] == new
    output = capsys.readouterr().out
    assert "UNVERIFIED:" in output and "WARNING:" in output
    assert old not in output and new not in output
