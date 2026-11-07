#!/usr/bin/env bash
# EXPLICIT, MANUAL: provisions four named model Volumes (no weights download).
# Run only with authorization; existing Volumes must not be recreated casually.
set -euo pipefail
if [[ "${CONFIRM_TRANSLATION_GPU_VOLUME_CREATION:-}" != "YES" ]]; then
  echo 'Volume creation disabled. Export CONFIRM_TRANSLATION_GPU_VOLUME_CREATION=YES only when provisioning model Volumes.' >&2
  exit 2
fi
modal volume create translation-ai-inference-hy-mt2-30b-a3b-gguf-weights
modal volume create translation-ai-inference-index-35b-a3b-preview-gguf-weights
modal volume create translation-ai-inference-gemma-4-31b-it-gguf-weights
modal volume create translation-ai-inference-qwen-3-5-35b-a3b-gguf-weights
