# Configuration and secrets

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](configuration.vi.md)

## Local development

The [local demo](../scripts/examples/local_demo.py) is self-contained: it
creates temporary SQLite state and uses a demo-only token from the script.
**It does not read `.env` or perform real inference.** For migrations,
real API scripts or deployments, copy [`.env.example`](../.env.example)
to an untracked `.env` and configure your own credentials. Never commit
`.env`, actual database URLs or cloud credentials.

| Variable | Purpose |
|---|---|
| `TRANSLATION_INFERENCE_DATABASE_URL` | PostgreSQL/SQLite connection URL |
| `TRANSLATION_INFERENCE_MIGRATION_DATABASE_URL` | Direct PostgreSQL URL for Alembic migrations |
| `TRANSLATION_API_BEARER_TOKEN` | Client secret (16–4096 printable ASCII characters; no spaces/control characters; use a random value) |
| `TRANSLATION_AUTH_FAILURE_LIMIT` | Failed Bearer attempts before local lockout (default: `3`) |
| `TRANSLATION_AUTH_FAILURE_WINDOW_SECONDS` | Sliding failure window (default: `300`) |
| `TRANSLATION_AUTH_LOCKOUT_SECONDS` | Lockout duration (default: `900`) |
| `TRANSLATION_AUTH_MAX_TRACKED_CLIENTS` | In-memory peer-state bound per gateway process (default: `4096`) |
| `TRANSLATION_MAX_API_BODY_BYTES` | Maximum protected request body (default: `65536` bytes) |
| `TRANSLATION_MAX_REQUESTS_PER_MINUTE_PER_PEER` | Pre-auth request ceiling per peer/process (`120`) |
| `TRANSLATION_MAX_REQUESTS_PER_MINUTE_PER_PROCESS` | Pre-auth ceiling for the entire process (`600`) |
| `TRANSLATION_MAX_JOB_POLLS_PER_MINUTE` | PostgreSQL-shared job GET quota per owner (`120`) |
| `TRANSLATION_MAX_PENDING_JOBS_PER_OWNER` | Maximum unfinished jobs per owner (`20`) |
| `TRANSLATION_MAX_PENDING_RUNS_PER_MODEL` | Maximum unfinished runs per model across owners (`20`) |
| `TRANSLATION_AUDIT_LOG_ENABLED` | Optional access metadata; accepts `true`/`false` only (default `false`) |
| `TRANSLATION_DISPATCHER_MODE` | `record-only`, `inline-mock`, `modal-cpu-mock`, `modal-gpu` |
| `TRANSLATION_MAX_JOBS_PER_MINUTE` | Per-owner job creation limit |
| `TRANSLATION_MAX_JOBS_PER_DAY` | Per-owner daily job limit |
| `TRANSLATION_MAX_MODEL_RUNS_PER_DAY` | Daily model-run limit |
| `TRANSLATION_MAX_ATTEMPTS_PER_MODEL` | Maximum total attempts per model, **including the first run**; retry only after confirmed failure (e.g. 2 = 1 initial run + at most 1 retry) |
| `TRANSLATION_ESTIMATED_GPU_USD_PER_RUN` | Optional positive estimated reservation per model-run |
| `TRANSLATION_MAX_ESTIMATED_GPU_USD_PER_DAY` | Optional estimated daily admission ceiling |

Both estimated USD values must be configured together. The estimate
reserves a fixed number of micro-USD units in PostgreSQL for an accepted
run. **It is not a limit on the actual Modal invoice.** Do not assign
a budget amount without the operator's decision.

## Access scope and shared credentials

The default deployment is **single-tenant**, not multi-tenant. The API
uses one shared `TRANSLATION_API_BEARER_TOKEN` and a fixed request owner
(`single-tenant-api`). Every client presenting that token operates in
the **same ownership scope**:

- Per-owner job quotas and model-run admission limits are shared among all
  clients, rather than calculated separately for each end user.
- The idempotency namespace is scoped to that owner: the same
  `Idempotency-Key` with the same payload identifies the same logical job;
  reusing that key with a different payload causes HTTP 409.
- An authenticated client with a valid job UUID can read jobs belonging to
  the shared owner. A UUID is not an independent user authorization boundary.
  Jobs outside the configured owner remain out of scope.

Keep the Bearer token in server-side secrets, restrict access to trusted
clients and rotate compromised credentials. For independent users/tenants,
a separate design is required: authenticated tenant identities, stable
job-owner mapping, per-job authorization, tenant-scoped quotas and
idempotency, data isolation and a reviewed migration/security plan.
**Setting multiple client tokens alone does not enable multi-tenancy.**

## CPU gateway security

The gateway limits requests **before comparing tokens**: by default 120 per
peer/minute and 600 per process/minute. Three failures in five minutes trigger
429 responses for further failed attempts for 15 minutes; a valid token clears
the failure counter while remaining subject to the request ceiling. Bodies
default to 64 KiB; public Swagger/OpenAPI are disabled.
Pre-auth limits use each process's RAM. Job GET quotas and unfinished job/run
limits share PostgreSQL across replicas. Configure the same limits on every
replica. See [security](security.md) and [operations](operations.md) for window
semantics, uncertain states and optional access logging.

Request/poll limits accept integers from 1–1,000,000; unfinished job/run limits
accept 1–100,000. These bounds are validated at startup.

## Modal resources

The deployed application uses these descriptive names:

- App: `multilingual-translation-ai-inference-api-and-model-workers`
- PostgreSQL Secret: `multilingual-translation-ai-inference-postgresql-connection`
- API authentication Secret: `multilingual-translation-ai-inference-api-authentication`

Each model has its own dedicated Modal Volume, locked in
[the model manifest](../models/four_l40s_workers_q8_0_manifest.json).
The GPU workers never download weights during a request.

The **deployed** API Secret controls real GPU mode. Editing a local
`.env` cannot change it. After updating a Secret, a Modal App rollover
may be necessary to replace containers that still hold an earlier
environment. Use [the deployment runbook](deployment.md) for controlled
activation and rollback.

For a first installation, follow the [Secret creation walkthrough](deployment.md)
before provisioning any GPUs. When changing an already-deployed dispatcher,
use the documented `modal.Secret.update()` helper to modify only
`TRANSLATION_DISPATCHER_MODE` without replacing unrelated Secret variables.

## PostgreSQL safety

Prefer a pooled runtime URL when the provider supports serverless
connection pooling, but use a direct connection for schema migrations.
Provider-specific features, TLS requirements, backups and connection
limits must be checked separately. The project does not require Neon
specifically; any compatible PostgreSQL host may be used.

See [operations](operations.md) for billing inspection, PostgreSQL
backup/restore verification and controlled stale-job reconciliation.
