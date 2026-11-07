# P6 — API reliability and input-boundary validation

Date: 2026-11-07

## Scope

This is a bounded real-GPU API reliability exercise for the four independently
scalable Modal L40S workers. It is **not** a translation-quality benchmark,
full production soak test or a guarantee of future latency.

Production API contract: one authenticated CPU FastAPI gateway, four
independent GPU classes, PostgreSQL-backed asynchronous jobs, no unauthenticated
GPU HTTP endpoints, and `min_containers=0` per GPU class.

## Live result 1: exact Unicode character boundary

One real benchmark job with **exactly 1,000 Unicode code points**
(**1,002 UTF-8 bytes**) was accepted and dispatched to all four models.
The input contained multiple paragraphs, English sentences, and the
non-ASCII character `é`.

| Model | PostgreSQL state | Model output | Output characters |
|---|---|---|---:|
| Hy-MT2-30B-A3B | `completed` | Real, nonempty; `is_mock_result=false` | 1,189 |
| Index-Translate-35B-A3B-preview | `completed` | Real, nonempty; `is_mock_result=false` | 1,381 |
| Gemma 4 31B IT | `completed` | Real, nonempty; `is_mock_result=false` | 1,141 |
| Qwen3.5-35B-A3B | `completed` | Real, nonempty; `is_mock_result=false` | 1,024 |

The client-side script measured **82.35 seconds** from its negative
validation requests through final API polling. The shell process used
~88 seconds. Do not interpret these wall times as guaranteed latency,
per-model inference latency, GPU billable seconds, or quality scores.

The following inputs were rejected with **HTTP 422** without a valid GPU
job: 1,001 code points, whitespace-only input, same source and target
language, and an unknown target language. A request replay with the same
idempotency key returned the same job ID; a conflicting payload with the
same key returned **HTTP 409**.

Evidence: [Boundary results](../reports/p6_four_models_exactly_1000_codepoints_v1.json).

## Live result 2: two submissions to the same single-container model

Two independent authenticated POST requests to `hy_mt2_30b` were submitted
through a two-thread client; two distinct job IDs were created.

- POST acceptance latency: **0.487 s** and **0.928 s**.
- Both runs reached `completed` with nonempty nonmock output.
- Entire exercise: **29.839 s**, including polling.
- Neither run was retried; both were on their original attempt.

This proves the API accepts independent concurrent submissions and the
PostgreSQL/Modal pipeline delivers both results under `max_containers=1`.
It does **not** prove simultaneous GPU inference on one model; sequential
execution or queueing is appropriate for this configuration. Different
model classes already passed an independent four-L40S simultaneous execution
test in P4.

Evidence: [Same-model concurrency result](../reports/p6_same_model_two_concurrent_jobs_v1.json).

## Live result 3: immediate container reuse

Two consecutive authenticated Modal `Cls.readiness` RPC calls targeted
the deployed Hy-MT2 worker:

| Call | End-to-end RPC wall time |
|---|---:|
| First | **25.104 s** |
| Second | **0.459 s** |

Both calls reported the same NVIDIA L40S GPU UUID and loaded model.
The script therefore observed warm worker reuse in this particular run.
The first call was **not guaranteed to start cold**, so the 25.104 s is
not a canonical cold-start SLA. The P5 class readiness run separately
measured internal model initialization of ~24.1–38.4 s for the four models,
but does not guarantee repeatability across Modal capacity conditions.

Evidence: [Container reuse probe](../reports/p6_hy_mt2_container_reuse_v1.json).

## Offline failure, timeout and security regressions

CPU-only pytest checks assert:

- 1,000 Unicode code points are accepted by the schema; 1,001 rejected
  with HTTP 422 before a PostgreSQL job or GPU dispatch is created.
- Nonexistent authentication fails with HTTP 401 without creating a job.
- Replays reuse the job; conflicting payloads return HTTP 409.
- Simulated local HTTP socket timeout, connection drop, and invalid
  inference JSON produce `ExecutionUncertain` instead of a
  confirmed-failure response.
- Unknown outcomes must **not be retried automatically**; earlier P2/P5
  tests enforce claim-token fencing and late worker completion.
- GPU test reports contain only state, lengths and SHA256 of synthetic
  outputs, not bearer tokens or raw translation text.

The timeout faults above were deliberately simulated in unit tests.
We **did not kill an actual GPU worker or induce a production timeout**:
that could leave paid, ambiguously running jobs and would require
careful operator reconciliation.

## Reproduction with explicit GPU cost opt-in

```bash
# CPU-only fixture preflight; no GPU allocation
PYTHONPATH=src python scripts/p6_api_reliability_smoke.py
PYTHONPATH=src python -m pytest -q tests/test_p6_reliability.py

# Authenticated HTTPS gateway and existing secret from an untracked .env
set -a; source .env; set +a
export TRANSLATION_GATEWAY_BASE_URL="https://YOUR_DEPLOYED_GATEWAY.modal.run"

# One benchmark = at most four real GPU model runs
PYTHONPATH=src python scripts/p6_api_reliability_smoke.py --run-boundary

# Two unique Hy-MT2 GPU jobs; queued if max_containers=1
PYTHONPATH=src python scripts/p6_api_reliability_smoke.py --run-concurrency

# Two deployed Hy-MT2 readiness RPCs, one GPU class
PYTHONPATH=src python scripts/p6_gpu_container_reuse.py --run
```

Neither script automatically retries ambiguous results. The test scripts
never modify production Modal Secrets, their GPU lifecycle, or schema
migrations. Persistent GPU weights remain in four dedicated Volumes.

## Remaining reliability and production hardening

This milestone verifies **specific bounded scenarios**, not all reliability
requirements. Still open:

- Larger controlled burst/soak tests, concurrency and throughput under
  workload-specific realistic distributions.
- Long-text tests on all eight EN↔VI, DE↔VI, JA↔VI, KO↔VI directions
  and human-reviewed reference quality evaluation.
- Fault injection in a protected staging deployment, including GPU crashes,
  provider unavailability, restart, queue drains, cancellation and operator
  reconciliation. Avoid fault-injecting into the live API directly.
- USD-denominated GPU cost ceilings and alerting; PostgreSQL request quotas
  are **not** a substitute for a dollar budget.
- Full threat modeling, multi-tenant identity, connection-pool exhaustion
  and end-to-end latency SLOs.

**Gate result:** P6 1000-codepoint boundary, two same-model submissions,
and immediate deployed worker reuse passed. Production hardening is still
outstanding, and these checks do not certify translation correctness.
