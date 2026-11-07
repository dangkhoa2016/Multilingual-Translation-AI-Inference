#!/usr/bin/env bash
# EXPLICIT, MANUAL, P3-ONLY: creates four named Volumes (no weights download).
# Do not run during P1/P2. Must be executed by an authorized Modal account owner.
set -euo pipefail
if [[ "${CONFIRM_TRANSLATION_GPU_VOLUME_CREATION:-}" != "YES" ]]; then
  echo 'Volume creation disabled. Export CONFIRM_TRANSLATION_GPU_VOLUME_CREATION=YES only when starting P3.' >&2
  exit 2
fi
modal volume create translation-ai-inference-hy-mt2-30b-a3b-gguf-weights
modal volume create translation-ai-inference-index-35b-a3b-preview-gguf-weights
modal volume create translation-ai-inference-gemma-4-31b-it-gguf-weights
modal volume create translation-ai-inference-qwen-3-5-35b-a3b-gguf-weights
