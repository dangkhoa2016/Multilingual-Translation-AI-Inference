"""P1 model adapter contracts and candidate decoding policies.

These are declarations from model documentation, NOT verified llama.cpp settings.
The GPU engine and prompt/chats templates must be proven in P3/P4 before enabling.
"""
from dataclasses import dataclass
from typing import Protocol

from .model_registry import MODEL_REGISTRY


@dataclass(frozen=True)
class TranslationTask:
    source_language: str
    target_language: str
    text: str
    preserve_formatting: bool = True


@dataclass(frozen=True)
class CandidateDecoding:
    temperature: float
    top_p: float | None
    top_k: int | None
    enable_thinking: bool | None
    max_output_tokens: int = 2048


@dataclass(frozen=True)
class ModelPrompt:
    system: str
    user: str
    prompt_version: str
    decoding: CandidateDecoding


class ModelAdapter(Protocol):
    model_key: str

    def build_prompt(self, task: TranslationTask) -> ModelPrompt:
        ...


class CandidateTranslationAdapter:
    """Prompt formatting only. Not an inference implementation."""

    def __init__(self, model_key: str, decoding: CandidateDecoding):
        if model_key not in MODEL_REGISTRY:
            raise ValueError(f"Unknown model: {model_key}")
        self.model_key = model_key
        self.decoding = decoding

    def build_prompt(self, task: TranslationTask) -> ModelPrompt:
        if task.source_language == task.target_language:
            raise ValueError("Source and target languages must be different")
        fmt = "Preserve the original paragraph breaks and placeholders." if task.preserve_formatting else ""
        # This is a candidate plain-language prompt, not a raw chat template.
        # Engine-specific tokens must be applied by each model's verified runtime.
        return ModelPrompt(
            system="You are a professional translator. Return only the translated text. "
                   "Do not add commentary, explanations, or reasoning markers.",
            user=(f"Translate the text below from {task.source_language} to "
                  f"{task.target_language}. {fmt}\n"
                  f"<source_text>\n{task.text}\n</source_text>"),
            prompt_version="translation-candidate-v0.1-unverified",
            decoding=self.decoding,
        )


CANDIDATE_ADAPTERS: dict[str, CandidateTranslationAdapter] = {
    "hy_mt2_30b": CandidateTranslationAdapter(
        "hy_mt2_30b", CandidateDecoding(temperature=0.7, top_p=1.0,
                                          top_k=-1, enable_thinking=None)
    ),
    "index_35b": CandidateTranslationAdapter(
        "index_35b", CandidateDecoding(temperature=0.0, top_p=None,
                                       top_k=None, enable_thinking=False)
    ),
    "gemma4_31b_it": CandidateTranslationAdapter(
        "gemma4_31b_it", CandidateDecoding(temperature=1.0, top_p=0.95,
                                           top_k=64, enable_thinking=False)
    ),
    "qwen35_35b": CandidateTranslationAdapter(
        "qwen35_35b", CandidateDecoding(temperature=0.7, top_p=0.8,
                                        top_k=20, enable_thinking=False)
    ),
}
