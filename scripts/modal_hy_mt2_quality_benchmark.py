"""Opt-in, bounded one-L40S Hy-MT2 translation diagnostic (not production).

Default command performs local validation only, with no GPU:
    modal run --profile YOUR_MODAL_PROFILE scripts/modal_hy_mt2_quality_benchmark.py
GPU work is explicit:
    modal run --profile YOUR_MODAL_PROFILE scripts/modal_hy_mt2_quality_benchmark.py --run
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import modal

from scripts.hy_mt2_benchmark_common import DATASET, ROOT, assess_fidelity, load_suite, save_reports
from scripts.modal_hy_mt2_gpu_smoke import BIN, REVISION, volume
from scripts.modal_hy_mt2_gpu_smoke import image as smoke_image

LOCK = ROOT / "models/hy_mt2_30b_q8_0.lock.json"
APP_NAME = "translation-ai-inference-hy-mt2-quality-diagnostic"
app = modal.App(APP_NAME)
image = (smoke_image.add_local_file(DATASET, "/opt/hy_mt2_benchmark_cases.json")
         .add_local_python_source("scripts"))
LANGUAGES = {"en": "English", "vi": "Vietnamese", "de": "German",
             "ja": "Japanese", "ko": "Korean"}
MAX_GPU_SECONDS = 590
MAX_COMPLETION_TOKENS = 14000


@app.function(
    image=image, gpu="L40S", volumes={"/weights": volume},
    cpu=4, memory=8192, timeout=720, max_containers=1,
    min_containers=0, buffer_containers=0, scaledown_window=5,
)
def benchmark_gpu(max_cases: int) -> dict:
    import os
    import signal
    import subprocess
    import threading
    import urllib.error
    import urllib.request

    suite = json.loads(Path("/opt/hy_mt2_benchmark_cases.json").read_text(encoding="utf-8"))
    lock = json.loads(Path("/opt/hy_mt2_lock.json").read_text(encoding="utf-8"))
    gguf = lock["gguf"]
    marker = json.loads(Path("/weights/hy_mt2_q8_0_verified.json").read_text())
    model_path = Path("/weights") / gguf["file"]
    if (marker.get("sha256_verified_locally") != gguf["sha256_from_huggingface_metadata"]
            or marker.get("repo_revision") != gguf["revision"]
            or not model_path.is_file() or model_path.stat().st_size != gguf["size_bytes"]):
        raise RuntimeError("Weights marker, revision, size or local file invalid")
    if not 1 <= max_cases <= min(16, len(suite["cases"])):
        raise ValueError("Invalid max_cases")
    t0 = time.monotonic()
    stop_sampler = threading.Event()
    samples = {"max_mib": 0, "n": 0, "errors": 0}

    def sample_gpu():
        while not stop_sampler.wait(0.2):
            try:
                value = subprocess.check_output(
                    ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                    text=True, timeout=4,
                ).strip()
                samples["max_mib"] = max(samples["max_mib"], int(value.splitlines()[0]))
                samples["n"] += 1
            except (OSError, ValueError, subprocess.SubprocessError):
                samples["errors"] += 1

    sampler = threading.Thread(target=sample_gpu, daemon=True)
    sampler.start()
    logfile = open("/tmp/hy_mt2_benchmark_server.log", "w", encoding="utf-8")
    process = subprocess.Popen(
        [
            BIN, "--model", str(model_path), "--host", "127.0.0.1", "--port", "8080",
            "--ctx-size", "4096", "--n-gpu-layers", "99",
            "--batch-size", "256", "--ubatch-size", "128", "--parallel", "1",
            "--threads", "4", "--no-webui", "--jinja",
        ],
        stdout=logfile, stderr=subprocess.STDOUT, start_new_session=True,
    )

    def request(path, body=None, timeout=5):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            "http://127.0.0.1:8080" + path, data=data,
            headers={"Content-Type": "application/json"} if body is not None else {},
            method="POST" if data is not None else "GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)

    entries = []
    ready_seconds = None
    output_token_sum = 0
    stop_reason = None
    try:
        while time.monotonic() - t0 < 160:
            if process.poll() is not None:
                raise RuntimeError("llama-server exited before health readiness")
            try:
                if request("/health", timeout=2).get("status") == "ok":
                    ready_seconds = round(time.monotonic() - t0, 3)
                    break
            except (OSError, ValueError, TimeoutError, urllib.error.URLError):
                pass
            time.sleep(1)
        if ready_seconds is None:
            raise TimeoutError("Model did not become ready within 160s")
        for case in suite["cases"][:max_cases]:
            elapsed = time.monotonic() - t0
            if elapsed + 115 > MAX_GPU_SECONDS:
                stop_reason = "gpu_time_budget"
                break
            remaining = MAX_COMPLETION_TOKENS - output_token_sum
            if remaining < 256:
                stop_reason = "output_token_budget"
                break
            source = case["source_text"]
            prompt = (
                "Translate the following text into "
                + LANGUAGES[case["target_language"]]
                + ". Note that you should only output the translated result "
                + "without any additional explanation:\n\n"
                + source
            )
            max_tokens = min(1100 if case["category"] == "narrative_long" else 300, remaining)
            row = {
                "id": case["id"],
                "pair": case["source_language"] + "->" + case["target_language"],
                "category": case["category"],
                "source_text": source,
                "input_characters": len(source),
                "max_tokens": max_tokens,
            }
            t_request = time.monotonic()
            try:
                answer = request("/v1/chat/completions", {
                    "model": gguf["file"],
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7, "top_p": 1.0, "top_k": -1,
                    "repeat_penalty": 1.0, "seed": 42,
                    "max_tokens": max_tokens, "stream": False,
                }, timeout=110)
                latency = time.monotonic() - t_request
                choice = answer["choices"][0]
                content = choice["message"]["content"]
                if not isinstance(content, str):
                    raise ValueError("No string output from model")
                usage = answer.get("usage", {})
                completion = int(usage.get("completion_tokens", 0))
                output_token_sum += completion
                finish_reason = choice.get("finish_reason")
                row.update({
                    "output": content,
                    "output_characters": len(content),
                    "elapsed_seconds": round(latency, 3),
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": completion,
                    "tokens_per_second": round(completion / latency, 3) if latency else None,
                    "finish_reason": finish_reason,
                    "warnings": assess_fidelity(case, content, finish_reason),
                    "error": None,
                })
            except Exception as e:
                row.update({
                    "output": "", "output_characters": 0,
                    "elapsed_seconds": round(time.monotonic() - t_request, 3),
                    "warnings": ["request_failed"], "error": type(e).__name__,
                })
                if process.poll() is not None:
                    stop_reason = "server_exited"
            entries.append(row)
            print("Case", row["id"], "seconds", row["elapsed_seconds"],
                  "warnings", len(row["warnings"]), "error", row["error"], flush=True)
            if stop_reason:
                break
        return {
            "status": "completed" if len(entries) == max_cases else "partial",
            "model_key": lock["model_key"], "engine_revision": REVISION,
            "weight_sha256": marker["sha256_verified_locally"],
            "cases": entries, "requested_cases": max_cases,
            "model_load_seconds": ready_seconds,
            "total_gpu_function_seconds": round(time.monotonic() - t0, 3),
            "max_sampled_gpu_mib": samples["max_mib"],
            "gpu_memory_sample_count": samples["n"],
            "gpu_memory_sample_errors": samples["errors"],
            "gpu_peak_is_exact": False,
            "generated_tokens_total": output_token_sum,
            "stop_reason": stop_reason,
            "sampling": {"temperature": 0.7, "top_p": 1.0, "top_k": -1,
                         "repeat_penalty": 1.0, "seed": 42},
            "runtime_limits": {"gpu_seconds": MAX_GPU_SECONDS,
                               "completion_tokens": MAX_COMPLETION_TOKENS,
                               "max_concurrent_gpu_containers": 1},
        }
    finally:
        stop_sampler.set()
        sampler.join(timeout=3)
        try:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=12)
        except (OSError, subprocess.TimeoutExpired):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
        logfile.close()


@app.local_entrypoint()
def main(run: bool = False, max_cases: int = 16):
    suite, checksum = load_suite()
    if not 1 <= max_cases <= len(suite["cases"]):
        raise ValueError("max_cases must be in the range [1, 16]")
    print("Suite validated:", len(suite["cases"]), "cases, sha256", checksum)
    print("Selected:", max_cases, "cases; maximum one L40S, 720s function timeout")
    if not run:
        print("CPU-only validation completed; no GPU requested. Add --run to benchmark.")
        return
    before = time.monotonic()
    result = benchmark_gpu.remote(max_cases)
    wall = round(time.monotonic() - before, 3)
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": str(DATASET.relative_to(ROOT)), "dataset_sha256": checksum,
        "dataset_kind": suite["kind"],
        "model_lock": str(LOCK.relative_to(ROOT)),
        "modal_rpc_wall_seconds": wall,
        "run": result,
        "quality_claim": "unscored: no professional reference translations or human evaluation",
    }
    path = ROOT / "reports/hy_mt2_quality_diagnostic.json"
    files = save_reports(report, path)
    print("Saved reports:", *[str(f) for f in files], sep="\n")
    print(json.dumps({
        "status": result["status"], "completed": len(result["cases"]),
        "seconds": result["total_gpu_function_seconds"],
        "peak_sampled_mib": result["max_sampled_gpu_mib"],
        "modal_rpc_wall_seconds": wall,
        "stop_reason": result["stop_reason"],
    }, ensure_ascii=False))
