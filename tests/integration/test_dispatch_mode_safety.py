"""CPU-only tests for a single-key Modal Secret dispatcher update."""
import subprocess
import sys

import pytest

from scripts.deployment import set_dispatch_mode as switch


def test_update_mode_only_updates_dispatcher_key(monkeypatch):
    captured = []

    def fake_run(argv, *, profile=None, environment=None):
        captured.append((argv, profile, environment))

    monkeypatch.setattr(switch, "_run_safely", fake_run)
    switch._update_mode("modal-gpu", profile="test-profile", environment="dev")
    argv, profile, environment = captured.pop()
    assert argv[:2] == [sys.executable, "-c"]
    assert "modal.Secret.from_name" in argv[2]
    assert "TRANSLATION_DISPATCHER_MODE" in argv[2]
    assert "modal-gpu" in argv[2]
    assert "TRANSLATION_API_BEARER_TOKEN" not in argv[2]
    assert "--force" not in argv[2]
    assert profile == "test-profile"
    assert environment == "dev"
    with pytest.raises(ValueError, match="Unsupported"):
        switch._update_mode("not-a-mode")


def test_profile_is_selected_without_exposing_credentials(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(argv=argv, **kwargs)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(switch.subprocess, "run", fake_run)
    switch._run_safely(["modal", "secret", "list"], profile="p", environment="staging")
    assert seen["env"]["MODAL_PROFILE"] == "p"
    assert seen["env"]["MODAL_ENVIRONMENT"] == "staging"
    assert seen["capture_output"] is True
    assert "--profile" not in seen["argv"]


def test_cli_diagnostics_are_redacted(monkeypatch):
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, "", "SECRET_TOKEN=very-sensitive")

    monkeypatch.setattr(switch.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="output withheld") as err:
        switch._run_safely(["modal", "secret", "list"])
    assert "very-sensitive" not in str(err.value)


def _prepare(monkeypatch, *, current_gpu=False):
    monkeypatch.setattr(sys, "argv", [
        "set_dispatch_mode.py", "--to-gpu", "--apply",
        "--base-url", "https://example.modal.run", "--profile", "test-profile",
    ])
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", "test-token")
    events = []
    active = {"gpu": current_gpu}

    def health(base_url):
        assert base_url == "https://example.modal.run"
        return {"status": "ok", "inference_enabled": active["gpu"]}

    def authenticated(base_url, token):
        assert token == "test-token"

    def update(mode, **kwargs):
        events.append(("update", mode))
        active["gpu"] = mode == "modal-gpu"

    def rollover(**kwargs):
        events.append(("rollover", kwargs["profile"]))

    monkeypatch.setattr(switch, "_health", health)
    monkeypatch.setattr(switch, "_check_authenticated", authenticated)
    monkeypatch.setattr(switch, "_update_mode", update)
    monkeypatch.setattr(switch, "_rollover", rollover)
    return events, active


def test_default_dry_run_has_no_side_effects(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["set_dispatch_mode.py", "--to-gpu"])
    monkeypatch.delenv("TRANSLATION_API_BEARER_TOKEN", raising=False)
    switch.main()
    assert "Dry-run only" in capsys.readouterr().out


def test_apply_updates_mode_and_rolls_containers(monkeypatch):
    events, active = _prepare(monkeypatch)
    switch.main()
    assert events == [("update", "modal-gpu"), ("rollover", "test-profile")]
    assert active["gpu"] is True


def test_already_correct_mode_is_noop(monkeypatch):
    events, _ = _prepare(monkeypatch, current_gpu=True)
    switch.main()
    assert events == []


def test_failed_or_uncertain_update_restores_previous_mode(monkeypatch):
    events, active = _prepare(monkeypatch)

    def uncertain_update(mode, **kwargs):
        events.append(("update", mode))
        active["gpu"] = mode == "modal-gpu"
        if mode == "modal-gpu":
            raise RuntimeError("lost acknowledgement")

    monkeypatch.setattr(switch, "_update_mode", uncertain_update)
    with pytest.raises(RuntimeError, match="lost acknowledgement"):
        switch.main()
    assert events == [
        ("update", "modal-gpu"), ("update", "modal-cpu-mock"),
        ("rollover", "test-profile"),
    ]
    assert active["gpu"] is False
