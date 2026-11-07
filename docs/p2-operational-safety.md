# P2 operational safety: PostgreSQL limits, uncertainty, and explicit retries

This document applies to the **CPU-only mock** deployment. No model inference or GPU
is enabled. It does not certify the service for production.

## Behavior and limits

Every newly accepted translation or benchmark job uses atomic PostgreSQL counters
for the authenticated owner. Default limits:

| Counter | Default | Notes |
|---|---:|---|
| `TRANSLATION_MAX_JOBS_PER_MINUTE` | 10 | UTC fixed 60-second windows |
| `TRANSLATION_MAX_JOBS_PER_DAY` | 100 | UTC-day windows |
| `TRANSLATION_MAX_MODEL_RUNS_PER_DAY` | 200 | A four-model benchmark charges four runs |
| `TRANSLATION_MAX_ATTEMPTS_PER_MODEL` | 2 | Includes the initial attempt |

Values can be supplied to the gateway environment/Modal API Secret. They are not
USD estimates or a complete billable GPU budget. They limit jobs and model runs
but **not** provider compute charges, duration, or uncontrolled parallelism.

Rejected submissions return HTTP **429** and a `Retry-After` header. Idempotent
replays with the same key and payload do not consume quota, even under
concurrent requests at a fully exhausted quota boundary; changing the payload
under the same key returns **409**. Quota reservation and job creation share a
single database transaction. The owner is still the single configured API owner;
IP/client-specific rate limiting is not yet implemented.

## Fail-closed reconciliation

A claimed attempt stores `dispatch_claimed_at`; running attempts store
`started_at`. If an attempt is stuck, the operator tool marks:

- `dispatching` older than 300 seconds -> `dispatch_uncertain`;
- `running` older than 900 seconds -> `execution_uncertain`.

A timeout does **not** mean execution has stopped. Reconciliation never spawns
a worker, never retries, and never declares an unknown result definitively
failed. A late worker can still finish with its original claim token.

Load the local `.env` then run:

```bash
set -a; source .env; set +a
.venv/bin/python scripts/reconcile_stale_jobs.py
# Review the dry-run counts before any changes:
.venv/bin/python scripts/reconcile_stale_jobs.py --apply
```

For now reconciliation is **operator-invoked** rather than scheduled. This avoids
idle background costs on Modal. Do not blindly change uncertain runs into failed
jobs without separate external execution evidence.

## Explicit failed-run retry

`POST /v1/jobs/{job_id}/runs/{run_id}/retry` requires the existing Bearer token
and only accepts the *latest confirmed-failed* attempt, subject to daily model-run
quota and a two-attempt default limit. It returns HTTP 202 with the original
`job_id`. The response `GET /v1/jobs/{job_id}` includes all attempts, each
with `attempt_no`. The overall job status derives from the **latest attempt per
model**, preserving historical failures for audit.

Retry attempts are not allowed for running, completed, queued, dispatch-uncertain,
or execution-uncertain states. An ambiguous Modal spawn must first be investigated
through Modal logs/call metadata, not replayed automatically. PostgreSQL row
locking serializes concurrent retry requests on the same job.

Live verification on Modal CPU (2026-11-07): the protected retry endpoint
returned HTTP 202 for a confirmed failed run, HTTP 409 for a duplicate
attempt retry, and the job reached `completed` with both attempts retained.
The temporary test job was deleted; its usage counters were not reset.

## Data retention: explicit dry-run first

```bash
set -a; source .env; set +a
.venv/bin/python scripts/purge_retained_jobs.py --retention-days 90
# Only if appropriate under your data policy:
.venv/bin/python scripts/purge_retained_jobs.py --retention-days 90 --apply
```

Only *terminal* jobs with `finished_at` older than the configured threshold
are deleted, with dependent runs and results. Queued, running and uncertain
jobs are left untouched; quota counters remain for their UTC window.

No cron purge is installed. Plan backups, audit evidence, client-level
authorization, quota windows cleanup, migration rollback, security and
per-provider budget alerting before production.
