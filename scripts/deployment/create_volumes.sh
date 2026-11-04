#!/usr/bin/env bash
# EXPLICIT, MANUAL: provisions four named model Volumes (no weights download).
# Run only with authorization; existing Volumes must not be recreated casually.
set -euo pipefail
if [[ "${CONFIRM_TRANSLATION_GPU_VOLUME_CREATION:-}" != "YES" ]]; then
  echo 'Volume creation disabled. Export CONFIRM_TRANSLATION_GPU_VOLUME_CREATION=YES only when provisioning model Volumes.' >&2
  exit 2
fi
modal volume create multilingual-translation-ai-inference-hy-mt2-q8-weights
modal volume create multilingual-translation-ai-inference-index-q8-weights
modal volume create multilingual-translation-ai-inference-gemma4-q8-weights
modal volume create multilingual-translation-ai-inference-qwen35-q8-weights
