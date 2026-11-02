"""HTTP contract. Character limits refer to Unicode code points, not UTF-8 bytes."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .language import normalize_language_label, same_language
from .model_options import validate_model_configs
from .model_registry import MODEL_REGISTRY
from .text import validate_translation_text


class TranslationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preserve_formatting: bool = True


class TranslationContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_language: str
    target_language: str
    text: str = Field(min_length=1, max_length=1000)
    options: TranslationOptions = Field(default_factory=TranslationOptions)
    model_configs: dict[str, dict[str, object]] = Field(default_factory=dict, max_length=4)

    @field_validator("model_configs")
    @classmethod
    def validate_overrides(cls, value: dict[str, dict[str, object]]) -> dict:
        return validate_model_configs(value)

    @field_validator("text")
    @classmethod
    def validate_storage_text(cls, value: str) -> str:
        return validate_translation_text(value)

    @field_validator("source_language", "target_language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        return normalize_language_label(value)

    @model_validator(mode="after")
    def different_languages(self) -> "TranslationContent":
        if same_language(self.source_language, self.target_language):
            raise ValueError("source_language and target_language must differ")
        if not self.text.strip():
            raise ValueError("text must contain non-whitespace characters")
        return self


class SubmitTranslation(TranslationContent):
    model: str

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        if value not in MODEL_REGISTRY:
            raise ValueError(f"Unknown model. Choose one of {list(MODEL_REGISTRY)}")
        return value

    @model_validator(mode="after")
    def selected_config_only(self) -> "SubmitTranslation":
        validate_model_configs(self.model_configs, [self.model])
        return self


class SubmitBenchmark(TranslationContent):
    models: list[str] = Field(default_factory=lambda: list(MODEL_REGISTRY), min_length=1, max_length=4)

    @field_validator("models")
    @classmethod
    def validate_models(cls, models: list[str]) -> list[str]:
        if len(set(models)) != len(models):
            raise ValueError("models must not contain duplicates")
        if any(model not in MODEL_REGISTRY for model in models):
            raise ValueError(f"Unknown models. Choose from {list(MODEL_REGISTRY)}")
        return models

    @model_validator(mode="after")
    def selected_configs_only(self) -> "SubmitBenchmark":
        validate_model_configs(self.model_configs, self.models)
        return self


class JobSubmitted(BaseModel):
    job_id: UUID
    status: str
    kind: Literal["translation", "benchmark"]
    status_url: str


class RunView(BaseModel):
    run_id: UUID
    model: str
    attempt_no: int = 1
    status: str
    translation_text: str | None = None
    is_mock_result: bool = False
    error_code: str | None = None
    usage: dict[str, int] | None = None
    timings: dict[str, float] | None = None
    resources: dict[str, float] | None = None


class JobView(BaseModel):
    job_id: UUID
    kind: Literal["translation", "benchmark"]
    status: str
    source_language: str
    target_language: str
    runs: list[RunView]
