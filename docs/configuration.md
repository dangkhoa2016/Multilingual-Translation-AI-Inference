# Configuration and secrets

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](configuration.vi.md)

## Local development

Copy [`.env.example`](../.env.example) to `.env` and set your
own random local Bearer token. The local example uses SQLite and
`inline-mock`; this **does not perform real model inference**.
Never commit `.env`, actual database URLs or cloud credentials.

| Variable | Purpose |
|---|---|
| `TRANSLATION_INFERENCE_DATABASE_URL` | PostgreSQL/SQLite connection URL |
| `TRANSLATION_INFERENCE_MIGRATION_DATABASE_URL` | Direct PostgreSQL URL for Alembic migrations |
| `TRANSLATION_API_BEARER_TOKEN` | Client authentication secret |
| `TRANSLATION_DISPATCHER_MODE` | `record-only`, `inline-mock`, `modal-cpu-mock`, `modal-gpu` |
| `TRANSLATION_MAX_JOBS_PER_MINUTE` | Per-owner job creation limit |
| `TRANSLATION_MAX_JOBS_PER_DAY` | Per-owner daily job limit |
| `TRANSLATION_MAX_MODEL_RUNS_PER_DAY` | Daily model-run limit |
| `TRANSLATION_MAX_ATTEMPTS_PER_MODEL` | Maximum confirmed-failure attempts |
| `TRANSLATION_ESTIMATED_GPU_USD_PER_RUN` | Optional positive estimated reservation per model-run |
| `TRANSLATION_MAX_ESTIMATED_GPU_USD_PER_DAY` | Optional estimated daily admission ceiling |

Both estimated USD values must be configured together. The estimate
reserves a fixed number of micro-USD units in PostgreSQL for an accepted
run. **It is not a limit on the actual Modal invoice.** Do not assign
a budget amount without the operator's decision.

## Modal resources

The deployed application uses these descriptive names:

- App: `translation-ai-inference-api-and-model-workers`
- PostgreSQL Secret: `translation-ai-inference-postgresql-connection`
- API authentication Secret: `translation-ai-inference-api-authentication`

Each model has its own dedicated Modal Volume, locked in
[the model manifest](../models/four_l40s_workers_q8_0_manifest.json).
The GPU workers never download weights during a request.

The **deployed** API Secret controls real GPU mode. Editing a local
`.env` cannot change it. After updating a Secret, a Modal App rollover
may be necessary to replace containers that still hold an earlier
environment. Use [the deployment runbook](deployment.md) for controlled
activation and rollback.

## PostgreSQL safety

Prefer a pooled runtime URL when the provider supports serverless
connection pooling, but use a direct connection for schema migrations.
Provider-specific features, TLS requirements, backups and connection
limits must be checked separately. The project does not require Neon
specifically; any compatible PostgreSQL host may be used.

See [operations](operations.md) for read-only billing inspection and
explicitly controlled stale-job reconciliation.
