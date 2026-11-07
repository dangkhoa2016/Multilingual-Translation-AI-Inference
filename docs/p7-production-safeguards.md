# P7 — Production safeguards: monitoring, estimated admission budget and reconciliation

Validation date: 2026-11-07

## What is operational now

The deployed `translation-ai-inference-api-and-model-workers` Modal App now has
**one CPU-only operations monitor scheduled hourly**. It reads PostgreSQL
state aggregates, emits structured logs and reports task failure on:
- any `dispatch_uncertain` or `execution_uncertain` run,
- stale `dispatching` or `running` work beyond configured age gates, or
- any error code observed in a job submitted over the past 24 hours.

The monitor never spawns a GPU, retries a request, purges a database row,
reconciles uncertain work or exposes the input/output translation text.
It uses a 0.125-CPU, 256-MiB, scale-to-zero CPU function with an **hourly**
`modal.Period(hours=1)` schedule. This CPU work is small but is **billable**
where not covered by workspace credits.

A live manual invocation of the *deployed* CPU function returned `healthy`,
zero alerts, zero GPU allocations and 36 completed model runs. Its
implementation is in `modal_app.py`, under
`translation_inference_cpu_operations_safety_monitor`.

**Alert delivery limitation:** the monitor writes to Modal Logs and shows
failed function executions; there is currently **no email/webhook/push**
notification integration. An operator must view the dashboard or connect
an external alerting solution. Do not claim a message will automatically
reach someone outside Modal.

## Live account and database snapshot

The read-only local operator CLI was used against the authenticated workspace
and existing PostgreSQL deployment; no new GPU task was requested:

| Metric | Observed |
|---|---:|
| Model runs completed in the PostgreSQL database | 36 |
| Uncertain job runs | 0 |
| Stale dispatching | 0 |
| Stale running | 0 |
| Error codes observed in last 24h | None |
| Workspace November 2026 metered cost, USD | 1.59568943 |
| Workspace November 2026 billed cost, USD after adjustments | 0 |

Source: [redacted aggregate report](../reports/p7_cpu_only_live_safeguards_snapshot_v1.json).

A separate, nonpersistent alert smoke supplied an illustrative
`--alert-metered-usd 1.00` threshold. Because workspace metered usage
exceeded the *test* threshold, the read-only CLI returned **exit status 2**
with `workspace_metered_usd_alert_threshold`, and performed no mutations.
This was **not** a change to the workspace's actual budget.

**These costs cover the entire Modal workspace**, including any previous
experiments, and are not a per-project GPU expense figure. Billed cost after
credits/free allowances is not equivalent to GPU metered cost. Billing
summaries can lag current activity; there is no claim of a zero-cost
future workload.

Current workspace CLI published resource rates for reference:

| Resource | USD/hour |
|---|---:|
| NVIDIA L40S GPU | 1.95000 |
| CPU, per requested core | 0.04730 |
| Memory, per GiB | 0.00800 |

GPU worker reservations: 1 L40S + 4 CPU cores + 8 GiB memory. These
rates are **point-in-time** and not a promise or an exact invoice;
startup, execution duration, other services and workspace adjustments
affect the eventual bill.

## Estimated USD admission safeguard (opt-in)

The authenticated API has new optional environment variables:

- `TRANSLATION_ESTIMATED_GPU_USD_PER_RUN`
- `TRANSLATION_MAX_ESTIMATED_GPU_USD_PER_DAY`

**Both must be set together** to valid, finite positive USD amounts.
The per-run estimate must be less than or equal to the chosen daily
estimated cap. Neither variable is set automatically; there is no
arbitrarily imposed default budget.

When `TRANSLATION_DISPATCHER_MODE=modal-gpu` and both are configured,
PostgreSQL atomically reserves a fixed **estimated USD proxy** for each
model run before the job is created. A four-model benchmark reserves
four units. Explicit retry of a confirmed failed attempt also reserves
one unit. Concurrent jobs share the same UTC-day counter.

When the estimated counter would exceed the daily limit, the API
returns **HTTP 429** and rolls back all quota changes in the rejected
transaction. A same-key idempotent replay does not reserve twice.
CPU mock dispatch is never charged against the estimated GPU counter.

The counter is stored in the existing `usage_windows` table, with
`scope=estimated-gpu-usd-per-day`; **no new migration is needed**.

### Critical limitation

This is a **fixed admission estimate, NOT an actual-dollar cap**:
the application cannot infer real billed GPU seconds per worker from
a job count. Model cold starts, queue times, 900s function timeout,
CPU/memory charges, storage and provider adjustments can all cause
real spend to diverge from the configured estimate.

An operator must separately set a **Modal Workspace Budget** in Modal's
Usage and Billing settings for provider-level spend protection, and
should review its semantics, thresholds and coverage. The workspace
budget was **not** created or changed by these scripts. Team/Enterprise
environment budgets may also be available, depending on plan.

The modal authentication Secret may include the two optional budget
variables. The `scripts/set_modal_dispatch_mode.py` helper carries
both values from the local environment when replacing the Secret.
**Never invoke Secret replacement without those environment values if
you expect the currently configured estimate to be preserved.**

The live API is **not currently enforcing the optional estimated-USD
cap**, because no operator-selected cap has been supplied.

## CPU-only operator scan and explicit reconciliation

```bash
# Load existing PostgreSQL URL from ignored .env, not source code:
set -a; source .env; set +a

# Read-only: no GPU, no DB mutation; current workspace usage:
PYTHONPATH=src python scripts/check_production_safeguards.py \
  --profile YOUR_MODAL_PROFILE

# Read-only with operator-chosen alerts; exit status 2 for threshold warnings:
PYTHONPATH=src python scripts/check_production_safeguards.py \
  --profile YOUR_MODAL_PROFILE \
  --alert-metered-usd 10 --alert-billed-usd 5

# Read-only database only, without any Modal CLI auth:
PYTHONPATH=src python scripts/check_production_safeguards.py --skip-billing

# Manual, explicit DB state reconciliation ONLY. This does NOT retry or
# requeue a job; stale runs are marked uncertain and may finish later.
PYTHONPATH=src python scripts/check_production_safeguards.py \
  --skip-billing --apply-reconcile
```

The values `10` and `5` above illustrate alert thresholds only;
they are **not a requested or configured monthly budget**.
Actual workspace usage thresholds are separate from the application's
estimated per-run daily admission limit.

A CLI alert is reported as a structured alert list and exit status 2.
This does not send email. Run from an authorized operator workstation
or an external scheduler with configured notifications if desired.

## Safety and test guarantees

Offline pytest coverage verifies:

- exact USD parsing with upward micro-USD rounding, rejecting NaN/Inf,
  invalid strings and unsupported integer overflow,
- paired configuration and no implicit operator budget amount,
- atomic budget reservation under concurrent submissions,
- a four-model job that exceeds the cap creates **zero jobs** and
  leaves **all** admission counters untouched,
- same-key idempotent replay does not reserve again,
- explicit failed-run retries consume a new reservation, but cannot
  retry when insufficient estimated budget remains,
- mock-only dispatch does not reserve real GPU estimates,
- read-only monitoring never alters job state or leaks source text,
- monthly billing CLI reports are workspace scoped and sanitized,
- uncertain/stale alert detection without any automatic retry,
- the existing 102 reliability, API and model compatibility tests.

The repository's live monitoring report contains only aggregate
counts, provider billing summary, warning codes and timestamps.
No bearer token, database URL, individual job identifier or user
translation output is committed.

## Not yet complete

- Workspace provider-level dollar budget must be configured by an
  authorized operator who chooses the amount and verifies enforcement.
- No external alert delivery channel is connected. Modal Logs alone
  are not reliable notifications to a person.
- Full resource-tagged actual per-project billing attribution remains
  out of scope; the current billing summary covers the entire workspace.
- Fault injection/cancellation in an isolated staging deployment and
  end-to-end disaster recovery remain outstanding.
- Long-duration load/soak testing and human-reviewed multilingual
  quality certification remain outstanding.

**Gate summary:** P7 DB monitoring, manual billing/alert checks and
opt-in estimated budget admission are implemented; hourly CPU
monitoring is deployed and live-smoke-tested. Provider dollar budget
and external notifications are *not* configured.
