#!/usr/bin/env bash
# Manual, CPU-only preflight for pinned Hy-MT2 llama.cpp source.
# Does NOT download GGUF weights or provision GPU/Modal resources.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LLAMA_REVISION="fd27b2034905f8dadd8bd6d2cc44595f4929d391"
HY_V3_SOURCE_SHA256="c173397670ff141b4a83424cf7d05f8b08f585b4a7a3fa3da36cc40f6b7a8814"
WORK_ROOT="${HY_MT2_PREFLIGHT_WORK_DIR:-/tmp/hy-mt2-p3-llama-build}"
BUILD_JOBS="${HY_MT2_BUILD_JOBS:-2}"

command -v curl >/dev/null || { echo 'curl required' >&2; exit 1; }
command -v cmake >/dev/null || {
  echo 'cmake required; install locally, e.g. python -m pip install cmake' >&2
  exit 1
}
mkdir -p "$WORK_ROOT"
cd "$WORK_ROOT"

if [[ ! -f "$WORK_ROOT/src/models/hy-v3.cpp" ]]; then
  curl --fail --location --retry 2 --max-time 120 --silent --show-error \
    "https://api.github.com/repos/ggml-org/llama.cpp/tarball/$LLAMA_REVISION" \
    -o "$WORK_ROOT/source.tar.gz"
  tar -xzf "$WORK_ROOT/source.tar.gz" --strip-components=1 -C "$WORK_ROOT"
fi
echo "$HY_V3_SOURCE_SHA256  $WORK_ROOT/src/models/hy-v3.cpp" | sha256sum --check

cmake -S "$WORK_ROOT" -B "$WORK_ROOT/build-cpu" \
  -DGGML_CUDA=OFF -DGGML_NATIVE=OFF \
  -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF \
  -DLLAMA_BUILD_SERVER=ON -DLLAMA_BUILD_UI=OFF -DLLAMA_USE_PREBUILT_UI=OFF \
  -DCMAKE_BUILD_TYPE=Release
cmake --build "$WORK_ROOT/build-cpu" --target llama-server -j "$BUILD_JOBS"
"$WORK_ROOT/build-cpu/bin/llama-server" --version

echo 'CPU binary build passed. This does NOT verify GGUF loading or CUDA.'
echo "Model pin manifest: $REPO_ROOT/models/hy_mt2_30b_q8_0.lock.json"
