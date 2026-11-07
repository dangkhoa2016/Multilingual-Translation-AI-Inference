# Deployment runbook — CPU gateway and four independent L40S workers

**Status (2026-11-07):** One Modal App contains an authenticated FastAPI CPU
gateway, a retained CPU mock worker, and four real model-specific NVIDIA L40S
classes. The currently deployed API Secret selects `modal-gpu`. All four
GGUF Q8_0 models passed individual and concurrent CUDA inference smokes,
and all four completed a real benchmark sent through the deployed API.

This is **operational GPU inference**, not certification of translation
accuracy, security, high concurrency or a dollar-denominated spending limit.
See [real GPU operations and evidence](real-gpu-deployment.md).

## 1. PostgreSQL

Configure a PostgreSQL provider with TLS, ideally region-adjacent to Modal.
Neon is optional, not embedded in service identifiers. Two credentials are
recommended when a provider offers pooled connections:

- `TRANSLATION_INFERENCE_MIGRATION_DATABASE_URL`: direct, migration CLI only.
- `TRANSLATION_INFERENCE_DATABASE_URL`: pooled, short API/worker transactions.

SQLAlchemy uses psycopg v3 for either `postgresql://` or
`postgresql+psycopg://`. Apply database schema migrations **outside** the
Modal gateway:

```bash
set -a; source .env; set +a
alembic -c db/alembic.ini upgrade head
```

The `0002_p2_safety` revision includes durable dispatch timestamps and
usage-window quotas. Do not run migrations at GPU cold start.

## 2. Modal Secrets and four preverified Volumes

The authenticated Modal workspace must have both named Secrets:

| Secret | Required keys |
|---|---|
| `translation-ai-inference-postgresql-connection` | `TRANSLATION_INFERENCE_DATABASE_URL` |
| `translation-ai-inference-api-authentication` | `TRANSLATION_API_BEARER_TOKEN`, `TRANSLATION_DISPATCHER_MODE` |

Modes: `modal-gpu` means **real, billable GPU translation**; `modal-cpu-mock`
means explicit mock results; `inline-mock` and `record-only` are intended
for local development. Never print or commit actual Secret values.

All four GGUF Q8_0 files must already be independently full-SHA256-verified
inside these separate Modal Volumes:

- `translation-ai-inference-hy-mt2-30b-a3b-gguf-weights`
- `translation-ai-inference-index-35b-a3b-preview-gguf-weights`
- `translation-ai-inference-gemma-4-31b-it-gguf-weights`
- `translation-ai-inference-qwen-3-5-35b-a3b-gguf-weights`

The verification markers are required at GPU startup. No GPU worker
downloads its weights. See the [four-model manifest](../models/four_l40s_workers_q8_0_manifest.json).

## 3. Deploy one Modal App, not four separately managed Apps

```bash
pip install -e '.[dev]'
modal deploy --profile YOUR_MODAL_PROFILE modal_app.py
modal app list --profile YOUR_MODAL_PROFILE
modal function info --profile YOUR_MODAL_PROFILE \
  translation-ai-inference-api-and-model-workers/translation_inference_fastapi_cpu_gateway
```

This deploys the CPU gateway, the CPU mock worker and **four GPU classes**:
`HyMT2L40SWorker`, `IndexTranslateL40SWorker`,
`Gemma4L40SWorker`, and `Qwen35L40SWorker`.

Each GPU class uses one L40S 48 GB and a model-specific Volume with
`min_containers=0`, `buffer_containers=0`, `max_containers=1`.
Four independent workloads can allocate four GPUs concurrently; idle GPUs
are not kept awake by GET polling.

Deployed classes have no public GPU HTTP URL. All external requests flow
through the authenticated CPU gateway.

## 4. Verify mode, authentication and real results

The public `GET /health` endpoint is intentionally unauthenticated. It
reports `inference_enabled=true` and `phase=gpu` only when the current
gateway process is configured for real inference.

All `/v1` routes require `Authorization: Bearer <TOKEN>`.
When the gateway is in real mode, submit one translation first and then
a bounded four-model benchmark:

```bash
set -a; source .env; set +a
export TRANSLATION_GATEWAY_BASE_URL="https://YOUR_DEPLOYED_MODAL_GATEWAY.modal.run"
PYTHONPATH=src python scripts/smoke_modal_gpu_api.py
PYTHONPATH=src python scripts/smoke_modal_gpu_api.py --run
PYTHONPATH=src python scripts/smoke_modal_gpu_api.py --run --all-models
```

The script uses the deployed API, checks bearer protection and same-key
idempotency, polls each run, and requires completed nonmock results.
It does not log bearer tokens or translated text. The two `--run` commands
allocate billable GPUs.

For a separate database/worker integration proof without modifying the
gateway dispatcher:

```bash
PYTHONPATH=src python scripts/smoke_real_gpu_job_dispatch.py --run
```

For a direct authenticated workspace check of all four **deployed** GPU
classes, without an API job:

```bash
PYTHONPATH=src python scripts/verify_deployed_four_gpu_classes.py --run
```

All three workflows were run successfully on 2026-11-07. See the
[full result table and raw reports](real-gpu-deployment.md).

## 5. Switching back to safe CPU mock mode

Keep the Secret name and existing bearer token. The opt-in switcher
uses an owner-private temporary JSON file, never puts token values in
shell arguments, and forces new Modal containers to load updated Secrets.

```bash
set -a; source .env; set +a
export TRANSLATION_GATEWAY_BASE_URL="https://YOUR_DEPLOYED_MODAL_GATEWAY.modal.run"
python scripts/set_modal_dispatch_mode.py --to-mock
python scripts/set_modal_dispatch_mode.py --to-mock --apply
# Explicitly restore real inference when appropriate:
python scripts/set_modal_dispatch_mode.py --to-gpu --apply
```

When code is unchanged, `modal deploy` can be a no-op. The switcher
explicitly performs `modal app rollover --strategy recreate` after the
Secret update, ensuring old runtime environments are replaced.
This may temporarily interrupt inflight work. Never automatically retry
an uncertain GPU execution; reconcile its PostgreSQL state first.

In mock mode, run `scripts/smoke_modal_cpu.py --base-url YOUR_HTTPS_URL`
to validate fake results marked `is_mock_result=true`. Do **not** use
the CPU mock smoke script against the active real-GPU endpoint.

## 6. Limits and incident handling

- Failed/uncertain GPU calls are isolated per model; ambiguous dispatch or
  execution never triggers automatic retry.
- Retry is operator/client-initiated only for confirmed `failed` attempts.
- PostgreSQL counters enforce per-minute, daily-job and daily-model-run
  submission limits. These are **not** dollar-based GPU budget caps.
- Reconciliation and retention are manually invoked; there is no scheduled
  billable background process for idle polling.
- `modal app stop translation-ai-inference-api-and-model-workers` terminates
  the public App but does not delete PostgreSQL or persistent model Volumes.
  For temporary disabling of real inference while retaining the API, prefer
  switching to `modal-cpu-mock`.
- Prior Hy-MT2 semantic errors remain unresolved as a quality certification
  matter. P6 has passed the exact 1,000-character boundary and two
  same-model concurrent submissions, but security, throughput, sustained
  soak and staging fault-injection tests are still outstanding. See the
  [P6 reliability report](p6-api-reliability-validation.md).

Additional guidance: [P2 operational safety](p2-operational-safety.md),
[Modal scale-to-zero](https://modal.com/docs/guide/scale) and
[Modal deployment rollover](https://modal.com/docs/guide/managing-deployments).


## 7. P7 — CPU monitoring and optional estimated USD admission

The main Modal App now also deploys
`translation_inference_cpu_operations_safety_monitor`, a **CPU-only function
scheduled hourly**. It aggregates PostgreSQL job state, reports stale
running/dispatching work, uncertain statuses, and recent error codes in
Modal Logs. It **never** starts GPU work or retries failed/uncertain jobs.
The operator must check the dashboard; there is no external notification
channel attached.

The API supports optional paired Secret variables
`TRANSLATION_ESTIMATED_GPU_USD_PER_RUN` and
`TRANSLATION_MAX_ESTIMATED_GPU_USD_PER_DAY`. When explicitly configured
together, PostgreSQL atomically reserves a fixed, **estimated** USD amount
for every GPU model run; requests over this admission budget return HTTP 429.
This is **not** a true Modal spending cap. The live values have not been set
because no operator amount was provided.

The authenticated workspace's actual metered/billed costs can be inspected
without allocating GPUs:

```bash
set -a; source .env; set +a
PYTHONPATH=src python scripts/check_production_safeguards.py \
  --profile YOUR_MODAL_PROFILE
```

Set an authoritative Workspace Budget in Modal's **Usage and Billing**
settings to protect actual spend. See the full
[P7 safeguards runbook](p7-production-safeguards.md) and
[CPU-only monitoring result](../reports/p7_cpu_only_live_safeguards_snapshot_v1.json).
