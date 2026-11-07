"""HTTP contract. Character limits refer to Unicode code points, not UTF-8 bytes."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .model_registry import ALLOWED_LANGUAGES, MODEL_REGISTRY


class TranslationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preserve_formatting: bool = True


class TranslationContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_language: str
    target_language: str
    text: str = Field(min_length=1, max_length=1000)
    options: TranslationOptions = Field(default_factory=TranslationOptions)

    @field_validator("source_language", "target_language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        if value not in ALLOWED_LANGUAGES:
            raise ValueError(f"Language must be one of {sorted(ALLOWED_LANGUAGES)}")
        return value

    @model_validator(mode="after")
    def different_languages(self) -> "TranslationContent":
        if self.source_language == self.target_language:
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


class JobView(BaseModel):
    job_id: UUID
    kind: Literal["translation", "benchmark"]
    status: str
    source_language: str
    target_language: str
    runs: list[RunView]
