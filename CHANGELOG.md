# Changelog

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](CHANGELOG.vi.md)

## [1.0.0]

Initial source release of **Multilingual Translation AI Inference**.

### Added

- An authenticated FastAPI gateway for asynchronous single-model translation and comparison jobs across 1–4 selected models, with job-status and result retrieval.
- PostgreSQL persistence for jobs, per-model execution attempts, results, and schema migrations with Alembic.
- Four independently deployed NVIDIA L40S workers on Modal for Hy-MT2, Index-Translate, Gemma 4, and Qwen3.5, using separately staged, revision-pinned GGUF Q8_0 artifacts.
- An offline CPU mock demonstration, a bilingual Jupyter API-client notebook, model-integrity checks, and deployment/operations tooling.
- Optional CPU operations monitoring, callable manually or through an opt-in hourly schedule; automatic scheduling is disabled by default.
- Safe, opt-in initial provisioning of two Modal Secrets from one private `.env`, without overwriting existing Secrets; manual JSON setup remains supported.

### Security and reliability

- Bearer-token authentication for a **single-tenant** gateway; per-process request throttling and PostgreSQL-backed polling and admission limits.
- Input validation, bounded request sizes, sanitized error responses, and guarded handling of sensitive notebook output.
- Idempotent submissions and concurrency-safe admission, with explicit handling of uncertain execution to avoid blind retries and duplicate billable work.
- Bounded, optional inference telemetry that does not invalidate a successful translation when metrics are unavailable or malformed.

### Verification

- CPU-only regression and clean-install checks, including Python 3.12/3.13 Quick Start validation.
- Sanitized historical reports documenting authenticated API operations, PostgreSQL persistence, and runs across four distinct GPU workers. **CI does not rerun live GPU inference.**

### Release scope

- Source and deployment tooling are provided; **model weights and a hosted translation endpoint are not included**.
- GPU execution is billable. The recorded infrastructure tests do **not** establish translation quality, uptime, or current performance, and no independent BLEU, COMET, or human evaluation score is claimed.
- The gateway uses one shared Bearer credential rather than per-client API keys; globally distributed pre-authentication rate limiting is not part of this release.

For setup and API usage, see the [README](README.md). For release highlights, see [GitHub Release v1.0.0](https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference/releases/tag/v1.0.0).
