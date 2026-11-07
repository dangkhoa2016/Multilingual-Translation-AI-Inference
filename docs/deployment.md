# Deployment runbook — CPU mock only

This runbook is **NOT** a production or GPU deployment guide.
PostgreSQL migrations and local mock requests have been tested. Modal deployment and GPU inference have **not** been performed.

## 1. Provision a PostgreSQL development database

Choose a PostgreSQL provider (Neon is optional), match its region to Modal where
possible, enable TLS, and obtain TWO credential URLs if your provider supports pooling:

- `TRANSLATION_INFERENCE_MIGRATION_DATABASE_URL`: direct connection, migration CLI only.
- `TRANSLATION_INFERENCE_DATABASE_URL`: pooled connection, short CPU gateway/worker operations.

Both `postgresql://` (provider default) and `postgresql+psycopg://` are accepted; SQLAlchemy explicitly selects psycopg v3. Never publish usernames/passwords. Migrations run via `alembic -c db/alembic.ini upgrade head`.

Do not run migrations automatically in each Modal gateway container. Verify the intended Modal workspace before creating Secrets or deploying.

## 2. Create exact Modal Secrets (manual, account-scoped)

PostgreSQL provider migration: preserve the Secret name and `TRANSLATION_INFERENCE_DATABASE_URL`
key. Update its value to the new provider's connection string; apply schema migrations
to the target before switching. No API application rename or code changes are required
when SQL compatibility is maintained. Keep the migration URL out of the deployed gateway Secret.

Use the Modal dashboard UI or secret CLI. Provide the following ENV KEY NAMES,
not the example values:

- Secret `translation-ai-inference-postgresql-connection`:
  `TRANSLATION_INFERENCE_DATABASE_URL`
- Secret `translation-ai-inference-api-authentication`:
  `TRANSLATION_API_BEARER_TOKEN` and `TRANSLATION_DISPATCHER_MODE=modal-cpu-mock`

Generate a long random API token. Never paste live credentials into a commit or log.
Use a short-lived/pooled PostgreSQL URL for API workers when supported; use a direct
PostgreSQL URL for migrations. A provider without a pooler may use its direct URL
for both with conservative connection limits.

## 3. Install and deploy CPU-only app

```bash
pip install -e '.[dev]'
modal deploy modal_app.py
modal app list
modal function info translation-ai-inference-api-and-model-workers/translation_inference_fastapi_cpu_gateway
modal function info translation-ai-inference-api-and-model-workers/translation_inference_cpu_mock_job_worker
```

Both functions have `gpu=None`, min/buffer containers 0. The mock worker does not
translate text. Do not run `scripts/create_named_modal_volumes.sh` before P3.

## 4. Smoke

Call `/health`, `/v1/models` with Bearer, submit a translation job, poll status,
verify `is_mock_result=true` and mock disclaimer, verify duplicate Idempotency-Key
uses the same `job_id`, and verify `GET` does not start GPU work.

## 5. Rollback and incident notes

`modal app stop translation-ai-inference-api-and-model-workers` stops the deployed App,
but DOES NOT delete the PostgreSQL database or any Volume. No automatic data deletion
is provided. The v1 job dispatcher currently does not retry `dispatch_uncertain`;
manual investigation is required after a spawn/DB ambiguity. Avoid pushing live
traffic until P2 reconciliation and quota controls are tested.

Further details: [Modal scaling](https://modal.com/docs/guide/scale),
[Modal Function lookups](https://modal.com/docs/guide/trigger-deployed-functions),
[Neon pooling](https://neon.com/docs/connect/connection-pooling).
