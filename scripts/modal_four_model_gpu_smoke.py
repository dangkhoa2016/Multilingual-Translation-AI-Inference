"""Four isolated, opt-in L40S model *load* probes using verified GGUF Volumes.

This test does NOT replace the deployed CPU gateway or enable public routes.
Each model has a distinct Modal GPU function and Volume; no model downloading
occurs on GPU. Run individual models only AFTER CPU staging + full SHA256.

  modal run --profile YOUR_MODAL_PROFILE scripts/modal_four_model_gpu_smoke.py
  modal run --profile YOUR_MODAL_PROFILE scripts/modal_four_model_gpu_smoke.py --model index_35b --smoke
  modal run --profile YOUR_MODAL_PROFILE scripts/modal_four_model_gpu_smoke.py --all-models
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import modal

from scripts.modal_hy_mt2_gpu_smoke import BIN, REVISION
from scripts.modal_hy_mt2_gpu_smoke import image as verified_cuda_image
from translation_ai_inference.resource_names import (
    MODAL_GPU_INFERENCE_FUNCTION_NAMES,
    MODAL_GPU_WEIGHT_VOLUME_NAMES,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "models/four_l40s_workers_q8_0_manifest.json"
REPORT = ROOT / "reports/p4_four_l40s_models_runtime_smoke_v1.json"
app = modal.App("translation-ai-inference-four-model-l40s-smoke")
image = (
    verified_cuda_image
    .add_local_file(MANIFEST, "/opt/four_l40s_workers_q8_0_manifest.json")
    .add_local_python_source("scripts")
    .add_local_python_source("translation_ai_inference")
)
volumes = {
    key: modal.Volume.from_name(name)
    for key, name in MODAL_GPU_WEIGHT_VOLUME_NAMES.items()
}
MODEL_KEYS = ("hy_mt2_30b", "index_35b", "gemma4_31b_it", "qwen35_35b")

GPU_ARGS = {
    "image": image,
    "gpu": "L40S",
    "cpu": 4,
    "memory": 8192,
    "timeout": 650,
    "min_containers": 0,
    "buffer_containers": 0,
    "max_containers": 1,
    "scaledown_window": 5,
}


def _load_server_and_translate(model_key: str):
    import os
    import re
    import signal
    import subprocess
    import urllib.error
    import urllib.request

    spec = json.loads(Path("/opt/four_l40s_workers_q8_0_manifest.json").read_text())[
        "models"][model_key]
    file = Path("/weights") / spec["gguf_filename"]
    marker_file = Path("/weights") / (
        "hy_mt2_q8_0_verified.json"
        if model_key == "hy_mt2_30b" else "verified_gguf_q8_0.json"
    )
    if not file.is_file() or not marker_file.is_file():
        raise RuntimeError("No verified GGUF; CPU staging and SHA256 are required first")
    marker = json.loads(marker_file.read_text())
    if (marker.get("sha256_verified_locally") != spec["gguf_lfs_sha256"]
            or marker.get("repo_revision") != spec["gguf_revision"]
            or file.stat().st_size != spec["gguf_size_bytes"]):
        raise RuntimeError("Invalid GGUF marker, pinned revision or size")
    # The verified marker is written ONLY after independently hashing full file on CPU.
    import socket

    started_unix = time.time()
    started = time.monotonic()
    gpu_uuid = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=uuid", "--format=csv,noheader"],
        text=True, timeout=10,
    ).strip()
    if len(gpu_uuid.splitlines()) != 1:
        raise RuntimeError("Expected one GPU UUID")
    log_path = Path("/tmp/llama_four_model_smoke.log")
    log_file = log_path.open("w", encoding="utf-8")
    cmd = [
        BIN, "--model", str(file), "--host", "127.0.0.1", "--port", "8080",
        "--ctx-size", "4096", "--n-gpu-layers", "99", "--batch-size", "256",
        "--ubatch-size", "128", "--parallel", "1", "--threads", "4",
        "--no-webui", "--jinja",
    ]
    if model_key in ("index_35b", "gemma4_31b_it", "qwen35_35b"):
        cmd += ["--chat-template-kwargs", '{"enable_thinking":false}']
    proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT,
                            start_new_session=True)
    def query(endpoint, data=None, timeout=10):
        payload = json.dumps(data).encode() if data is not None else None
        request = urllib.request.Request(
            "http://127.0.0.1:8080" + endpoint, data=payload,
            headers={"Content-Type": "application/json"} if payload is not None else {},
            method="POST" if payload is not None else "GET",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)

    peak_mem = 0
    ready = None
    try:
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError("llama-server exited before model ready")
            try:
                gpu_mem = subprocess.check_output(
                    ["nvidia-smi", "--query-gpu=memory.used",
                     "--format=csv,noheader,nounits"], text=True, timeout=5).strip()
                peak_mem = max(peak_mem, int(gpu_mem.splitlines()[0]))
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
            try:
                if query("/health", timeout=3).get("status") == "ok":
                    ready = time.monotonic() - started
                    break
            except (OSError, ValueError, TimeoutError, urllib.error.URLError):
                pass
            time.sleep(2)
        if ready is None:
            raise TimeoutError("Model was not ready within 240 seconds")
        text = "The little fox crossed the bridge at sunrise."
        # Compatibility smoke, not the quality benchmark's frozen prompt.
        if model_key == "index_35b":
            instruction = (
                "Translate English to Vietnamese. Preserve original meaning. "
                "Only output the translation.\\n\\n"
                + text
            )
        else:
            instruction = (
                "Translate the following text into Vietnamese. "
                "Note that you should only output the translated result "
                "without any additional explanation:\\n\\n" + text
            )
        completion = query("/v1/chat/completions", {
            "model": spec["gguf_filename"],
            "messages": [{"role": "user", "content": instruction}],
            "max_tokens": 512 if model_key == "gemma4_31b_it" else 128,
            "temperature": 0 if model_key == "index_35b" else (
                1.0 if model_key == "gemma4_31b_it" else 0.7),
            "top_p": 1 if model_key == "index_35b" else (
                0.95 if model_key == "gemma4_31b_it" else 0.9),
            "top_k": 64 if model_key == "gemma4_31b_it" else 20,
            "seed": 42, "stream": False,
        }, timeout=120)
        result = completion["choices"][0]["message"]["content"]
        if not isinstance(result, str) or not result.strip():
            choice = completion["choices"][0]
            summary = {
                "finish_reason": choice.get("finish_reason"),
                "usage": completion.get("usage"),
                "message_keys": sorted(choice.get("message", {})),
                "content_type": type(result).__name__,
                "content_length": len(result) if isinstance(result, str) else None,
            }
            raise RuntimeError("No nonempty model text returned; " + json.dumps(summary))
        return {
            "status": "single_sentence_gpu_smoke_passed",
            "model_key": model_key,
            "gguf_sha256_verification_marker": marker["sha256_verified_locally"],
            "cuda_llama_revision": REVISION,
            "model_load_to_ready_seconds": round(ready, 3),
            "function_elapsed_seconds": round(time.monotonic() - started, 3),
            "start_unix_seconds": started_unix,
            "end_unix_seconds": time.time(),
            "gpu_uuid": gpu_uuid,
            "container_hostname": socket.gethostname(),
            "highest_sampled_vram_mib": peak_mem,
            "translation": result[:512],
            "usage": completion.get("usage"),
            "gpu_memory_peak_is_exact": False,
            "gpu_count": 1,
            "real_http_production_endpoint": False,
        }
    except Exception:
        log_file.flush()
        recent = log_path.read_text(encoding="utf-8", errors="replace")[-3500:]
        print("llama.cpp diagnostics (last 3.5KiB):",
              re.sub(r"(?i)(token|password|secret)=\\S+", r"\\1=[REDACTED]",
                     recent), flush=True)
        raise
    finally:
        try:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=12)
        except (OSError, subprocess.TimeoutExpired):
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
        log_file.close()


@app.function(name=MODAL_GPU_INFERENCE_FUNCTION_NAMES["hy_mt2_30b"],
              volumes={"/weights": volumes["hy_mt2_30b"]}, **GPU_ARGS)
def hy_mt2_gpu_smoke():
    return _load_server_and_translate("hy_mt2_30b")


@app.function(name=MODAL_GPU_INFERENCE_FUNCTION_NAMES["index_35b"],
              volumes={"/weights": volumes["index_35b"]}, **GPU_ARGS)
def index_gpu_smoke():
    return _load_server_and_translate("index_35b")


@app.function(name=MODAL_GPU_INFERENCE_FUNCTION_NAMES["gemma4_31b_it"],
              volumes={"/weights": volumes["gemma4_31b_it"]}, **GPU_ARGS)
def gemma4_gpu_smoke():
    return _load_server_and_translate("gemma4_31b_it")


@app.function(name=MODAL_GPU_INFERENCE_FUNCTION_NAMES["qwen35_35b"],
              volumes={"/weights": volumes["qwen35_35b"]}, **GPU_ARGS)
def qwen35_gpu_smoke():
    return _load_server_and_translate("qwen35_35b")


@app.local_entrypoint()
def main(model: str = "index_35b", smoke: bool = False, all_models: bool = False):
    if model not in MODEL_KEYS:
        raise ValueError("Unknown model")
    print("4 one-L40S workers registered; min_containers=0, max_containers=1")
    if not smoke and not all_models:
        print("CPU-only dry run. Pass --smoke for selected model or --all-models for all.")
        return
    lookup = {
        "hy_mt2_30b": hy_mt2_gpu_smoke,
        "index_35b": index_gpu_smoke,
        "gemma4_31b_it": gemma4_gpu_smoke,
        "qwen35_35b": qwen35_gpu_smoke,
    }
    t0 = time.monotonic()
    if all_models:
        calls = {key: function.spawn() for key, function in lookup.items()}
        responses = {}
        for key, call in calls.items():
            try:
                responses[key] = call.get(timeout=600)
            except Exception as exc:
                responses[key] = {
                    "status": "gpu_smoke_failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:500],
                }
    else:
        try:
            responses = {model: lookup[model].remote()}
        except Exception as exc:
            responses = {model: {
                "status": "gpu_smoke_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:500],
            }}
    all_ok = all(
        result.get("status") == "single_sentence_gpu_smoke_passed"
        for result in responses.values()
    )
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "one-sentence model/GGUF/CUDA compatibility only; no production deployment",
        "status": "all_selected_models_passed" if all_ok else "partial_or_failed",
        "selected_models": list(responses),
        "total_rpc_wall_seconds": round(time.monotonic() - t0, 3),
        "results": responses,
    }
    report_path = REPORT if all_models else REPORT.with_name(
        f"p4_{model}_l40s_worker_smoke_v1.json"
    )
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for key, value in responses.items():
        if value.get("status") != "single_sentence_gpu_smoke_passed":
            print(key, value["status"], value.get("error_type"),
                  value.get("error_message"))
            continue
        print(key, value["status"], "ready_s", value["model_load_to_ready_seconds"],
              "sampled_memory_mib", value["highest_sampled_vram_mib"],
              "translation", repr(value["translation"][:120]))
    print("Saved:", report_path)
    if not all_ok:
        raise RuntimeError("One or more model smokes failed; full report was preserved")
