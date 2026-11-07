# Reliability — verified API boundaries and known limits

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](reliability.vi.md)

The results below document **bounded real GPU experiments**, not a
guaranteed SLA, exhaustive load test, or certified translation quality.

## Real HTTP tests

| Scenario | Observed result | Evidence |
|---|---|---|
| Exactly 1,000 Unicode code points to four models | 4/4 completed, nonmock | [Boundary report](../reports/unicode_input_boundary.json) |
| 1,001 characters and invalid language/blank inputs | HTTP 422, no accepted run | [Boundary report](../reports/unicode_input_boundary.json) |
| Same idempotency key and payload | Job reused, no duplicate reservation | [Boundary report](../reports/unicode_input_boundary.json) |
| Same key, different payload | HTTP 409 conflict | [Boundary report](../reports/unicode_input_boundary.json) |
| Two near-simultaneous submissions to Hy-MT2 | Two distinct completed jobs | [Concurrent report](../reports/concurrent_model_jobs.json) |
| Two immediate Hy-MT2 readiness calls | Same GPU UUID; warm reuse observed | [Container report](../reports/gpu_container_reuse.json) |
| Four independently active models | Four distinct L40S GPU UUIDs | [Parallel inference](../reports/four_gpu_parallel_inference.json) |

The 1,000-character test contained non-ASCII text and measured more than
1,000 UTF-8 bytes: character limits refer to **Unicode code points**.

Two immediate readiness calls measured **25.104 s** and **0.459 s**
end-to-end RPC durations. The first call was not guaranteed cold;
neither measurement is an SLA. Two concurrent API submissions
to **the same model** do not imply parallel execution on one GPU,
because that class is limited to one container.

## Failure handling

The CPU-only unit suite simulates:
- a model socket timeout or broken connection;
- invalid completion JSON and a truncated/reasoning-only completion;
- repeated idempotency keys and racing quota reservations;
- definite failure versus uncertain dispatch or execution;
- retry limitations, retained completed results and state reconciliation.

An ambiguous execution is **not automatically retried**. A cancelled or
reconciled database record does not prove that the GPU provider stopped
an already-running engine call.

## How to reproduce safely

```bash
# Does not allocate GPUs:
python -m pytest -q
python -m ruff check .
PYTHONPATH=src python scripts/api_reliability_smoke.py

# Billable, opt-in real API checks:
set -a; source .env; set +a
export TRANSLATION_GATEWAY_BASE_URL="https://YOUR_GATEWAY.modal.run"
PYTHONPATH=src python scripts/api_reliability_smoke.py --run-boundary
PYTHONPATH=src python scripts/api_reliability_smoke.py --run-concurrency
PYTHONPATH=src python scripts/gpu_container_reuse.py --run
```

## Outstanding work

Larger burst and soak tests, fault injection in an **isolated staging
deployment**, external alerting, actual provider-level budget enforcement
and human-reviewed translation quality evaluations remain necessary.
See [operations](operations.md) and [benchmarking](benchmarking.md).
