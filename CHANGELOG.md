# Changelog

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](CHANGELOG.vi.md)

This changelog tracks externally meaningful capabilities, not internal
development stages or temporary workspace experiments.

## Unreleased — public preview

### Added
- One authenticated asynchronous FastAPI service backed by PostgreSQL.
- Four isolated NVIDIA L40S GGUF inference workers with scale-to-zero.
- Model provenance, pinned revisions, SHA256 checks and nonmock test evidence.
- Idempotent job admission, explicit retry for confirmed failures,
  quotas and uncertain-state recovery.
- Read-only billing inspection, optional estimated GPU admission budgets
  and a CPU-only hourly safety monitor.
- English and Vietnamese documentation, model license register,
  MIT source license and GitHub contribution/security policies.

### Verified
- Four independently active GPUs; real translations persisted through the API.
- A 1,000 Unicode-codepoint input boundary and two same-model
  submissions with durable output.
- CPU-only regression suite and reproducible local validation tools.

### Not claimed
- No guaranteed translation-quality score, continuous service SLA,
  provider-level spending limit or security certification.

See [roadmap](docs/roadmap.md), [benchmarking](docs/benchmarking.md)
and [operations](docs/operations.md). A stable release is intentionally
not announced until the remaining qualification work is complete.
