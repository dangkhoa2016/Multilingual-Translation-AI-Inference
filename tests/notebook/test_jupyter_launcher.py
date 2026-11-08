"""Offline tests for Jupyter launcher; no real Jupyter process or private values."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts" / "examples" / "launch_jupyter_private.py"


def load_launcher():
    spec = importlib.util.spec_from_file_location("public_local_jupyter_launcher", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_inherits_private_environment_without_cli_args_or_outputs(monkeypatch, capsys):
    mod = load_launcher()
    secret = "TEST_ONLY_PRIVATE_CREDENTIAL"
    gateway = "https://private-gateway.example.test"
    calls = []
    monkeypatch.setattr(mod.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda prompt: gateway)
    monkeypatch.setattr(mod, "getpass", lambda prompt: secret)
    monkeypatch.setattr(mod.os, "execvpe", lambda *args: calls.append(args))
    mod.main()
    assert len(calls) == 1
    executable, args, environment = calls[0]
    assert executable == sys.executable
    assert args[:4] == [sys.executable, "-m", "jupyter", "lab"]
    assert Path(args[4]).name == "translation_api_demo.ipynb"
    assert environment["TRANSLATION_GATEWAY_BASE_URL"] == gateway
    assert environment["TRANSLATION_API_BEARER_TOKEN"] == secret
    assert secret not in " ".join(args)
    assert secret not in capsys.readouterr().out
    assert secret not in __import__("os").environ


@pytest.mark.parametrize("invalid", ["http://localhost", "https://user:pass@example.com",
                                      "https://example.com/private", "https://example.com/?key=x"])
def test_launcher_rejects_nonroot_or_insecure_url(monkeypatch, invalid):
    mod = load_launcher()
    monkeypatch.setattr(mod.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda prompt: invalid)
    monkeypatch.setattr(mod, "getpass", lambda prompt: pytest.fail("Token must not be requested"))
    monkeypatch.setattr(mod.os, "execvpe", lambda *args: pytest.fail("Jupyter must not run"))
    with pytest.raises(SystemExit, match="HTTPS gateway"):
        mod.main()


def test_launcher_rejects_noninteractive_and_empty_token(monkeypatch):
    mod = load_launcher()
    monkeypatch.setattr(mod.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    with pytest.raises(SystemExit, match="interactive terminal"):
        mod.main()
    monkeypatch.setattr(mod.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda prompt: "https://gateway.example.test")
    monkeypatch.setattr(mod, "getpass", lambda prompt: "  ")
    with pytest.raises(SystemExit, match="cannot be empty"):
        mod.main()
