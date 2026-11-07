"""Inspect only nonsecret Modal dispatcher-mode setting in an ephemeral CPU call.

Never print authentication tokens or database credentials.
  modal run --profile YOUR_PROFILE scripts/verify_modal_auth_dispatch_secret.py
"""
import os

import modal

app = modal.App("translation-ai-inference-dispatcher-secret-check")
auth = modal.Secret.from_name("translation-ai-inference-api-authentication")


@app.function(image=modal.Image.debian_slim(python_version="3.12"), secrets=[auth],
              cpu=0.5, memory=256, timeout=60, min_containers=0, max_containers=1)
def effective_dispatch_mode():
    mode = os.environ.get("TRANSLATION_DISPATCHER_MODE")
    if mode not in {"modal-gpu", "modal-cpu-mock", "record-only", "inline-mock"}:
        raise RuntimeError("Unexpected dispatcher mode in API Secret")
    return mode


@app.local_entrypoint()
def main():
    print("Current Modal API Secret dispatcher mode:", effective_dispatch_mode.remote())
