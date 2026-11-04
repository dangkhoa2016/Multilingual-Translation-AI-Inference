#!/usr/bin/env bash
# Manual, CPU-only preflight for pinned Hy-MT2 llama.cpp source.
# Does NOT download GGUF weights or provision GPU/Modal resources.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MANIFEST="$REPO_ROOT/models/four_l40s_workers_q8_0_manifest.json"
PYTHON_BIN="python3"
command -v "$PYTHON_BIN" >/dev/null || { echo 'python3 required' >&2; exit 1; }
LLAMA_REVISION="$("$PYTHON_BIN" -c 'import json,sys; print(json.load(open(sys.argv[1]))["llama_cpp_revision_hy_mt2_proven"])' "$MANIFEST")"
HY_V3_SOURCE_SHA256="$("$PYTHON_BIN" -c 'import json,sys; print(json.load(open(sys.argv[1]))["models"]["hy_mt2_30b"]["llama_cpp_architecture_source_sha256"])' "$MANIFEST")"
WORK_ROOT="${HY_MT2_PREFLIGHT_WORK_DIR:-/tmp/hy-mt2-llama-preflight-build}"
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
echo "Model manifest: $MANIFEST"
