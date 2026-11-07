# Multilingual Translation AI Inference

**Status: P1 API and P2 CPU-only mock deployment tested on Modal (2026-11-07). Actual GPU translation is NOT implemented or deployed.**

This repository starts the text-only, async-first translation service described in
[`docs/implementation-plan.vi.md`](docs/implementation-plan.vi.md). The target
architecture is one Modal App, a CPU FastAPI gateway, four independent L40S model
workers, and PostgreSQL as a durable job/result store (Neon is the initial hosting option). The CPU mock is an
integration-test tool; it does **not** translate.

## Resource names (no abbreviations)

| Modal resource | Exact name |
|---|---|
| App | `translation-ai-inference-api-and-model-workers` |
| CPU gateway | `translation_inference_fastapi_cpu_gateway` |
| CPU mock worker | `translation_inference_cpu_mock_job_worker` |
| API token Secret | `translation-ai-inference-api-authentication` |
| PostgreSQL connection Secret | `translation-ai-inference-postgresql-connection` |
| Hy-MT2 model Volume (P3) | `translation-ai-inference-hy-mt2-30b-a3b-gguf-weights` |
| Index-Translate model Volume (P3) | `translation-ai-inference-index-translate-35b-a3b-preview-gguf-weights` |
| Gemma 4 IT model Volume (P4) | `translation-ai-inference-gemma-4-31b-it-gguf-weights` |
| Qwen3.5 model Volume (P4) | `translation-ai-inference-qwen-3-5-35b-a3b-gguf-weights` |

The database provider is configurable via `TRANSLATION_INFERENCE_DATABASE_URL`; no provider name is
embedded in Modal resource names, environment variable names, or Python identifiers.

GPU Functions have explicit proposed names in `src/translation_ai_inference/resource_names.py`,
but they are **not registered yet**: mounting empty volumes and starting L40S would waste money.

## Run offline (SQLite; no Modal, hosted database, or GPU account needed)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e '.[dev]'
export TRANSLATION_INFERENCE_DATABASE_URL=sqlite+pysqlite:///./translation_inference_local.sqlite3
export TRANSLATION_API_BEARER_TOKEN=choose-a-long-local-secret
export TRANSLATION_DISPATCHER_MODE=inline-mock
alembic -c db/alembic.ini upgrade head
uvicorn translation_ai_inference.local:app --host 127.0.0.1 --port 8000
```

Use `http://127.0.0.1:8000/docs` for OpenAPI or:

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS -X POST http://127.0.0.1:8000/v1/jobs/translations \
  -H "Authorization: Bearer $TRANSLATION_API_BEARER_TOKEN" \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: demo-translation-001' \
  -d '{"model":"hy_mt2_30b","source_language":"en","target_language":"vi","text":"Hello, world!"}'
```

The response has `job_id` and `status_url`; `GET /v1/jobs/{id}` exposes results.
`inline-mock` returns an *explicitly marked mock*, not a translated sentence.
For an API-only test use `TRANSLATION_DISPATCHER_MODE=record-only` (status stays queued).
`modal-cpu-mock` uses Modal `spawn()` and requires a deployed Modal App.

## Run tests

```bash
python -m pytest -q
python scripts/local_demo.py
```

Unit tests and CI use only SQLite and CPU. They never require production secrets.
For Codespaces development with a local `.env`, explicitly load it before running
Alembic or Uvicorn (`set -a; source .env; set +a`). `.env` is Git-ignored.
Provider `postgresql://` URLs are converted to the psycopg v3 SQLAlchemy driver.

## Deploy the **CPU-only** Modal mock

See [`docs/deployment.md`](docs/deployment.md). Use a **direct PostgreSQL connection** for schema migrations and, where supported, a
pooled PostgreSQL connection for the deployed API/worker. The two Modal Secrets and
PostgreSQL schema must be configured before deployment. Run
`.venv/bin/modal deploy --profile YOUR_MODAL_PROFILE modal_app.py` from the
repository root. It registers ONLY the CPU gateway and CPU mock worker.
Development deployment and live Modal `spawn()` tests have passed. For reproducible
verification, load `.env` and run `scripts/smoke_modal_cpu.py --base-url YOUR_HTTPS_MODAL_URL`.
The script validates Bearer auth, idempotency, polling and four mock model runs.

## Current limitations

- No real GGUF runtime, L40S configuration, GPU function registration or model weights.
- PostgreSQL development migrations and Modal CPU `spawn()` have passed live smoke tests; this is not production-ready.
- No reconciliation/retry scheduler, TTL/privacy purger, client quotas or cost guards yet.
- `dispatch_uncertain` requires operator investigation; automatic retry is intentionally disabled to avoid duplicate billable work.
- The initial migration contains job/run/results tables; model registry, reviews and full provenance
  schema will be added during P2/P5.
- `Idempotency-Key` is scoped to a configured owner. Multi-tenant identity is not implemented.
- **Do not publish this mock API as a real translation service.**

See [`README.vi.md`](README.vi.md) for Vietnamese documentation.
