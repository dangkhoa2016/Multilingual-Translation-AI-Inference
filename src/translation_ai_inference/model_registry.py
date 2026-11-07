"""Model registry metadata is not a proof of GPU compatibility or accuracy."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelDefinition:
    key: str
    checkpoint: str
    gguf_repository: str
    quantization: str = "Q8_0"
    enabled: bool = False  # Real GPU inference is not enabled in P1/P2.
    runtime_verified: bool = False


MODEL_REGISTRY: dict[str, ModelDefinition] = {
    "hy_mt2_30b": ModelDefinition(
        "hy_mt2_30b", "tencent/Hy-MT2-30B-A3B", "tencent/Hy-MT2-30B-A3B-GGUF"
    ),
    "index_35b": ModelDefinition(
        "index_35b", "IndexTeam/Index-Translate-35B-A3B-preview",
        "IndexTeam/Index-Translate-35B-A3B-preview-GGUF",
    ),
    "gemma4_31b_it": ModelDefinition(
        "gemma4_31b_it", "google/gemma-4-31B-it", "unsloth/gemma-4-31B-it-GGUF"
    ),
    "qwen35_35b": ModelDefinition(
        "qwen35_35b", "Qwen/Qwen3.5-35B-A3B", "unsloth/Qwen3.5-35B-A3B-GGUF"
    ),
}

ALLOWED_LANGUAGES = frozenset({"en", "vi", "de", "ja", "ko"})
