#!/usr/bin/env bash
# Explicit manual provisioning of empty volumes; no weights download or GPU.
set -euo pipefail
if [[ "${CONFIRM_TRANSLATION_GPU_VOLUME_CREATION:-}" != "YES" ]]; then
  echo 'Volume creation requires CONFIRM_TRANSLATION_GPU_VOLUME_CREATION=YES' >&2
  exit 2
fi
: "${MODAL_PROFILE:?Set MODAL_PROFILE before creating model Volumes}"
: "${MODAL_ENVIRONMENT:?Set MODAL_ENVIRONMENT before creating model Volumes}"
modal volume create --profile "$MODAL_PROFILE" --env "$MODAL_ENVIRONMENT" multilingual-translation-ai-inference-hy-mt2-q8-weights
modal volume create --profile "$MODAL_PROFILE" --env "$MODAL_ENVIRONMENT" multilingual-translation-ai-inference-index-q8-weights
modal volume create --profile "$MODAL_PROFILE" --env "$MODAL_ENVIRONMENT" multilingual-translation-ai-inference-gemma4-q8-weights
modal volume create --profile "$MODAL_PROFILE" --env "$MODAL_ENVIRONMENT" multilingual-translation-ai-inference-qwen35-q8-weights
