# API reference and local development

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](development.vi.md)

Use the [API contract](#api-contract) to integrate your application, or the
local setup below to explore the implementation and contribute changes.
You can run the demo and automated tests without a GPU or cloud account.

## Repository layout

The source and utilities are organized by responsibility:

| Directory | Purpose |
|---|---|
| `src/multilingual_translation_ai_inference/` | Installable API, database, job and GPU runtime package |
| `scripts/api/` | API smoke checks and reliability probes |
| `scripts/deployment/` | Modal deployment and resource setup |
| `scripts/models/` | Shared model metadata, staging, CUDA build and GPU probes |
| `scripts/operations/` | Database maintenance and operational checks |
| `scripts/examples/` | Local demonstration |
| `tests/api/`, `tests/database/`, `tests/inference/`, `tests/models/`, `tests/operations/` | API, storage, inference, model and operations regressions |
| `tests/documentation/`, `tests/evidence/`, `tests/integration/`, `tests/notebook/`, `tests/security/` | Documentation contracts, recorded evidence, integration, notebooks and publication safeguards |

For model validation without GPU allocation:

~~~bash
python -m scripts.models.verify_manifest
python -m scripts.models.verify_gguf
~~~


The project is a Python application with FastAPI, SQLAlchemy,
PostgreSQL and Modal. You can test the API and job state machine
**without a GPU or a cloud account**.

## Run locally

```bash
git clone https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference.git
cd Multilingual-Translation-AI-Inference
git checkout v1.0.0
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python scripts/examples/local_demo.py
```

The example creates a temporary SQLite database and uses a fixed demo-only
Bearer token inside its script. It does not read `.env` or use network/GPU
resources. Labelled mock responses let you explore the job workflow locally.
Configure `.env` separately only for tools requiring credentials, migrations
or an actual deployment; see [configuration](configuration.md).

## Verification commands

```bash
python -m pytest -q
python -m ruff check .
python -m compileall -q src modal_app.py scripts tests
python -m pytest -q tests/security/test_publication_safety.py
```

CI runs CPU-only tests and focused publication-safety checks on GitHub.
Do not put actual tokens, database URLs or licensed model weights
in fixtures, workflow logs or pull requests.

### Deployment dependency profile

CI checks both the default dependency set and the deployed gateway profile.
To check the latter, create and activate a separate virtual environment, then run:

```bash
python -m pip install -c constraints/deployed-gateway.txt -e '.[dev]'
python -m pip check
python -m pytest -q
```

The constraints pin three core API libraries; transitive dependencies remain flexible.
On Windows, use `.\.venv\Scripts\python.exe` in place of `python` in the commands above.

CI also runs PostgreSQL transaction regressions against an isolated PostgreSQL
service. To run them locally, set `TRANSLATION_TEST_POSTGRESQL_URL` privately
to a **dedicated test database**, then run
`python -m pytest -q tests/database/test_postgresql_job_safety.py`.
The test account needs permission to create and drop schemas: each test creates
a unique schema and removes it afterward. These checks are skipped when the
variable is unset; the remaining CPU tests continue to use SQLite.

## API contract

- `GET /health`: process health (public; not a deep readiness probe).
- `GET /v1/models`: authenticated model catalog.
- `POST /v1/jobs/translations`: one model, HTTP 202.
- `POST /v1/jobs/benchmarks`: 1–4 model keys, HTTP 202.
- `GET /v1/jobs/{job_id}`: authenticated polling.
- `POST /v1/jobs/{job_id}/runs/{run_id}/retry`: explicit retry for
  confirmed failure only, subject to quotas.

Text must be valid UTF-8 and contain no NUL characters. Isolated Unicode
surrogates and NUL return HTTP 422 before job admission. Valid Unicode, emoji,
newlines and tabs are preserved at input. Validation errors omit submitted
values, validator contexts and arbitrary unknown JSON field names; unrecognized
locations are shown as `unknown_field`.

Completed translations retain leading and trailing whitespace exactly as
returned by the engine. `preserve_formatting` is a best-effort instruction to
the model, not a guarantee of exact layout fidelity.

Single-model request body for `POST /v1/jobs/translations`:

```json
{
  "model": "hy_mt2_30b",
  "source_language": "en",
  "target_language": "vi",
  "text": "The little fox crossed the bridge at sunrise.",
  "options": {"preserve_formatting": true}
}
```

For `POST /v1/jobs/benchmarks`, use `models` (plural) instead of `model`:

```json
{
  "models": ["hy_mt2_30b", "qwen35_35b"],
  "source_language": "en",
  "target_language": "vi",
  "text": "The little fox crossed the bridge at sunrise.",
  "options": {"preserve_formatting": true}
}
```

This example requests two model runs. Specify 1–4 distinct model keys to
choose the backends. **Omitting `models` selects all four registered models**,
so a GPU-mode request can incur charges for all four runs. Set the list
explicitly when you want a smaller comparison. Each new logical request
should use its own `Idempotency-Key`.

Include `Authorization: Bearer YOUR_TOKEN`; an
`Idempotency-Key` is recommended to avoid duplicate jobs. The
content must contain 1–1,000 nonblank Unicode code points, with
different source and target labels under case-insensitive comparison;
semantic aliases such as `en` and `English` are not normalized. Any printable
language name or code is accepted (1–64 characters, containing a letter),
without guaranteeing model support or translation accuracy.

### JobSubmitted and JobView — response and polling rules

**HTTP 202** from either POST endpoint returns `JobSubmitted`. The following UUIDs and payloads are **synthetic documentation examples**, not captured live inference results:

```json
{
  "job_id": "00000000-0000-0000-0000-000000000001",
  "status": "queued",
  "kind": "translation",
  "status_url": "/v1/jobs/00000000-0000-0000-0000-000000000001"
}
```

Poll the **relative** `status_url` against your private gateway using the **same Bearer token**. The authenticated `GET /v1/jobs/{job_id}` returns `JobView`, including `job.status` (summary), source/target languages and a `runs[]` array (individual model attempts).

The **synthetic four-model benchmark** example below deliberately mixes a completed mock run, a confirmed failure, an uncertain execution and an active run. This is **not** a GPU result or a translation-quality score.

```json
{
  "job_id": "00000000-0000-0000-0000-000000000010",
  "kind": "benchmark",
  "status": "execution_uncertain",
  "source_language": "en",
  "target_language": "vi",
  "runs": [
    {
      "run_id": "00000000-0000-0000-0000-000000000011",
      "model": "hy_mt2_30b",
      "attempt_no": 1,
      "status": "completed",
      "translation_text": "[MOCK ONLY — NOT A TRANSLATION]",
      "is_mock_result": true,
      "error_code": null
    },
    {
      "run_id": "00000000-0000-0000-0000-000000000012",
      "model": "index_35b",
      "attempt_no": 1,
      "status": "failed",
      "translation_text": null,
      "is_mock_result": false,
      "error_code": "SYNTHETIC_FAILURE"
    },
    {
      "run_id": "00000000-0000-0000-0000-000000000013",
      "model": "gemma4_31b_it",
      "attempt_no": 1,
      "status": "execution_uncertain",
      "translation_text": null,
      "is_mock_result": false,
      "error_code": "EXECUTION_STALE_UNVERIFIED"
    },
    {
      "run_id": "00000000-0000-0000-0000-000000000014",
      "model": "qwen35_35b",
      "attempt_no": 1,
      "status": "running",
      "translation_text": null,
      "is_mock_result": false,
      "error_code": null
    }
  ]
}
```

#### Optional per-run performance telemetry

Authenticated `GET /v1/jobs/{job_id}` returns optional `usage`, `timings` and
`resources` **inside each model attempt** in `runs[]`. The response fields
remain backward compatible; reading GET never starts GPU work.

**Illustrative non-mock response shape — all text and numbers are invented, not measurements from a GPU run.** The example sets `is_mock_result: false` to demonstrate the field value that a *real* inference result would carry; it does **not** claim that the example was produced by a model.

```json
{
  "run_id": "00000000-0000-0000-0000-000000000002",
  "model": "hy_mt2_30b",
  "attempt_no": 1,
  "status": "completed",
  "translation_text": "Synthetic example only",
  "is_mock_result": false,
  "error_code": null,
  "usage": {
    "prompt_tokens": 120,
    "completion_tokens": 80,
    "total_tokens": 200
  },
  "timings": {
    "queue_ms": 1450.0,
    "inference_ms": 2450.0,
    "total_ms": 4010.0,
    "prefill_ms": 350.0,
    "decode_ms": 2050.0,
    "tokens_per_second": 39.02
  },
  "resources": {
    "cpu_process_seconds": 0.36,
    "cpu_utilization_percent": 14.69,
    "sampled_vram_mib": 31200,
    "sampled_gpu_utilization_percent": 2
  }
}
```

| Fields | Meaning and units |
|---|---|
| `usage.prompt_tokens`, `completion_tokens`, `total_tokens` | Engine-provided counts, not character length |
| `timings.queue_ms` | Attempt created to worker start; can include Modal cold start |
| `timings.inference_ms` | Worker-side engine request wall time, excluding queue |
| `timings.total_ms` | Attempt created to persisted completion; not Rails polling |
| `timings.prefill_ms`, `decode_ms` | Engine-reported timings when available |
| `timings.prompt_per_second`, `tokens_per_second` | Engine-reported throughput; not always available |
| `resources.cpu_process_seconds`, `cpu_utilization_percent` | CPU used by llama.cpp process during inference; multicore percentages may exceed 100% |
| `resources.sampled_vram_mib`, `sampled_gpu_utilization_percent` | One **post-inference** GPU snapshot, not peak, average, or per-token utilization |

Absent groups are `null`, and absent individual measurements are omitted.
Missing values are **unknown, not zero**. Invalid optional token counts are
omitted without discarding the translation; valid counts from the same response
remain available. Older jobs, queued attempts, failed
runs and CPU mocks may not have token/GPU metrics; retries have separate
`run_id` and `attempt_no`. Telemetry never includes server logs, credentials,
GPU UUIDs or filesystem paths. Do not infer billed GPU cost from these
measurements.

For a deployed legacy database, run the migration documented in
[deployment](deployment.md) before updating gateway/workers. Fresh installs
already include the nullable columns; migration `0004_run_metrics` adds only
those missing on older databases. No GPU inference is required for migration.

#### Unsupported language pair result

The API accepts any valid language label without a fixed allowlist. A model may
respond with the exact sentinel `UNSUPPORTED_LANGUAGE_PAIR`; in that case the
GPU worker records a **failed run** with
`runs[].error_code = "UNSUPPORTED_LANGUAGE_PAIR"` and no translation.
Clients should preserve this code in the job result instead of displaying
an unspecified error. This signal is **model-generated**, not a reliable
language-support detector: other unsupported pairs may still produce
incorrect or fabricated translations. Check the latest attempt for each model.

#### Status meaning

| Status | Interpretation and safe client action |
|---|---|
| `queued` / `dispatching` / `running` | Pending, being dispatched, or executing; keep authenticated GET polling with a bounded interval. |
| `completed` | Model run finished successfully; `translation_text` may contain output. Inspect `is_mock_result` before calling it an actual translation. |
| `failed` | Confirmed model failure; do not infer other models failed. Explicit per-run retry is possible **only** under the API's retry/quota policy. |
| `partial_failed` | **Job-level summary only:** at least one latest run completed, at least one latest run failed, and all latest runs are resolved as completed/failed. |
| `dispatch_uncertain` | Dispatch outcome cannot be confirmed; operator reconciliation is required. **Never automatically create a replacement paid POST.** |
| `execution_uncertain` | Execution outcome cannot be confirmed; operator reconciliation is required. **Never automatically create a replacement paid POST.** |

**Important: `job.status` is not the polling-stop criterion by itself.** It summarizes the **latest attempt per model** (largest `attempt_no`), while `runs[]` can also contain earlier attempts. In particular, an uncertain latest run can make `job.status="execution_uncertain"` **while another model is still `running`** (as above). Continue GET polling while *any* latest run is `queued`, `dispatching` or `running`. Once every latest run is `completed` or `failed`, the job is resolved; `completed`/`partial_failed`/`failed` describe the overall outcome. If every latest run has stopped active processing but one is `dispatch_uncertain` or `execution_uncertain`, this is **not a confirmed final result**: preserve the UUID, investigate via operations/reconciliation and GET later as appropriate. Do not automatically retry an uncertain run or POST.

**Terms:** `attempt` is one execution attempt of a model, identified by `run_id` and `attempt_no`. `admission` is the transactional pre-dispatch quota/budget-reservation decision; estimates are **not** actual Modal billing. `runtime_verified` in the model catalog reflects recorded runtime validation metadata, **not** a live worker health probe or a translation-quality guarantee. The backward-compatible `enabled` flag means a model can receive jobs in GPU dispatcher mode, not that a GPU is currently awake. `dispatch_enabled` reports that dispatcher mode explicitly; `runtime_status="not_checked"` means no live GPU readiness check was attempted by this GET. Authentication failures are rate limited per gateway process; see [security](security.md).

## Contributing code and documentation

Keep model-specific inference decisions behind the GPU runtime boundary.
Preserve the PostgreSQL transaction and claim-token semantics.
For each user-facing Markdown document, supply matching English and
Vietnamese versions with working language-switch links. Prefer
small, focused source commits and explain behavior changes in tests.

See [contribution guide](../.github/CONTRIBUTING.md),
[architecture](architecture.md) and [security](../.github/SECURITY.md).
