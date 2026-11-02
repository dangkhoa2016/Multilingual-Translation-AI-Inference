"""Explicit, non-generic Modal resource names.

Resources use the canonical project prefix. Short model suffixes keep
Volume names within Modal's 63-character limit.
Model weight Volumes are intentionally NOT created as a side effect of import/deploy.
"""

MODAL_APP_NAME = "multilingual-translation-ai-inference-api-and-model-workers"
MODAL_API_AUTH_SECRET_NAME = "multilingual-translation-ai-inference-api-authentication"
MODAL_POSTGRESQL_CONNECTION_SECRET_NAME = "multilingual-translation-ai-inference-postgresql-connection"
MODAL_HUGGINGFACE_DOWNLOAD_SECRET_NAME = "multilingual-translation-ai-inference-huggingface-download"

MODAL_CPU_GATEWAY_FUNCTION_NAME = "translation_inference_fastapi_cpu_gateway"
MODAL_CPU_MOCK_WORKER_FUNCTION_NAME = "translation_inference_cpu_mock_job_worker"

MODAL_GPU_WEIGHT_VOLUME_NAMES = {
    "hy_mt2_30b": "multilingual-translation-ai-inference-hy-mt2-q8-weights",
    "index_35b": "multilingual-translation-ai-inference-index-q8-weights",
    "gemma4_31b_it": "multilingual-translation-ai-inference-gemma4-q8-weights",
    "qwen35_35b": "multilingual-translation-ai-inference-qwen35-q8-weights",
}

MODAL_GPU_INFERENCE_FUNCTION_NAMES = {
    "hy_mt2_30b": "translation_inference_hy_mt2_30b_a3b_l40s_worker",
    "index_35b": "translation_inference_index_translate_35b_a3b_preview_l40s_worker",
    "gemma4_31b_it": "translation_inference_gemma_4_31b_it_l40s_worker",
    "qwen35_35b": "translation_inference_qwen_3_5_35b_a3b_l40s_worker",
}


# Real GPU Modal Cls names (distinct from ephemeral function-based smoke tools).
MODAL_GPU_INFERENCE_CLASS_NAMES = {
    "hy_mt2_30b": "HyMT2L40SWorker",
    "index_35b": "IndexTranslateL40SWorker",
    "gemma4_31b_it": "Gemma4L40SWorker",
    "qwen35_35b": "Qwen35L40SWorker",
}
