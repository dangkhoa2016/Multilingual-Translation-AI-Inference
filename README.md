# Multilingual Translation AI Inference

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](README.vi.md)

[![Python CI](https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference/actions/workflows/python-validation.yml/badge.svg?branch=main)](https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference/actions/workflows/python-validation.yml)
[![Repository Audit](https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference/actions/workflows/repository-audit.yml/badge.svg?branch=main)](https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference/actions/workflows/repository-audit.yml)
[![License: MIT](https://img.shields.io/badge/Source%20License-MIT-yellow.svg)](LICENSE)
[![Model License: Apache 2.0](https://img.shields.io/badge/Model%20License-Apache--2.0-blue.svg)](MODEL_LICENSE.md)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Modal](https://img.shields.io/badge/Modal-L40S%20%C3%97%204-76B900)](https://modal.com/)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Status](https://img.shields.io/badge/Status-Validated%20Preview-blue)](docs/roadmap.md)

**An authenticated, asynchronous multilingual translation API using four
independently scaling large-language models on NVIDIA L40S GPUs, with
PostgreSQL-backed jobs and reproducible GGUF model provenance.**

This project focuses on practical model-serving engineering: use one
consistent API to select a model or compare four models, keep the gateway
CPU-only, let each GPU scale to zero, and retain durable results when a
model fails or a request disconnects.

> **Verified preview, not a quality-certified translation product.**
> All four backends have produced real outputs through the deployed API,
> but accuracy across every language direction and production security
> requirements still need independent evaluation.

## What the project provides

- **Four model-specific NVIDIA L40S workers**, each with its own pinned
  GGUF artifact, persistent Modal Volume and model-specific decoding.
- **One FastAPI gateway** with Bearer authentication, input validation,
  idempotency keys, asynchronous submission and authenticated polling.
- **Durable PostgreSQL state** for jobs, attempts, results, request
  quotas and optional estimated USD admission reservations.
- **Controlled failure handling:** definite failures are isolated and
  ambiguous GPU executions are never retried automatically.
- **CPU-only hourly operations monitor** for stale/uncertain jobs,
  with read-only billing inspection through the Modal CLI.
- **Real GPU evidence, CPU-only automated tests and bilingual guides**
  to verify what the service actually does and does not prove.

## Supported model backends

| API model key | Upstream model | GPU | Quantization |
|---|---|---|---|
| `hy_mt2_30b` | Tencent Hy-MT2-30B-A3B | L40S 48 GB | GGUF Q8_0 |
| `index_35b` | IndexTeam Index-Translate-35B-A3B-preview | L40S 48 GB | GGUF Q8_0 |
| `gemma4_31b_it` | Google Gemma 4 31B IT | L40S 48 GB | GGUF Q8_0 |
| `qwen35_35b` | Qwen3.5-35B-A3B | L40S 48 GB | GGUF Q8_0 |

The API accepts `en` (English), `vi` (Vietnamese), `de` (German),
`ja` (Japanese) and `ko` (Korean), with different source and target
languages and up to **1,000 Unicode code points**. API support is not
a guarantee that every translation is semantically correct.

Model sources, revisions, weights, checksums and distribution licenses
are documented in the [model catalog](docs/models.md) and
[model license register](MODEL_LICENSE.md). No model weights are
committed to this Git repository.

## Validated results at a glance

| Verification | Observed result |
|---|---|
| Four real model loads | PASS on four distinct L40S GPUs |
| Model executions overlapping | PASS; four different GPU UUIDs |
| Authenticated single-model HTTP job | Completed with real, nonmock output |
| Four-model HTTP benchmark | 4/4 completed and persisted in PostgreSQL |
| Exact 1,000-character benchmark | 4/4 completed; 1,001 rejected with HTTP 422 |
| Two independent jobs sent to one model | Both completed without duplicate attempts |
| Immediate worker reuse | Same GPU UUID returned on consecutive readiness calls |
| Operational monitoring | Hourly CPU function, no GPU allocation or auto-retry |

These are bounded functional checks, **not performance SLAs or
translation-quality rankings**. Hy-MT2 diagnostics exposed terminology
and material-substitution errors that require further study.
See [benchmarking](docs/benchmarking.md) and [reliability](docs/reliability.md).

## Quick start — no GPU required

```bash
git clone https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference.git
cd Multilingual-Translation-AI-Inference

python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

cp .env.example .env
# Replace the sample Bearer token in .env with a local random secret.
python scripts/local_demo.py

python -m pytest -q
python -m ruff check .
python scripts/audit_public_repository.py
```

The local demo uses mock inference to exercise API and database behavior.
**It does not download or run the large GPU models.** Real deployments
require your own Modal and PostgreSQL configuration; see
[deployment instructions](docs/deployment.md).

## API example

Submit a real translation only after deploying the service and enabling
the `modal-gpu` dispatcher in your private Modal Secret:

```bash
export BASE_URL="https://YOUR_DEPLOYED_GATEWAY.modal.run"
# Load your private TRANSLATION_API_BEARER_TOKEN from a secure source.

curl -fsS -X POST "$BASE_URL/v1/jobs/translations" \
  -H "Authorization: Bearer $TRANSLATION_API_BEARER_TOKEN" \
  -H "Idempotency-Key: example-translation-001" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "hy_mt2_30b",
    "source_language": "en",
    "target_language": "vi",
    "text": "The little fox crossed the bridge at sunrise.",
    "options": {"preserve_formatting": true}
  }'
```

The API responds with HTTP 202, a `job_id`, and `status_url`. Poll
`GET /v1/jobs/{job_id}` with the same Bearer token. To compare models,
submit `POST /v1/jobs/benchmarks` with a `models` array instead of a
single `model` key. See the [developer/API guide](docs/development.md).

## Documentation

| Topic | English | Tiếng Việt |
|---|---|---|
| Architecture and design | [Architecture](docs/architecture.md) | [Kiến trúc](docs/architecture.vi.md) |
| Installation | [Deployment](docs/deployment.md) | [Triển khai](docs/deployment.vi.md) |
| Environment and secrets | [Configuration](docs/configuration.md) | [Cấu hình](docs/configuration.vi.md) |
| Model selection | [Models](docs/models.md) | [Model](docs/models.vi.md) |
| Translation evaluation | [Benchmarking](docs/benchmarking.md) | [Đánh giá](docs/benchmarking.vi.md) |
| Boundaries and concurrency | [Reliability](docs/reliability.md) | [Độ tin cậy](docs/reliability.vi.md) |
| Monitoring and budgets | [Operations](docs/operations.md) | [Vận hành](docs/operations.vi.md) |
| Local development | [Development](docs/development.md) | [Phát triển](docs/development.vi.md) |
| Design trade-offs | [Decisions](docs/design-decisions.md) | [Quyết định](docs/design-decisions.vi.md) |
| Remaining work | [Roadmap](docs/roadmap.md) | [Lộ trình](docs/roadmap.vi.md) |
| Model copyrights | [Model licenses](MODEL_LICENSE.md) | [Giấy phép model](MODEL_LICENSE.vi.md) |

Raw, immutable verification evidence is retained in [`reports/`](reports).
See [Contributing](.github/CONTRIBUTING.md), [Security](.github/SECURITY.md),
[Support](.github/SUPPORT.md) and [Changelog](CHANGELOG.md).

## Licensing and attribution

Original source code: **MIT © 2026 Đăng Khoa
<i.am@dangkhoa.dev>** — see [LICENSE](LICENSE).

The four pretrained models and their GGUF derivatives remain
**third-party Apache-2.0 licensed model artifacts** under their
respective upstream copyrights. MIT does **not** apply to those weights.
Review [MODEL_LICENSE.md](MODEL_LICENSE.md) and
[third-party notices](NOTICE.md) before redistribution or commercial use.

This is an independent community project, not an official Tencent,
IndexTeam, Google, Unsloth, Qwen or Modal product.
