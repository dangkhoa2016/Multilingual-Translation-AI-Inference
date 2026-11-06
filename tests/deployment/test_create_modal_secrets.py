"""Offline checks for the private .env -> Modal Secret onboarding workflow."""
import os
import sys
from types import SimpleNamespace

import pytest

from scripts.deployment import create_modal_secrets as setup


def env_file(tmp_path, extra="", runtime=None, migration=None, token=None):
    path = tmp_path / ".env"
    path.write_text(
        f"{setup.DB}='{runtime or 'postgresql+psycopg://user:password@pool.example/translation?sslmode=require'}'\n"
        f"{setup.MIGRATE}='{migration or 'postgresql+psycopg://user:password@direct.example/translation?sslmode=require'}'\n"
        f"{setup.TOKEN}='{token or 'ExamplePersonalBearerToken123456789!'}'\n"
        f"{setup.MODE}=inline-mock\n"
        f"{extra}\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


class FakeSecretManager:
    def __init__(self, existing=(), fail_after=None):
        self.existing = tuple(existing)
        self.created = []
        self.fail_after = fail_after

    def list(self, **kwargs):
        assert kwargs["environment_name"] == "test-env"
        return [SimpleNamespace(name=n) for n in self.existing]

    def create(self, name, data, **kwargs):
        if self.fail_after is not None and len(self.created) >= self.fail_after:
            raise RuntimeError("Secret might contain secret values")
        assert kwargs == {"allow_existing": False, "environment_name": "test-env"}
        self.created.append((name, data))


def fake_modal(monkeypatch, manager):
    monkeypatch.setitem(sys.modules, "modal", SimpleNamespace(Secret=SimpleNamespace(objects=manager)))
    return manager


def test_dry_run_is_offline_and_leaves_modal_untouched(tmp_path, monkeypatch, capsys):
    manager = fake_modal(monkeypatch, FakeSecretManager())
    path = env_file(tmp_path)
    assert setup.main(["--env-file", str(path)]) == 0
    assert not manager.created
    output = capsys.readouterr().out
    assert "Dry run" in output
    assert "password" not in output
    assert "ExamplePersonalBearerToken" not in output


def test_prepares_only_approved_settings_no_migration_no_gpu(tmp_path):
    path = env_file(tmp_path,
                    extra="TRANSLATION_MAX_JOBS_PER_DAY=42\n"
                          "TRANSLATION_AUDIT_LOG_ENABLED=true\n"
                          "UNRELATED_SECRET='must-not-leak'\n")
    database, api = setup.prepare(setup.read_dotenv(path))
    assert database == {setup.DB: setup.read_dotenv(path)[setup.DB]}
    assert setup.MIGRATE not in database and setup.MIGRATE not in api
    assert api[setup.MODE] == "modal-cpu-mock"
    assert api["TRANSLATION_MAX_JOBS_PER_DAY"] == "42"
    assert api["TRANSLATION_AUDIT_LOG_ENABLED"] == "true"
    assert "UNRELATED_SECRET" not in api


def test_apply_creates_only_two_new_named_secrets(tmp_path, monkeypatch):
    manager = fake_modal(monkeypatch, FakeSecretManager())
    path = env_file(tmp_path)
    assert setup.main(["--env-file", str(path), "--profile", "test-profile",
                       "--environment", "test-env", "--apply"]) == 0
    assert [item[0] for item in manager.created] == [
        setup.MODAL_POSTGRESQL_CONNECTION_SECRET_NAME,
        setup.MODAL_API_AUTH_SECRET_NAME,
    ]
    assert setup.MIGRATE not in str(manager.created)
    assert manager.created[1][1][setup.MODE] == "modal-cpu-mock"
    assert os.environ["MODAL_PROFILE"] == "test-profile"


@pytest.mark.parametrize("existing", [
    (setup.MODAL_API_AUTH_SECRET_NAME,), (setup.MODAL_POSTGRESQL_CONNECTION_SECRET_NAME,),
    (setup.MODAL_API_AUTH_SECRET_NAME, setup.MODAL_POSTGRESQL_CONNECTION_SECRET_NAME),
])
def test_existing_secrets_are_never_overwritten(tmp_path, monkeypatch, existing):
    manager = fake_modal(monkeypatch, FakeSecretManager(existing=existing))
    with pytest.raises(setup.SetupError, match="already exists"):
        setup.main(["--env-file", str(env_file(tmp_path)), "--profile", "p",
                    "--environment", "test-env", "--apply"])
    assert not manager.created


def test_second_creation_failure_reports_partial_state_without_secrets(tmp_path, monkeypatch):
    manager = fake_modal(monkeypatch, FakeSecretManager(fail_after=1))
    with pytest.raises(setup.SetupError, match="might exist") as exc:
        setup.main(["--env-file", str(env_file(tmp_path)), "--profile", "p",
                    "--environment", "test-env", "--apply"])
    assert len(manager.created) == 1
    assert "password" not in str(exc.value)


def test_missing_migration_url_is_rejected(tmp_path):
    path = env_file(tmp_path)
    path.write_text(path.read_text().replace(f"{setup.MIGRATE}=", "DISABLED_MIGRATE="))
    with pytest.raises(setup.SetupError, match=setup.MIGRATE):
        setup.prepare(setup.read_dotenv(path))


def test_postgresql_database_mismatch_is_rejected(tmp_path):
    path = env_file(tmp_path, migration="postgresql://user:password@direct.example/other")
    with pytest.raises(setup.SetupError, match="same PostgreSQL database"):
        setup.prepare(setup.read_dotenv(path))


def test_sqlite_url_or_placeholder_is_rejected(tmp_path):
    for runtime in ("sqlite:///mock.db", "postgresql://DB_USER:pw@RUNTIME_HOST/translation"):
        path = env_file(tmp_path, runtime=runtime)
        with pytest.raises(setup.SetupError):
            setup.prepare(setup.read_dotenv(path))


def test_invalid_quota_and_unsafe_permissions_fail(tmp_path):
    path = env_file(tmp_path, extra="TRANSLATION_MAX_JOBS_PER_DAY=0")
    with pytest.raises(setup.SetupError, match="runtime options"):
        setup.prepare(setup.read_dotenv(path))
    if os.name == "posix":
        path.chmod(0o644)
        with pytest.raises(setup.SetupError, match="chmod 600"):
            setup.read_dotenv(path)


def test_duplicate_required_key_is_rejected(tmp_path):
    path = env_file(tmp_path, extra=f"{setup.TOKEN}='ExtraReplacementTokenExample123456789'\n")
    with pytest.raises(setup.SetupError, match="Duplicate"):
        setup.read_dotenv(path)


def test_malformed_quote_is_rejected_without_exposing_value(tmp_path):
    path = env_file(tmp_path, extra="TRANSLATION_MAX_JOBS_PER_DAY='sensitive-value")
    with pytest.raises(setup.SetupError, match="Invalid quotes") as exc:
        setup.read_dotenv(path)
    assert "sensitive-value" not in str(exc.value)


@pytest.mark.parametrize("suffix", ["#suffix", "\\literal#suffix", "!", "_long#piece"])
def test_unquoted_token_is_preserved_byte_for_byte_before_provisioning(tmp_path, suffix):
    token = "synthetic-printable-token-123456" + suffix
    path = env_file(tmp_path, token=token)
    old = f"{setup.TOKEN}='{token}'"
    assert old in path.read_text()
    path.write_text(path.read_text().replace(old, f"{setup.TOKEN}={token}"))
    values = setup.read_dotenv(path)
    assert values[setup.TOKEN] == token
    database, api = setup.prepare(values)
    assert api[setup.TOKEN] == token
    assert setup.TOKEN not in database


def test_unquoted_comment_after_whitespace_and_duplicates_are_distinct(tmp_path):
    path = env_file(tmp_path, extra="TRANSLATION_MAX_JOBS_PER_DAY=42 # operator note")
    assert setup.read_dotenv(path)["TRANSLATION_MAX_JOBS_PER_DAY"] == "42"
    duplicate = path.read_text() + f"{setup.TOKEN}=another-synthetic-token-123456\n"
    path.write_text(duplicate)
    with pytest.raises(setup.SetupError, match="Duplicate"):
        setup.read_dotenv(path)
