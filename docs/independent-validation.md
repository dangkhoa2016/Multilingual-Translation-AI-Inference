# Verify your installation

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](independent-validation.vi.md)

Use this guide to check a local installation, connect the notebook to your
own gateway, and verify a self-hosted deployment. Start with the CPU demo;
GPU checks require your own configured resources and incur cloud charges.

## 1. Check the local API workflow

Follow the [quick start](../README.md#quick-start--no-gpu-required) in a fresh
Python 3.12+ virtual environment with `.[demo]` installed, then run:

```bash
python -m pip check
python scripts/examples/local_demo.py
```

Expect **POST 202**, **GET 200**, `status: completed` and
`is_mock_result == true`. This exercises submission, storage and retrieval
using temporary SQLite and mock text. Real translation is checked separately
on your deployed gateway.

## 2. Run the full demo from the notebook

Open the [API notebook](../notebooks/translation_api_demo.ipynb) on Jupyter, Colab or Kaggle. `DISPLAY_LANGUAGE="en"` is the default (change to `"vi"` for Vietnamese). Choose `DEMO_MODE="offline"` and **Run All** for an entirely synthetic no-network/no-GPU warm-up and three-round demo.

For GPU testing on **your own deployment**:

1. Activate `modal-gpu` using the operator-only steps in [deployment](deployment.md), confirm `/health` has `phase="gpu"`, `inference_enabled=true`, and selected models in `/v1/models` are enabled/runtime-verified.
2. Private `TRANSLATION_GATEWAY_BASE_URL` and `TRANSLATION_API_BEARER_TOKEN` from Colab/Kaggle Secrets or environment variables are optional. Missing values or Secrets timeouts trigger **hidden input prompts** when you Run All.
3. Select `DEMO_MODE="gpu"` and keep the default `BENCHMARK_SEQUENCE="per_model"`; review `WARMUP_TEXT` and the three `MEASUREMENT_TEXTS`. With four models, **Run All submits up to 16 real API jobs**: four single-model translation warm-ups followed immediately by three single-model benchmark jobs per model (**16 GPU model runs**). The optional `BENCHMARK_SEQUENCE="parallel"` preserves the previous five-API-job multi-model workflow, also with 16 GPU model runs. GPU charges may apply.
4. Keep the default 60-second GPU idle scaledown window for the normal `per_model` demo; the optional 120-second window is for longer experiments and requires restoration afterward. Warm idle GPUs can incur charges. Click **Run All**; hidden prompts request missing credentials and jobs are polled in order. Only translate public, non-sensitive samples if sharing outputs.

GPU Run All spaces successive new POSTs by at least 6.25 seconds to fit the default 10 jobs/minute quota on an otherwise idle gateway. This does not override the operator's quota: if the gateway is already busy or configured more tightly, a definite HTTP 429 still stops the demo, without automatically replaying POST.

If `GET /health` returns HTTP 403 via a Cloudflare custom domain, a proxy rule may block the Python client. The notebook sends an explicit API User-Agent. If needed, use your own direct Modal HTTPS Gateway URL or adjust Cloudflare rules. Never put the Bearer token into a URL.

Any failed, uncertain or mock warm-up/measurement stops the demo before another paid POST. Incomplete comparisons never count as full-demo success.

The notebook is a CPU HTTP client: no Kaggle/Colab GPU is needed. It does not enable GPU dispatch by itself. No legacy `RUN_*_POST` or paid acknowledgement flags are used.

**Transient GET failures:** HTTP 429 is retried with `Retry-After` within the polling deadline; 502/503/504 and network errors have bounded GET-only retry/backoff. Authentication and conflicts fail fast. No polling retry re-sends paid POST requests.

**Model comparison:** The responsive HTML table escapes all text and shows each model's latest attempt, safe error code and available numeric metrics. Unavailable fields show `N/A`.

### Temporary GPU scaledown window for benchmarking

The four L40S workers default to `scaledown_window=60` seconds and `min_containers=0`. In a real official GPU run, Gemma-4 lost reuse for TEXT 2: the gap between TEXT 1 completion and TEXT 2 admission was 7.034 seconds, exceeding the former five-second idle window. Modal logs confirmed different worker containers, although the precise shutdown cause was not logged. The 60-second window accommodates normal HTTP preflight, notebook polling and 6.25-second POST pacing but cannot guarantee reuse. Idle warm GPUs may incur charges. For longer warm-retention experiments, consider 120 seconds while **keeping `min_containers=0`**; restore 60 seconds afterward. Public gateway `GET /health` is CPU-only and does not warm GPU model servers.

In a terminal authenticated to **your own** Modal workspace, substitute your own environment name:

```bash
export MODAL_ENVIRONMENT="YOUR_MODAL_ENVIRONMENT"
APP="multilingual-translation-ai-inference-api-and-model-workers"
for worker in HyMT2L40SWorker IndexTranslateL40SWorker Gemma4L40SWorker Qwen35L40SWorker; do
  modal function autoscaler update --env "$MODAL_ENVIRONMENT" \
    "$APP/$worker.*" --scaledown-window 120
done

# After the benchmark OR if interrupted, ALWAYS restore the default 60 seconds:
for worker in HyMT2L40SWorker IndexTranslateL40SWorker Gemma4L40SWorker Qwen35L40SWorker; do
  modal function autoscaler update --env "$MODAL_ENVIRONMENT" \
    "$APP/$worker.*" --scaledown-window 60
  modal function autoscaler settings --env "$MODAL_ENVIRONMENT" "$APP/$worker.*"
done
```

A 120-second window reduces the likelihood of cold starts; it cannot guarantee reuse after worker replacement or failure. API `queue_ms` includes dispatch and startup, not isolated model-load time.

### Observed GPU queue delays

An observed 16-model-run session completed all GPU jobs, but the original parallel warm-up strategy allowed earlier models to scale down while another waited. Modal's **actual Function Call history** (not estimated from the notebook) reports:

| Worker | Calls | Distinct worker containers | Longest enqueue-to-start delay |
|---|---:|---:|---:|
| Hy-MT2 | 4 | 3 | 111.18 s |
| Index-Translate | 4 | 3 | 351.00 s |
| Gemma-4 | 4 | 3 | 903.24 s |
| Qwen3.5 | 4 | 4 | 36.67 s |

These are confirmed Modal call timestamps, and no private call IDs, GPU UUIDs, tokens or customer text are reproduced here. They **do not isolate GPU capacity wait from container scheduling, GGUF loading, or runtime readiness**: Modal did not provide a standalone per-call startup duration in these records. All 16 calls completed successfully. Since each model used 3–4 different containers over four calls, the old warm-up could not guarantee warm reuse. The new default `per_model` sequence removes cross-model waiting between an individual model's warm-up and its three measurement requests; `worker_reuse_confirmed`, when deployed, provides direct same-container evidence. The updated per-model workflow was subsequently verified on an updated deployment; see the separate results below.

### Verified per-model GPU inference

An opt-in notebook run on a self-hosted GPU deployment used the default `per_model` sequence and the same three public English-to-Vietnamese sample texts for each model. **All 16/16 real GPU model runs completed** (four warm-ups and twelve measurements across 16 separate API jobs). The API reported `worker_reuse_confirmed=1` for **12/12 measured runs**. A [sanitized numeric evidence file](gpu-per-model-evidence.json) contains all sixteen run measurements, redacted of cloud identifiers and content; it permits checking the published counts and medians, not independently proving the original infrastructure provenance. Modal function statistics independently showed four successful calls in **one container per GPU worker**, with zero container errors in the run.

| Model | Warm-up queue + startup | Engine ready | Median measured queue | Median measured inference | Median measured end-to-end | Confirmed reuse |
|---|---:|---:|---:|---:|---:|---:|
| Hy-MT2 | 453.831 s | 16.025 s | 2.308 s | 0.559 s | 3.888 s | 3/3 |
| Index-Translate | 34.582 s | 23.053 s | 0.390 s | 0.448 s | 0.894 s | 3/3 |
| Gemma-4 | 36.360 s | 18.027 s | 0.584 s | 2.425 s | 3.129 s | 3/3 |
| Qwen3.5 | 35.067 s | 24.040 s | 0.580 s | 0.456 s | 1.087 s | 3/3 |

These are **observed API timings**, not guaranteed service levels or translation-quality scores. `queue_ms` measures job creation to worker execution start; `engine_ready_ms` measures only the llama.cpp server startup/readiness interval inside its container. The **Hy-MT2 warm-up queue/startup was unusually long** despite fast engine readiness. Available logs cannot attribute the full difference to GPU provisioning or model loading. Later measured requests reused the same worker; no container restart or failed function call was observed.

The main notebook execution cell finished in **11 min 28 s**, versus **21 min 11 s** for the earlier differently scheduled run. These are separate observations, **not a controlled causal performance comparison**. The three sample texts differ in length, so the medians describe this demonstration rather than normalized same-length throughput. No further paid GPU run is needed solely to verify worker reuse.

## 3. Re-run and recover safely

By default, `DEMO_RUN_ID="auto"` creates a unique UTC timestamp-based ID once per Python kernel. Repeating Run All in the **same kernel** retains that ID and reuses deterministic idempotency keys for unchanged stages and payloads. A **new kernel creates a new ID and may submit new billable GPU jobs**; do not restart and replay after an uncertain POST. To resume a known run across restarts, explicitly reuse its original ID and unchanged payload while server-side records remain available, or recover a previously accepted job UUID with GET-only mode. The notebook displays source inputs before requests and in the results; share only non-sensitive examples.

**Recover with Run All, GET-only:** Set `RECOVERY_JOB_ID="prompt"` and `DEMO_MODE="gpu"`. Run All asks for a private UUID (or reads `TRANSLATION_EXISTING_JOB_ID` from a private Secret/environment) and fetches only the existing job. The gateway need not still be in GPU mode. In the original trusted kernel `accepted_demo_job_ids()` returns accepted job UUIDs. To replace manually entered credentials, run `reset_demo_credentials()` in a temporary private cell; environment/Secrets overrides must be updated in their own settings.

**If the POST outcome is uncertain, do not run it again blindly.** Find the accepted job UUID using your private gateway/database audit records and perform authenticated **GET-only** recovery, e.g. with your own environment variables:

```bash
curl -fsS -H "Authorization: Bearer $TRANSLATION_API_BEARER_TOKEN"   "$TRANSLATION_GATEWAY_BASE_URL/v1/jobs/YOUR_ACCEPTED_JOB_UUID"
```

Do not copy private bearer tokens or real job UUIDs into public notebooks/logs. For a deliberately new evaluation, reconcile previous jobs first, then start a new kernel with `DEMO_RUN_ID="auto"` or set a fresh explicit ID.

## 4. Check your self-hosted deployment

| Component | Check | Expected result |
|---|---|---|
| Database and API | Follow [deployment](deployment.md), apply migrations and use an authenticated mock gateway | Jobs and results persist in your PostgreSQL database |
| Model files | Verify the pinned GGUF files and configure your Modal Secrets/Volumes | All four artifacts match the model manifest |
| GPU inference | Enable the GPU dispatcher and run the opt-in smoke commands in [reliability](reliability.md) | Requested runs complete with nonmock output |
| Recovery | Repeat the GET-only sequence above for an accepted job | The same job can be read without a new POST |

Record the source revision, dependency versions and observed results when
comparing installations. CPU mocks, GPU execution and translation-quality
evaluation check different aspects; see [reliability](reliability.md) and
the [community roadmap](roadmap.md) for operational and integration proposals.

## Share feedback

If a step fails or needs explanation, open a
[GitHub Issue](https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference/issues)
with your OS, Python/package versions, the step reached, expected behavior
and a minimal reproduction. Remove tokens, private URLs, UUIDs and translation
text from attachments. See [support](../.github/SUPPORT.md) for help.
