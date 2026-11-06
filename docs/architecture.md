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
      | Bearer token + optional Idempotency-Key
      v
+--------------------------------------------------------------------+
| Modal App: CPU gateway and FOUR independently scaling L40S workers  |
|                                                                    |
| CPU FastAPI gateway --------------------------- GET /health         |
|       |                                                            |
|       | Per-model Modal RPC after durable job creation             |
|       +--> Hy-MT2 worker    [L40S] <--> [Hy-MT2 GGUF Volume]       |
|       +--> Index worker     [L40S] <--> [Index GGUF Volume]        |
|       +--> Gemma worker     [L40S] <--> [Gemma GGUF Volume]        |
|       +--> Qwen worker      [L40S] <--> [Qwen GGUF Volume]         |
|           (each model server uses private llama.cpp loopback)      |
+--------------------------------------------------------------------+
       | jobs, attempts, quotas, idempotency and results
       v
External PostgreSQL (durable system of record)
       |
       +--> Authenticated GET /v1/jobs/{job_id} via CPU gateway
```

All four worker classes are defined in [`modal_app.py`](../modal_app.py).
Their shared model lifecycle is implemented in
[`gpu_runtime.py`](../src/multilingual_translation_ai_inference/gpu_runtime.py).
The gateway uses one Modal App, not four unrelated public GPU URLs.

## Resource lifecycle

| Resource | Behavior |
|---|---|
| CPU gateway | Authenticates, validates, persists and dispatches |
| PostgreSQL | System of record for jobs, attempts, quotas, results and idempotency |
| Four L40S classes | Each has its own pinned GGUF and persistent Volume |
| GPU worker | Loads a single model once per container; `min_containers=0` |
| Model server | Local `llama-server` on `127.0.0.1`, never a public port |
| CPU operations monitor | Optional hourly PostgreSQL checks, disabled by default; no GPU |

The worker configuration supports independent scale-to-zero operation
and predictable per-model resource isolation.

## Durable jobs

The API stores job and model-run state in PostgreSQL and dispatches
work asynchronously. Each model run is tracked independently, and
clients retrieve available results via authenticated polling.
Idempotency keys support consistent repeated submissions.

## API access

API clients use Bearer authentication for `/v1` routes.
Health checks, environment settings and network access are described
in the [deployment guide](deployment.md).

See [deployment](deployment.md), [configuration](configuration.md),
[reliability](reliability.md), and [architecture decisions](design-decisions.md).
