# Multilingual Translation AI Inference

**Status: P1/P2 CPU mock is deployed; P3 has verified Hy-MT2 Q8_0 on one Modal L40S and completed a 16-case multilingual diagnostic. Semantic fidelity issues remain; no production GPU translation API is deployed.**

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

Only the Hy-MT2 model Volume has been created and populated. The other three Volume
names above are reserved, not provisioned. GPU Functions have proposed names in
`src/translation_ai_inference/resource_names.py` but are **not registered in the
production Modal App**.

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

## P2 operational safeguards

The development service has PostgreSQL-backed limits for submissions and model
runs, with same-key idempotent replays honored even at full quota, fail-closed stale-run reconciliation, explicit retry for confirmed failures,
and opt-in terminal-job retention. See
[`docs/p2-operational-safety.md`](docs/p2-operational-safety.md) for exact
behavior, settings and operator commands. A timeout never automatically
restarts a possibly active Modal execution. The protected failed-run retry
endpoint has been verified end to end on the deployed Modal CPU mock. This is not a dollar-denominated
GPU budget or a production security system.

## Current limitations

- No production GPU translation worker or endpoint; Hy-MT2 smoke and a 16-case quality diagnostic ran separately. Three other candidates remain unverified on GPU.
- PostgreSQL development migrations and Modal CPU `spawn()` have passed live smoke tests; this is not production-ready.
- No scheduled reconciliation or automatic purger; tools are intentionally operator-invoked.
- No multi-tenant/client-specific quotas, dollar-denominated provider budget guards or full security controls.
- `dispatch_uncertain` requires operator investigation; automatic retry is intentionally disabled to avoid duplicate billable work.
- The initial migration contains job/run/results tables; model registry, reviews and full provenance
  schema will be added during P2/P5.
- `Idempotency-Key` is scoped to a configured owner. Multi-tenant identity is not implemented.
- **Do not publish this mock API as a real translation service.**

See [`README.vi.md`](README.vi.md) for Vietnamese documentation.


## P3 — Hy-MT2 Q8_0 weight verification and L40S smoke

The official `tencent/Hy-MT2-30B-A3B-GGUF` Q8_0 candidate is pinned to
immutable Hugging Face revisions. The **entire 31,985,729,376-byte GGUF file**
was downloaded once into a dedicated Modal Volume and independently SHA256
verified against the pinned official hash. A short L40S hardware probe passed.
**Model loading and actual GPU translation are separate verification gates.**

- [P3 Hy-MT2 readiness and blockers](docs/p3-hy-mt2-readiness.md)
- [Pinned artifact manifest](models/hy_mt2_30b_q8_0.lock.json)
- Run `python scripts/verify_hy_mt2_p3.py --online --deep-header` (metadata only).
- Pinned llama.cpp CUDA build, full GGUF loading and real L40S EN→VI smoke **passed**.
- A controlled 16-case EN↔VI, DE↔VI, JA↔VI, KO↔VI diagnostic also completed.
  Source passages were 617–969 characters, and notable semantic substitutions
  require further review before any production inference is enabled.
- [L40S GPU smoke results](docs/p3-hy-mt2-l40s-smoke.md) and
  [machine-readable report](reports/p3_hy_mt2_l40s_smoke.json).

## P3 — Hy-MT2 multilingual quality diagnostic (2026-11-07)

A paid, one-shot NVIDIA L40S run completed **16/16 translation requests** across
EN↔VI, DE↔VI, JA↔VI and KO↔VI. Mean warm response latency was **0.653s** for
structured text and **3.127s** for narrative text; highest sampled VRAM was
**31,189 MiB**. The Modal RPC call took **52.271s**, including GPU startup.

**Important:** The diagnostic exposed semantic fidelity errors: the Vietnamese
expression for a *silver compass* was translated as *brass/copper* in all four
target languages. Automatic placeholder checks reported zero issues, but they
cannot establish semantic accuracy. This synthetic diagnostic has no qualified
human-reviewed references, so **Hy-MT2 is not approved for production inference**.

- [Diagnostic design, measured results, and limitations](docs/p3-hy-mt2-quality-diagnostic-review.md)
- [Complete inference outputs](reports/p3_hy_mt2_quality_diagnostic_v1.json)
- [Preliminary semantic review](reports/p3_hy_mt2_quality_review_v1.json)
- To validate the suite without GPU, run
  `modal run --profile YOUR_MODAL_PROFILE scripts/modal_hy_mt2_quality_benchmark.py`.
- The `--run` option **allocates a billable L40S**; it is never invoked by CI.
