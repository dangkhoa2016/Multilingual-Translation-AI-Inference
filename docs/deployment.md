# Deployment runbook — CPU mock only

This runbook is **NOT** a production or GPU deployment guide.
Development PostgreSQL migrations, Modal CPU deployment, and asynchronous CPU mock smoke tests have passed (2026-11-07). **GPU inference has not been deployed.**

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
.venv/bin/modal deploy --profile YOUR_MODAL_PROFILE modal_app.py
.venv/bin/modal app list --profile YOUR_MODAL_PROFILE
.venv/bin/modal function info --profile YOUR_MODAL_PROFILE translation-ai-inference-api-and-model-workers/translation_inference_fastapi_cpu_gateway
.venv/bin/modal function info --profile YOUR_MODAL_PROFILE translation-ai-inference-api-and-model-workers/translation_inference_cpu_mock_job_worker
```

Both functions have `gpu=None`, min/buffer containers 0. The mock worker does not
translate text. Do not run `scripts/create_named_modal_volumes.sh` before P3.

## 4. Smoke

Run the manual integration smoke test against the actual Modal web URL after loading
the local `.env` (the script reads only the bearer token from the environment):

```bash
set -a; source .env; set +a
.venv/bin/python scripts/smoke_modal_cpu.py \
  --base-url https://YOUR_DEPLOYED_ENDPOINT.modal.run
```

Checks: public `/health`, protected `/v1/models`, translation submission,
`spawn()`, PostgreSQL persistence, GET polling, idempotency and conflict detection,
plus a four-model CPU mock benchmark. Every result must declare
`is_mock_result=true` with the mock disclaimer. No real inference runs.
The public Modal URL uses application Bearer authentication for `/v1` endpoints;
the `/health` endpoint is intentionally public. Do not expose this test gateway
as a production translation service.

## 5. Operational safety (P2)

Apply revision `0002_p2_safety` to PostgreSQL before deploying this version:
`alembic -c db/alembic.ini upgrade head`.
The revision adds dispatch timestamps and the `usage_windows` quota table.

See [P2 operational safety](p2-operational-safety.md) for durable limits, explicit
failed-run retry, fail-closed reconciliation, and dry-run retention commands.
Reconciliation and retention are manual operator actions, not scheduled billable work.

## 6. Rollback and incident notes

`modal app stop translation-ai-inference-api-and-model-workers` stops the deployed App,
but DOES NOT delete the PostgreSQL database or any Volume. No automatic data deletion
is provided. The dispatcher never retries `dispatch_uncertain` or `execution_uncertain`;
manual investigation is required after a spawn/DB ambiguity. Avoid pushing live
traffic until P2 reconciliation and quota controls are tested.

Further details: [Modal scaling](https://modal.com/docs/guide/scale),
[Modal Function lookups](https://modal.com/docs/guide/trigger-deployed-functions),
[Neon pooling](https://neon.com/docs/connect/connection-pooling).
