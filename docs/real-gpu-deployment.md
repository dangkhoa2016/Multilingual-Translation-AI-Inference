# Real GPU inference on four Modal L40S workers

Date: 2026-11-07

## Current deployment

The application `translation-ai-inference-api-and-model-workers` has
**one authenticated CPU FastAPI gateway**, one retained CPU mock worker for
safe local/operational tests, and **four independently scaling GPU classes**.
The CPU gateway uses `TRANSLATION_DISPATCHER_MODE=modal-gpu` in the Modal
API Secret. Both translation and benchmark POST routes now dispatch genuine
GPU work; `GET /v1/jobs/{job_id}` does not allocate GPU.

| API model key | Modal GPU class | Dedicated GPU | GGUF |
|---|---|---|---|
| `hy_mt2_30b` | `HyMT2L40SWorker` | L40S 48 GB | Hy-MT2-30B-A3B Q8_0 |
| `index_35b` | `IndexTranslateL40SWorker` | L40S 48 GB | Index-Translate-35B-A3B-preview Q8_0 |
| `gemma4_31b_it` | `Gemma4L40SWorker` | L40S 48 GB | Gemma 4 31B IT Q8_0 |
| `qwen35_35b` | `Qwen35L40SWorker` | L40S 48 GB | Qwen3.5-35B-A3B Q8_0 |

Every class has a dedicated, full-SHA256-verified Volume. The GPU image
builds the previously verified llama.cpp CUDA revision
`fd27b2034905f8dadd8bd6d2cc44595f4929d391`. Each container starts
its own `llama-server` **once** in `@modal.enter()`, listens only on local
`127.0.0.1`, serves the assigned model, and shuts down at `@modal.exit()`.
Containers specify `min_containers=0`, `buffer_containers=0`,
`max_containers=1`, and `scaledown_window=5` per model.

The API URL is the one emitted by the deployed Modal CPU gateway:
`https://YOUR_DEPLOYED_MODAL_GATEWAY.modal.run` (replace with the URL from
your own Modal deployment).
Only `/health` is intentionally public. All `/v1` endpoints require
`Authorization: Bearer <TOKEN>`; model GPU classes have **no public HTTP URLs**.

## Verified live evidence

All artifacts below come from actual Modal L40S and PostgreSQL execution,
not simulated inference:

| Verification | Result | Durable report |
|---|---|---|
| Four distinct deployed GPU classes, 4 GPU UUIDs, model loaded | PASS | [Deployed class readiness](../reports/p5_deployed_four_gpu_classes_readiness_v1.json) |
| One PostgreSQL benchmark job, four Modal GPU workers, nonmock results, authenticated API GET | PASS, 4/4 | [PostgreSQL integration](../reports/p5_postgresql_four_gpu_job_integration_v1.json) |
| Authenticated `POST /v1/jobs/translations`, same-key reuse, nonmock GET | PASS, Hy-MT2 | [Real API single-model smoke](../reports/p5_real_gpu_api_single_model_smoke_v1.json) |
| Authenticated `POST /v1/jobs/benchmarks`, four real model outputs persisted | PASS, 4/4 | [Real API benchmark smoke](../reports/p5_real_gpu_api_four_model_smoke_v1.json) |
| Four independent real model executions overlap across four different L40S GPU UUIDs | PASS (P4) | [Four concurrent model runtimes](../reports/p4_four_l40s_models_runtime_smoke_v1.json) |

The PostgreSQL integration test used **849 source characters** across four
models and completed in **~68 seconds** end to end. The real API
four-model benchmark completed in **~54.5 seconds** including HTTP orchestration,
cold starts and polling. These timings depend on Modal resource availability;
they are **not** guaranteed latency targets.

The four-model P5 API reports do not assert overlapping GPU execution
timestamps; P4 explicitly measured simultaneous model execution on four
different GPU UUIDs, and P5 verified four distinct deployed-class identities.

## API contract and background job safety

```bash
export BASE_URL="https://YOUR_DEPLOYED_MODAL_GATEWAY.modal.run"
# Load TRANSLATION_API_BEARER_TOKEN from your untracked .env or secret manager.
curl -fsS "$BASE_URL/health"
curl -fsS "$BASE_URL/v1/models" \
  -H "Authorization: Bearer $TRANSLATION_API_BEARER_TOKEN"
curl -fsS -X POST "$BASE_URL/v1/jobs/translations" \
  -H "Authorization: Bearer $TRANSLATION_API_BEARER_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: example-translation-001' \
  -d '{"model":"hy_mt2_30b","source_language":"en","target_language":"vi","text":"Good morning!"}'
# Poll /v1/jobs/{job_id} from the returned status_url.
```

- Job state, results, attempt histories and idempotency keys remain in PostgreSQL.
- GPU work is invoked through internal `modal.Cls.from_name(...).process_job.spawn()`.
- `claim_dispatch()` and `start_run()` fence duplicate executions with
  random claim tokens; repeated HTTP requests with the same idempotency key
  must not create extra jobs or model runs.
- A confirmed unusable completion marks only its own model run `failed`;
  an ambiguous GPU failure is marked `execution_uncertain` and **never
  automatically retried**. Operators must investigate uncertain states.
- Real translations are saved with `is_mock_result=false` and available token
  usage; mock results retain `is_mock_result=true`.
- The gateway remains CPU-only; GET/poll traffic never requires GPU resources.
- `/health` returns `inference_enabled=true` only when the deployed
  dispatcher is set to `modal-gpu`.

## Reproduction and safe operations

The following commands require an authenticated Modal workspace, existing
named Volumes/Secrets and their authorized contents.

```bash
# CPU-only offline tests and static checks:
python -m pytest -q
python -m ruff check .

# Explicit remote GPU allocations, four deployed classes:
PYTHONPATH=src python scripts/verify_deployed_four_gpu_classes.py --run

# Real GPU end-to-end HTTP, one model and four models respectively:
set -a; source .env; set +a
export TRANSLATION_GATEWAY_BASE_URL="https://YOUR_DEPLOYED_MODAL_GATEWAY.modal.run"
PYTHONPATH=src python scripts/smoke_modal_gpu_api.py --run
PYTHONPATH=src python scripts/smoke_modal_gpu_api.py --run --all-models
```

**Switch to mock, or switch back to GPU, without exposing secrets in
command-line arguments:**

```bash
# Dry run; reads no secret values in output.
python scripts/set_modal_dispatch_mode.py --to-mock
# Explicit change; requires the existing local API bearer token to match
# the currently deployed gateway. Export the gateway URL as above.
set -a; source .env; set +a
export TRANSLATION_GATEWAY_BASE_URL="https://YOUR_DEPLOYED_MODAL_GATEWAY.modal.run"
python scripts/set_modal_dispatch_mode.py --to-mock --apply
python scripts/set_modal_dispatch_mode.py --to-gpu --apply
```

The switcher writes an owner-private temporary JSON file, updates the Modal
authentication Secret, redeploys the App, and explicitly executes
`modal app rollover --strategy recreate` to refresh the Secret in running
containers. A no-op redeploy alone does not guarantee immediate Secret
refresh. This operation can briefly interrupt requests; investigate
`dispatch_uncertain` rather than resubmitting blindly.

You can also pass the gateway URL using `--base-url` and select the
authenticated account using `--profile` or `TRANSLATION_MODAL_PROFILE`.
The development `.env` may still choose `inline-mock` locally; it **does
not control the deployed Modal Secret**. Never commit the `.env`, bearer
token, database URL or full translation text from private traffic.

## Limits: operationally live does not imply quality certification

- The four GGUFs were checked against their pinned SHA256 and successfully
  ran EN→VI smoke tests. Translation quality across all eight directions
  (EN↔VI, DE↔VI, JA↔VI, KO↔VI) still needs an independently referenced,
  human-reviewed benchmark.
- An earlier Hy-MT2 diagnostic found real semantic material substitutions,
  including a silver compass becoming copper/brass. A glossary helped known
  cases but did not prove general correctness.
- P6 verified an actual **1,000-Unicode-codepoint** four-model benchmark
  through the production API and rejected 1,001 characters with HTTP 422.
  Two same-model concurrent API submissions and Hy-MT2 immediate container
  reuse were also validated. Extended soak, burst-load, production fault
  injection and recovery remain outstanding. See
  [P6 reliability and boundary results](p6-api-reliability-validation.md).
- No per-provider dollar limit, multi-tenant identity, automatic safe
  reconciliation daemon or full production security audit is implemented.
- Scale-to-zero reduces idle GPU compute charges but persistent model Volumes,
  startup, DB and ancillary services may still be billed.
- Modal L40S availability/capacity is subject to provider and account limits.

**Current outcome:** The end-to-end production API is technically live for
authenticated real GPU translation, with 4/4 tested models. It should remain
limited to controlled usage until quality, capacity, security and budget
requirements are independently satisfied.
