# Operations — monitoring, cost and reconciliation

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](operations.vi.md)

The service intentionally separates **API admission policy**, **actual Modal
billing**, and **durable job recovery**. No application-level estimate is a
substitute for the billing provider's own spending controls.

## Monitoring

The shared Modal App runs a scheduled **CPU-only operations monitor**
every hour. It checks aggregate PostgreSQL statuses, uncertain
executions, stale dispatching/running work and recent error codes.
It uses no GPU, does not retry, and writes redacted structured
events to Modal Logs. **No email/webhook notification has been wired.**

Operator CLI (read-only by default):

```bash
set -a; source .env; set +a
PYTHONPATH=src python scripts/check_production_safeguards.py \
  --profile YOUR_MODAL_PROFILE

# Optional operator-chosen thresholds; exit code 2 signals warnings:
PYTHONPATH=src python scripts/check_production_safeguards.py \
  --profile YOUR_MODAL_PROFILE \
  --alert-metered-usd 10 --alert-billed-usd 5
```

The example alert thresholds above are *illustrative only*, not configured
production spending limits.

## Estimated GPU admission reservations

When **both** settings are configured, the API reserves a fixed estimated
USD proxy for each accepted real GPU model-run:

```text
TRANSLATION_ESTIMATED_GPU_USD_PER_RUN
TRANSLATION_MAX_ESTIMATED_GPU_USD_PER_DAY
```

The admission transaction includes quotas and job creation. A four-model
benchmark reserves four units. When the estimated daily amount would
be exceeded, the API returns HTTP 429 and does not create a job.
Idempotent replays do not reserve twice, and explicitly retried
confirmed failures require another reservation.

**Important:** these counters do not measure actual GPU seconds, queue
time, CPU, memory, storage or provider adjustments. They are not a
hard currency limit. Set a **Modal Workspace Budget** separately, with
an amount selected by an authorized operator. No default USD cap has
been silently configured in the deployed API.

## Uncertain runs and recovery

The following statuses are deliberately different:
- `failed`: confirmed terminal failure, eligible for a bounded explicit retry.
- `dispatch_uncertain`: a Modal spawn acknowledgement may have been lost.
- `execution_uncertain`: the engine may have completed without the caller
  receiving confirmation.
- `completed`: durable output stored in PostgreSQL.

Never automatically resubmit uncertain runs. Inspect the log, the
claim token, the model and the job age before changing states.

```bash
# Read-only inspection without Modal CLI:
PYTHONPATH=src python scripts/check_production_safeguards.py --skip-billing

# Explicit state reconciliation: updates stale state; never re-runs a GPU:
PYTHONPATH=src python scripts/check_production_safeguards.py \
  --skip-billing --apply-reconcile
```

A state transition is not proof the old GPU task was cancelled. For
retention cleanup, review the operator-only
[`purge_retained_jobs.py`](../scripts/purge_retained_jobs.py) carefully.

## Evidence and remaining safeguards

- [Aggregate operational snapshot](../reports/operations_safety_snapshot.json)
- [Real PostgreSQL/GPU job integration](../reports/postgresql_gpu_jobs.json)
- [GPU worker readiness](../reports/deployed_gpu_readiness.json)

An end-to-end disaster recovery drill, external alert channel, per-project
provider billing attribution and staging fault-injection test remain open.
See [security policy](../.github/SECURITY.md).
