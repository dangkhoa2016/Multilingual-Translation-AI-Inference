"""CPU-only tests for optional Hugging Face credential setup."""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

from multilingual_translation_ai_inference.resource_names import (
    MODAL_HUGGINGFACE_DOWNLOAD_SECRET_NAME,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/deployment/configure_huggingface_access.py"



def test_python_dotenv_is_declared_as_runtime_dependency():
    import tomllib

    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text())
    declared = configuration["project"]["dependencies"]
    assert any(requirement.startswith("python-dotenv>=") for requirement in declared)


@pytest.fixture
def helper():
    spec = importlib.util.spec_from_file_location("huggingface_setup_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stub_modal(monkeypatch, existing=()):
    created = []

    class Objects:
        def list(self, *, environment_name):
            return [types.SimpleNamespace(name=name) for name in existing]

        def create(self, name, values, **kwargs):
            created.append((name, values, kwargs))

    fake_modal = types.ModuleType("modal")
    fake_modal.Secret = types.SimpleNamespace(objects=Objects())
    monkeypatch.setitem(sys.modules, "modal", fake_modal)
    return created


def test_preview_never_reads_token_or_calls_modal(helper, monkeypatch, capsys):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    helper.create_secret(profile="gmanley943",
                         environment="Multilingual-Translation-AI-Inference",
                         apply=False, env_file=Path("/missing/private.env"))
    assert "no cloud operation" in capsys.readouterr().out


def test_apply_creates_only_one_hf_token_in_selected_environment(
    helper, monkeypatch, capsys
):
    created = stub_modal(monkeypatch)
    token = "hf_" + "A" * 36
    monkeypatch.setenv("HF_TOKEN", token)
    helper.create_secret(profile="gmanley943",
                         environment="Multilingual-Translation-AI-Inference",
                         apply=True, env_file=None)
    assert created == [(
        MODAL_HUGGINGFACE_DOWNLOAD_SECRET_NAME,
        {"HF_TOKEN": token},
        {"allow_existing": False,
         "environment_name": "Multilingual-Translation-AI-Inference"},
    )]
    assert token not in capsys.readouterr().out
    assert helper.os.environ["MODAL_PROFILE"] == "gmanley943"
    assert helper.os.environ["MODAL_ENVIRONMENT"] == "Multilingual-Translation-AI-Inference"


def test_existing_secret_refused_without_mutation(helper, monkeypatch):
    created = stub_modal(monkeypatch, existing=[MODAL_HUGGINGFACE_DOWNLOAD_SECRET_NAME])
    with pytest.raises(helper.SetupError, match="already exists"):
        helper.create_secret(profile="gmanley943", environment="test",
                             apply=True, env_file=None)
    assert not created


@pytest.mark.parametrize("raw", ["wrong", "hf_!", "token", "hf_123"])
def test_invalid_token_format_rejected(helper, monkeypatch, raw):
    monkeypatch.setenv("HF_TOKEN", raw)
    with pytest.raises(helper.SetupError, match="invalid format"):
        helper.read_token(None)


def test_private_dotenv_only_sends_token(helper, monkeypatch, tmp_path):
    import dotenv  # noqa: F401 - missing dependency must fail the test, never skip it.
    token = "hf_" + "B" * 36
    private_env = tmp_path / "credentials.env"
    private_env.write_text(
        "HF_TOKEN=" + token + "\n"
        "TRANSLATION_INFERENCE_DATABASE_URL=postgresql://do-not-copy\n"
        "TRANSLATION_API_BEARER_TOKEN=do-not-copy\n"
    )
    private_env.chmod(0o600)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    created = stub_modal(monkeypatch)
    helper.create_secret(profile="gmanley943", environment="test",
                         apply=True, env_file=private_env)
    assert created[0][1] == {"HF_TOKEN": token}


def test_publicly_readable_dotenv_refused(helper, tmp_path):
    private_env = tmp_path / "credentials.env"
    private_env.write_text("HF_TOKEN=hf_" + "C" * 36 + "\n")
    private_env.chmod(0o644)
    with pytest.raises(helper.SetupError, match="0600"):
        helper.read_token(private_env)


def test_missing_explicit_environment_rejected(helper):
    with pytest.raises(helper.SetupError, match="explicit"):
        helper.create_secret(profile="gmanley943", environment=" ",
                             apply=False, env_file=None)


def test_cli_preview_success(helper, capsys):
    result = helper.main(["--profile", "gmanley943",
                          "--environment", "Multilingual-Translation-AI-Inference"])
    assert result == 0
    assert "no cloud operation" in capsys.readouterr().out
