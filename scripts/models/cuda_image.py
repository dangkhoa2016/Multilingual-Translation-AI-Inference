"""Shared CUDA image for the four GGUF model smoke workers.

All model backends use the pinned llama.cpp revision and Hy-V3 loader hash
specified by the common model manifest. Image creation does not allocate GPU.
"""
import json
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_FILE = ROOT / "models/four_l40s_workers_q8_0_manifest.json"
MANIFEST = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
HY_SPEC = MANIFEST["models"]["hy_mt2_30b"]
REVISION = MANIFEST["llama_cpp_revision_hy_mt2_proven"]
SOURCE_SHA256 = HY_SPEC["llama_cpp_architecture_source_sha256"]
BIN = "/opt/llama.cpp/build/bin/llama-server"

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
    .add_local_file(MANIFEST_FILE, "/opt/four_l40s_workers_q8_0_manifest.json")
)

