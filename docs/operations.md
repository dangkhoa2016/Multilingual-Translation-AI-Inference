# Operations — monitoring, cost and reconciliation

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](operations.vi.md)

The service intentionally separates **API admission policy**, **actual Modal
billing**, and **durable job recovery**. No application-level estimate is a
substitute for the billing provider's own spending controls.

## Monitoring

The shared Modal App includes a **CPU-only operations monitor**. Its
automatic schedule is **off by default**; enable hourly checks when deploying
with `TRANSLATION_OPERATIONS_MONITOR_SCHEDULE=hourly` (see
[deployment](deployment.md#deploy-the-app)). The monitor remains available
for manual runs when scheduling is off. Each invocation checks aggregate
PostgreSQL statuses, uncertain executions, stale dispatching/running work
and recent error codes; it never invokes or retries GPU workers.

**Alert delivery:** A healthy check writes a structured status to Modal Logs.
When an issue is detected, it writes an `alert` status and fails that CPU
function call. View the function's **Function Calls** and **Logs** in Modal;
this is **not** an email, webhook or automatically delivered notification.
Configure your own external notification integration if required. Alerts
do not automatically recover or retry jobs. Scheduled CPU invocations and
PostgreSQL queries may incur costs even without translation requests.

Operator CLI (read-only by default):

```bash
set -a; source .env; set +a
PYTHONPATH=src python scripts/operations/check_safeguards.py \
  --profile YOUR_MODAL_PROFILE

# Optional operator-chosen thresholds; exit code 2 signals warnings:
PYTHONPATH=src python scripts/operations/check_safeguards.py \
  --profile YOUR_MODAL_PROFILE \
  --alert-metered-usd 10 --alert-billed-usd 5
```

The example alert thresholds above are *illustrative only*, not configured
production spending limits.

Snapshots include `pending_jobs_count` and `pending_runs_by_model`, including
uncertain work across the database. `estimated_gpu_usd_reserved_today` covers
the **current UTC day** across configured owners; CLI billing covers the
**current month for the Modal workspace**. These scopes and periods differ;
subtracting the totals cannot establish an overrun or reconcile individual jobs.

## Unfinished workload limits

Defaults allow **20 unfinished jobs per owner** and **20 unfinished runs per
model**, counting `queued`, `dispatching`, `running`, `dispatch_uncertain`
and `execution_uncertain`. Model counts span owners; a multi-model job counts
once toward its owner's job limit. PostgreSQL locks stable owner/model keys
within admission transactions; configure identical limits across replicas.
These ceilings bound accepted work, not concurrent GPUs or queue latency.

Exhaustion returns HTTP 429 with `Retry-After: 30` and rolls back job/run
creation, quotas and estimated reservations. Idempotent replays of retained
jobs remain allowed. Confirmed-failure retries also obey capacity limits;
retrying one model consumes no additional job slot while another model in
the same job is active. Uncertain work retains capacity regardless of age.
Reconcile it before admitting more work; do not retry or change states merely
to bypass a ceiling. See [configuration](configuration.md).

## Estimated GPU admission reservations

When **both** settings are configured, the API reserves a fixed estimated
USD proxy for each accepted real GPU model-run:

```text
TRANSLATION_ESTIMATED_GPU_USD_PER_RUN
TRANSLATION_MAX_ESTIMATED_GPU_USD_PER_DAY
```

The admission transaction includes quotas and job creation. A four-model
API request reserves four units. When the estimated daily amount would
be exceeded, the API returns HTTP 429 and does not create a job.
Idempotent replays do not reserve twice, and explicitly retried
confirmed failures require another reservation.

**Important:** these counters do not measure actual GPU seconds, queue
time, CPU, memory, storage or provider adjustments. They are not a
hard currency limit. Set a **Modal Workspace Budget** separately, with
an amount selected by an authorized operator. The application-level
estimated budget is optional and must be explicitly configured.

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
PYTHONPATH=src python scripts/operations/check_safeguards.py --skip-billing

# Explicit state reconciliation: updates stale state; never re-runs a GPU:
PYTHONPATH=src python scripts/operations/check_safeguards.py \
  --skip-billing --apply-reconcile
```

A state transition is not proof the old GPU task was cancelled. For
retention cleanup, review the operator-only
[`purge_jobs.py`](../scripts/operations/purge_jobs.py) carefully.

### Job retention and idempotency lifetime

`purge_old_terminal_jobs()` is **operator-invoked only**, with a **90-day
default retention cutoff** and dry-run mode unless `apply=True` is
explicitly selected. Only sufficiently old, finished `completed`,
`failed` or `partial_failed` jobs are eligible; pending, running
and uncertain jobs are excluded. Age alone does **not** delete a job.

**Important:** the idempotency key and request hash are stored on the
job record, not in an independent permanent ledger. Purging the job
also deletes its duplicate-request identity. Repeating its key and payload
after purge can create a **new, potentially billable GPU job**.
The same-key replay guarantee holds only while the original job record
exists. Confirm retention with the operator before attempting old
replays. Never blindly resubmit uncertain work. Backups are a separate
operator responsibility.

## Operational references

- [Sanitized operations example](../reports/operations_safety_snapshot.json)
- [API integration summary](../reports/postgresql_gpu_jobs.json)
- [GPU worker summary](../reports/deployed_gpu_readiness.json)

## PostgreSQL backup and restore verification

**Database recovery is operator-managed, not automated by this repository.**
Configure provider-managed backups or point-in-time recovery, retention,
access controls and restoration testing with your PostgreSQL provider.
Save a **separate backup before migrations, provider changes or destructive
maintenance**. Translation inputs and outputs may be sensitive: backup
files must be encrypted/access-controlled, stored outside Git, and never
included in published `reports/`.

For an optional manual **logical backup**, use PostgreSQL client tools
compatible with the server version. Connect to the provider's **direct**
database endpoint using secure libpq environment variables and a private
`PGPASSFILE` (avoid passwords in shell history):

```bash
# Operator example only: configure PGHOST, PGPORT, PGUSER, PGDATABASE,
# PGSSLMODE and PGPASSFILE privately before running.
umask 077
mkdir -p "$HOME/translation-db-backups"
pg_dump --format=custom --no-owner \
  --file "$HOME/translation-db-backups/translation-backup.dump"
pg_restore --list "$HOME/translation-db-backups/translation-backup.dump" >/dev/null
```

To **test recovery**, create a *separate, empty, access-controlled*
PostgreSQL database, point your libpq connection variables at that
test database, then use `pg_restore --no-owner --dbname YOUR_EMPTY_TEST_DB
/path/to/translation-backup.dump`. Verify Alembic revision, job/run
record counts and application read paths without calling real GPUs.
**Never restore over the live database or run `--clean` against it.**
Provider snapshots and logical dumps have different recovery guarantees;
record the restore procedure and recovery objectives for your own
deployment.

See [security policy](../.github/SECURITY.md) and
[deployment](deployment.md).
