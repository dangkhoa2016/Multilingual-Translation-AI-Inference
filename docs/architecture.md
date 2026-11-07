# Architecture — asynchronous multilingual translation

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](architecture.vi.md)

## Design goals

Serve four different large translation models on independently scaling
NVIDIA L40S instances without paying for always-on GPU inference. Keep
user-facing operations asynchronous, persist results durably in PostgreSQL
and isolate each model's failures.

## Request flow

```text
Authorized API client
        |
        | Bearer token + optional Idempotency-Key
        v
Modal CPU FastAPI gateway ----------------- GET /health
        |
        | PostgreSQL transaction, quotas, job + model-run records
        v
PostgreSQL (provider independent)
        |
        | claim token + model-specific Modal RPC spawn
        v
+----------------------+  +----------------------+  +----------------------+
| Hy-MT2 L40S worker   |  | Index L40S worker    |  | Gemma / Qwen workers |
| own GGUF Volume      |  | own GGUF Volume      |  | own GGUF Volumes     |
| llama.cpp loopback   |  | llama.cpp loopback   |  | llama.cpp loopback   |
+----------------------+  +----------------------+  +----------------------+
        |                         |                         |
        +-------------------------+-------------------------+
                                  |
                            Durable results
                                  |
                          Authenticated GET job
```

All four worker classes are defined in [`modal_app.py`](../modal_app.py).
Their shared model lifecycle is implemented in
[`gpu_runtime.py`](../src/translation_ai_inference/gpu_runtime.py).
The gateway uses one Modal App, not four unrelated public GPU URLs.

## Resource lifecycle

| Resource | Behavior |
|---|---|
| CPU gateway | Authenticates, validates, persists and dispatches |
| PostgreSQL | System of record for jobs, attempts, quotas, results and idempotency |
| Four L40S classes | Each has its own pinned GGUF and persistent Volume |
| GPU worker | Loads a single model once per container; `min_containers=0` |
| Model server | Local `llama-server` on `127.0.0.1`, never a public port |
| CPU operations monitor | Hourly aggregate check without GPU allocations |

The GPU worker limits are `max_containers=1` for each model, and
`scaledown_window=5` seconds. These controls reduce idle GPU compute
but are not a guarantee of availability or fixed cold-start latency.

## Failure and consistency boundaries

PostgreSQL can commit a queued job before Modal acknowledges `spawn()`.
A claim token prevents a duplicate dispatcher from starting the same run.
An engine response lost after execution can leave an uncertain outcome;
automatic retries are intentionally disabled in such cases to prevent
ambiguous duplicate work. Confirmed failures can be retried explicitly,
subject to attempt and quota limits.

The gateway's `GET /v1/jobs/{job_id}` does not start a GPU.
Individual model results in a benchmark are independent; failure of one
model must not erase successful results from another.

## Security and limitations

All `/v1` endpoints require Bearer authentication. `/health` is public
and intentionally checks process configuration only, not GPU/database
availability. The deployment is single-tenant, has not undergone an
external penetration test, and provides no guaranteed end-to-end SLA.

See [deployment](deployment.md), [configuration](configuration.md),
[reliability](reliability.md), and [architecture decisions](design-decisions.md).
