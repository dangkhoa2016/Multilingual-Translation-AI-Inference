"""Offline provisioning safety: never fall back to the wrong Modal environment."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/deployment/create_volumes.sh"


def test_no_confirmation_does_not_invoke_modal(tmp_path):
    env = {
        **os.environ,
        "MODAL_PROFILE": "gmanley943",
        "MODAL_ENVIRONMENT": "Multilingual-Translation-AI-Inference",
    }
    env.pop("CONFIRM_TRANSLATION_GPU_VOLUME_CREATION", None)
    proc = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert proc.returncode == 2


def test_confirmation_requires_explicit_profile_and_environment(tmp_path):
    env = {**os.environ, "CONFIRM_TRANSLATION_GPU_VOLUME_CREATION": "YES"}
    env.pop("MODAL_PROFILE", None)
    env.pop("MODAL_ENVIRONMENT", None)
    proc = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert proc.returncode != 0
    assert "MODAL_PROFILE" in proc.stderr


def test_four_volumes_target_the_same_explicit_environment(tmp_path):
    fake_cli = tmp_path / "modal"
    args_log = tmp_path / "argv.txt"
    fake_cli.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> \"$TEST_LOG_PATH\"\n")
    fake_cli.chmod(0o700)
    profile = "gmanley943"
    environment = "Multilingual-Translation-AI-Inference"
    env = {
        **os.environ,
        "PATH": str(tmp_path) + os.pathsep + os.environ.get("PATH", ""),
        "MODAL_PROFILE": profile,
        "MODAL_ENVIRONMENT": environment,
        "CONFIRM_TRANSLATION_GPU_VOLUME_CREATION": "YES",
        "TEST_LOG_PATH": str(args_log),
    }
    subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, check=True)
    calls = args_log.read_text().splitlines()
    assert len(calls) == 4
    assert all(call.startswith(f"volume create --profile {profile} --env {environment} ")
               for call in calls)
    assert len({call.split()[-1] for call in calls}) == 4
