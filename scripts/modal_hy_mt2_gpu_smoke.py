"""One-shot CUDA build and bounded Hy-MT2 Q8_0 translation smoke.

This is a temporary Modal App, NOT a deployed HTTP service. Uses one L40S
only when invoked with --smoke. No GPU allocation for default build-check.

Run:
  modal run --profile bsmith888 scripts/modal_hy_mt2_gpu_smoke.py
  modal run --profile bsmith888 scripts/modal_hy_mt2_gpu_smoke.py --smoke
"""
import json
import subprocess
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
LOCK_FILE = ROOT / "models/hy_mt2_30b_q8_0.lock.json"
VOLUME_NAME = "translation-ai-inference-hy-mt2-30b-a3b-gguf-weights"
REVISION = "fd27b2034905f8dadd8bd6d2cc44595f4929d391"
SOURCE_SHA256 = "c173397670ff141b4a83424cf7d05f8b08f585b4a7a3fa3da36cc40f6b7a8814"
BIN = "/opt/llama.cpp/build/bin/llama-server"
app = modal.App("translation-ai-inference-hy-mt2-p3-cuda-smoke")
volume = modal.Volume.from_name(VOLUME_NAME)

# Compiles CUDA 8.9 / L40S-compatible binary in the IMAGE BUILDER, not on a GPU.
# GPU is only allocated for the explicit --smoke call below.
image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.8.1-devel-ubuntu22.04", add_python="3.12"
    ).entrypoint([])
    .apt_install(
        "git", "cmake", "build-essential", "libcurl4-openssl-dev",
        "libssl-dev", "ca-certificates", "curl", "ninja-build",
    )
    .run_commands(
        "git clone --filter=blob:none https://github.com/ggml-org/llama.cpp.git /opt/llama.cpp"
        + f" && cd /opt/llama.cpp && git checkout --detach {REVISION}",
        f"echo '{SOURCE_SHA256}  /opt/llama.cpp/src/models/hy-v3.cpp' | sha256sum -c -",
        "cmake -S /opt/llama.cpp -B /opt/llama.cpp/build -G Ninja "
        "-DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=89 -DGGML_NATIVE=OFF "
        "-DLLAMA_BUILD_SERVER=ON -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_UI=OFF "
        "-DLLAMA_USE_PREBUILT_UI=OFF -DCMAKE_BUILD_TYPE=Release",
        # CUDA driver library is host-injected on the GPU runtime, absent at build time.
        # The upstream llama.cpp CUDA Dockerfile uses --allow-shlib-undefined.
        "cmake -S /opt/llama.cpp -B /opt/llama.cpp/build "
        "-DCMAKE_EXE_LINKER_FLAGS=-Wl,--allow-shlib-undefined "
        "&& cmake --build /opt/llama.cpp/build --target llama-server --parallel 2",
    )
    .add_local_file(LOCK_FILE, "/opt/hy_mt2_lock.json")
)


@app.function(
    image=image, cpu=1, memory=1024, timeout=90,
    min_containers=0, buffer_containers=0, max_containers=1,
)
def cuda_build_check() -> dict:
    """Structural verification on CPU; real NVIDIA driver is GPU-runtime-injected."""
    cuda = subprocess.run(["nvcc", "--version"], capture_output=True, text=True, timeout=25)
    binary = Path(BIN)
    cuda_library = list(Path("/opt/llama.cpp/build/bin").glob("libggml-cuda.so*"))
    if cuda.returncode != 0 or not binary.is_file() or not cuda_library:
        raise RuntimeError("CUDA toolkit, binary or linked backend missing")
    return {
        "llama_server_binary_exists": True,
        "llama_server_binary_size_bytes": binary.stat().st_size,
        "nvcc_version_last_line": cuda.stdout.strip().splitlines()[-1],
        "cuda_backend_compiled": True,
        "driver_library_runtime_verified": False,
        "note": "Binary execution requires host-injected libcuda.so.1 on L40S",
    }


@app.function(
    gpu="L40S",
    image=image,
    volumes={"/weights": volume},
    cpu=4,
    memory=8192,
    timeout=720,
    min_containers=0,
    buffer_containers=0,
    max_containers=1,
    scaledown_window=5,
)
def smoke_translation() -> dict:
    """Load a verified volume, invoke exactly one EN->VI translation, shut down."""
    import os
    import re
    import signal
    import time
    import urllib.error
    import urllib.request

    lock = json.loads(Path("/opt/hy_mt2_lock.json").read_text())
    gguf = lock["gguf"]
    path = Path("/weights") / gguf["file"]
    marker_path = Path("/weights/hy_mt2_q8_0_verified.json")
    if not path.is_file() or not marker_path.is_file():
        raise RuntimeError("Verified weights missing: do not run GPU smoke")
    marker = json.loads(marker_path.read_text())
    if (marker.get("sha256_verified_locally") != gguf["sha256_from_huggingface_metadata"]
            or marker.get("repo_revision") != gguf["revision"]
            or path.stat().st_size != gguf["size_bytes"]):
        raise RuntimeError("Verified volume hash/size/revision mismatch")
    version = subprocess.run([BIN, "--version"], capture_output=True, text=True, timeout=25)
    if version.returncode != 0:
        raise RuntimeError("CUDA llama-server binary failed on L40S: " + version.stderr[-600:])
    start = time.monotonic()
    print("CUDA llama-server version on GPU host:", (version.stdout or version.stderr).strip()[:200], flush=True)
    print("Full weights preverified, starting llama-server on one L40S", flush=True)

    def gpu_memory() -> int:
        q = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            text=True, timeout=10,
        ).strip()
        return int(q.splitlines()[0].strip())

    log_file = open("/tmp/hy_mt2_llama_server.log", "w", encoding="utf-8")
    cmd = [
        BIN, "--model", str(path),
        "--host", "127.0.0.1", "--port", "8080",
        "--ctx-size", "4096", "--n-gpu-layers", "99",
        "--batch-size", "256", "--ubatch-size", "128",
        "--parallel", "1", "--threads", "4",
        "--no-webui", "--jinja",
    ]
    process = subprocess.Popen(
        cmd, stdout=log_file, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    peak_mib = 0
    last_http_error = None

    def request_json(path_name: str, payload=None, timeout=8):
        uri = f"http://127.0.0.1:8080{path_name}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        request = urllib.request.Request(uri, data=data, headers=headers, method="POST" if data else "GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)

    try:
        ready_time = None
        load_deadline = time.monotonic() + 510
        while time.monotonic() < load_deadline:
            if process.poll() is not None:
                raise RuntimeError(f"llama-server exited during load: code {process.returncode}")
            peak_mib = max(peak_mib, gpu_memory())
            try:
                health = request_json("/health", timeout=3)
                if health.get("status") == "ok":
                    ready_time = time.monotonic()
                    break
            except (OSError, ValueError, TimeoutError, urllib.error.URLError) as e:
                last_http_error = type(e).__name__
            time.sleep(3)
        if ready_time is None:
            raise TimeoutError(f"llama-server not ready in 510 seconds ({last_http_error})")
        # Official Hy-MT2 prompt: no default system message; use full target name.
        messages = [
            {"role": "user", "content": (
                "Translate the following text into Vietnamese. "
                "Note that you should only output the translated result without "
                "any additional explanation:\n\n"
                "The little fox crossed the bridge at sunrise."
            )},
        ]
        result = request_json("/v1/chat/completions", {
            "model": gguf["file"],
            "messages": messages,
            "temperature": 0.7,
            "top_p": 1.0,
            "top_k": -1,
            "repeat_penalty": 1.0,
            "max_tokens": 128,
            "stream": False,
        }, timeout=120)
        peak_mib = max(peak_mib, gpu_memory())
        choices = result.get("choices", [])
        if not choices:
            raise RuntimeError("No chat completions returned")
        content = choices[0].get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Empty translation output")
        print("Translation smoke succeeded:", content[:250], flush=True)
        return {
            "status": "smoke_passed",
            "model_key": lock["model_key"],
            "translation_output": content[:600],
            "load_to_ready_seconds": round(ready_time - start, 3),
            "total_seconds": round(time.monotonic() - start, 3),
            "observed_gpu_used_mib": peak_mib,
            "usage": result.get("usage"),
            "gguf_sha256_verified_on_cpu": marker["sha256_verified_locally"],
            "exact_gpu_memory_peak_externally_instrumented": False,
        }
    except Exception:
        log_file.flush()
        recent = Path(log_file.name).read_text(encoding="utf-8", errors="replace")[-7000:]
        print("llama-server last logs:", re.sub(r"(?i)(token|password)=\S+", r"\1=[REDACTED]", recent), flush=True)
        raise
    finally:
        try:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
        log_file.close()


@app.local_entrypoint()
def main(smoke: bool = False) -> None:
    if smoke:
        print("STARTING one L40S smoke; model Volume must be fully verified", flush=True)
        from datetime import datetime, timezone

        result = smoke_translation.remote()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        report_path = ROOT / "reports" / "hy_mt2_gpu_smoke.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps({
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "model_lock": "models/hy_mt2_30b_q8_0.lock.json",
            "engine_revision": REVISION,
            "result": result,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Saved non-secret smoke report:", report_path)
    else:
        print("CUDA image build-check only: no GPU and no model files loaded")
        print(json.dumps(cuda_build_check.remote(), indent=2))
