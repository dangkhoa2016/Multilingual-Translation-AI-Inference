"""Explicit, non-generic Modal resource names.

Do not shorten resource names; these identifiers are visible in the Modal console.
Model weight Volumes are intentionally NOT created as a side effect of import/deploy.
"""

MODAL_APP_NAME = "translation-ai-inference-api-and-model-workers"
MODAL_API_AUTH_SECRET_NAME = "translation-ai-inference-api-authentication"
MODAL_POSTGRESQL_CONNECTION_SECRET_NAME = "translation-ai-inference-postgresql-connection"

MODAL_CPU_GATEWAY_FUNCTION_NAME = "translation_inference_fastapi_cpu_gateway"
MODAL_CPU_MOCK_WORKER_FUNCTION_NAME = "translation_inference_cpu_mock_job_worker"

MODAL_GPU_WEIGHT_VOLUME_NAMES = {
    "hy_mt2_30b": "translation-ai-inference-hy-mt2-30b-a3b-gguf-weights",
    "index_35b": "translation-ai-inference-index-translate-35b-a3b-preview-gguf-weights",
    "gemma4_31b_it": "translation-ai-inference-gemma-4-31b-it-gguf-weights",
    "qwen35_35b": "translation-ai-inference-qwen-3-5-35b-a3b-gguf-weights",
}

MODAL_GPU_INFERENCE_FUNCTION_NAMES = {
    "hy_mt2_30b": "translation_inference_hy_mt2_30b_a3b_l40s_worker",
    "index_35b": "translation_inference_index_translate_35b_a3b_preview_l40s_worker",
    "gemma4_31b_it": "translation_inference_gemma_4_31b_it_l40s_worker",
    "qwen35_35b": "translation_inference_qwen_3_5_35b_a3b_l40s_worker",
}
