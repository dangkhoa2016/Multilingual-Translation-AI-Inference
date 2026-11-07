# Community roadmap

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](roadmap.vi.md)

Multilingual Translation AI Inference is a translation service for practical
API use and self-hosted deployments. This roadmap focuses on operability,
reliability, security and integration—not model rankings or translation-quality
benchmarks. The ideas are open for community discussion, not committed features
or release dates.

## What is available in 1.0.0

- Bearer-authenticated FastAPI gateway and durable PostgreSQL job state.
- Asynchronous translation jobs, input validation and idempotency safeguards.
- Four independently managed NVIDIA L40S GGUF model workers.
- Local CPU demonstrations and regression tests, plus bilingual documentation.
- MIT-licensed source with separate attribution for upstream models.

## Suggested contribution priorities

1. **Reliable API operations:** improve clarity of job lifecycle and error
   handling, recovery of accepted requests, concurrency safeguards, and
   guidance for queue pressure and upstream failures. Keep idempotency
   guarantees intact and test failure cases without paid GPU calls.
2. **Security and fair use:** propose optional per-client credentials, scoped
   access, quotas and rate limiting with explicit trust boundaries. These are
   future extensions, not capabilities already shipped; add CPU-only tests
   and safe configuration examples before enabling them.
3. **Observability and integration:** add privacy-conscious operational metrics
   and structured diagnostics (without logging translation text or tokens),
   reusable client examples, and tests for asynchronous job polling.
   Examples should run with mock responses by default.

Discuss proposals via [GitHub Issues](https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference/issues)
before implementing significant changes.

## Possible extensions

- Client SDKs and examples for additional programming languages.
- Optional monitoring integrations, health diagnostics and alerting.
- Configurable request admission, per-client usage policies and bounded
  concurrent job handling.
- Deployment guides for additional supported environments and model backends,
  with documented resource requirements and licensing.

These ideas are not promises of production readiness or features supported in
the current release. See the [contribution guide](../.github/CONTRIBUTING.md).
