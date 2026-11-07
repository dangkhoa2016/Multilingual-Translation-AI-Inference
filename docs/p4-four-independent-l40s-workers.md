# P4 — Four independent Modal L40S workers

Date: 2026-11-07

## Objective and boundaries

Run four separate Q8_0 translation models on **four independent NVIDIA L40S
GPU containers** within one source repository and one eventual Modal deployment.
Each worker has a separate weight Volume, function name, cold-start lifecycle
and `min_containers=0`. One warm GPU may serve only its own model.

**This is infrastructure/load validation, not a translation quality assessment.**
Production CPU PostgreSQL/gateway remains mock-only until real worker
integration passes its own security/recovery gates.

## Verified hardware concurrency

A live Modal run successfully allocated **four distinct L40S GPUs at once**
on the authenticated Modal workspace:

- Recorded output: [capacity JSON](../reports/p4_four_l40s_capacity_probe_v1.json)
- Four different GPU UUIDs, each NVIDIA L40S, >= 46,000 MiB VRAM.
- Observed four overlapping GPU reservations, not four sequential calls.
- Four independent Modal functions; each `max_containers=1`, `min_containers=0`,
  `buffer_containers=0`, `scaledown_window=5`.
- The test App stopped after results. This verifies actual scheduling capacity
  during that run, **not a guarantee of ongoing quota or availability**.
- GPU capacity test did **not** load any translation model.

Reproduction (GPU charge only with explicit `--run`):

```bash
modal run --profile YOUR_MODAL_PROFILE scripts/modal_four_l40s_capacity_probe.py
modal run --profile YOUR_MODAL_PROFILE scripts/modal_four_l40s_capacity_probe.py --run
```

## Frozen Q8_0 files

All four file names, revisions, sizes and publisher LFS SHA256 hashes were
verified against pinned Hugging Face metadata. **Each actual full GGUF was
subsequently downloaded to its dedicated Modal Volume, hashed locally in full,
and smoke-tested on one L40S**. The source manifests and raw run results
record the distinction between publisher metadata and full local verification.

| Key | Official/selected GGUF repo | Q8_0 file bytes | Full CPU SHA256 and L40S model load |
|---|---|---:|---|
| `hy_mt2_30b` | `tencent/Hy-MT2-30B-A3B-GGUF` | 31,985,729,376 | Full SHA256 + L40S inference PASS |
| `index_35b` | `IndexTeam/Index-Translate-35B-A3B-preview-GGUF` | 37,802,148,992 | Full SHA256 + L40S inference PASS |
| `gemma4_31b_it` | `unsloth/gemma-4-31B-it-GGUF` | 32,635,677,632 | Full SHA256 + L40S inference PASS |
| `qwen35_35b` | `unsloth/Qwen3.5-35B-A3B-GGUF` | 36,903,139,968 | Full SHA256 + L40S inference PASS |

Pinned metadata including every SHA256:
[`models/four_l40s_workers_q8_0_manifest.json`](../models/four_l40s_workers_q8_0_manifest.json).

Validating metadata without GPUs or weight downloads:

```bash
PYTHONPATH=src python scripts/verify_four_l40s_models.py
PYTHONPATH=src python scripts/verify_four_l40s_models.py --online
```

**Memory safety:** The weight files add up to ~129.758 GiB of disk space,
spread across **four separate Volumes**. This is not the memory consumption of
a single GPU. Q8_0 alone can occupy ~32–38 GB per L40S, but KV cache,
runtime buffers, context size and model-specific code affect actual VRAM.
All four passed one-sentence CUDA load tests with sampled VRAM between
31,151 and 35,336 MiB. This does **not** prove fitness for every context
length, batch size or production workload.

## Volume naming correction

The original explicit Index Volume ID exceeded Modal's **63-character**
maximum: `translation-ai-inference-index-translate-35b-a3b-preview-gguf-weights`
was 69 characters and was rejected by the real Modal CLI.

Before any Index Volume existed, the ID was corrected consistently to
`translation-ai-inference-index-35b-a3b-preview-gguf-weights` (59 characters).
Hy-MT2's existing Volume name was not changed.

## Weight staging (CPU only)

Three additional model-named Volumes were created and populated.
**All four GGUFs passed independent complete-file SHA256 verification**.
The CPU-only staging command is **explicitly opted in**, one model at a time:

```bash
modal run --profile YOUR_MODAL_PROFILE scripts/modal_stage_remaining_weights.py
modal run --profile YOUR_MODAL_PROFILE scripts/modal_stage_remaining_weights.py --model index_35b --stage
modal run --profile YOUR_MODAL_PROFILE scripts/modal_stage_remaining_weights.py --model gemma4_31b_it --stage
modal run --profile YOUR_MODAL_PROFILE scripts/modal_stage_remaining_weights.py --model qwen35_35b --stage
```

A marker `verified_gguf_q8_0.json` is committed **only after the complete
downloaded file passes pinned byte size and independently computed SHA256**.
No GGUF weights are stored in Git or in Codespaces.

At the previously quoted Modal storage rate of ~$0.09/GiB/month, all four
files at 129.758 GiB would cost roughly **$11.68/month of weight storage**,
if the same rate still applies; **~$9/month would be additional storage**
over the existing Hy-MT2 file. Actual provider billing can differ.
Four simultaneously running L40S GPUs at the earlier published $1.95/GPU-hour
would cost ~$7.80/hour of GPU compute only; scale-to-zero removes idle GPU
compute but does **not** remove persistent Volume storage charges.

## Load one model on exactly one L40S

```bash
modal run --profile YOUR_MODAL_PROFILE scripts/modal_four_model_gpu_smoke.py
modal run --profile YOUR_MODAL_PROFILE scripts/modal_four_model_gpu_smoke.py --model hy_mt2_30b --smoke
modal run --profile YOUR_MODAL_PROFILE scripts/modal_four_model_gpu_smoke.py --model index_35b --smoke
modal run --profile YOUR_MODAL_PROFILE scripts/modal_four_model_gpu_smoke.py --model gemma4_31b_it --smoke
modal run --profile YOUR_MODAL_PROFILE scripts/modal_four_model_gpu_smoke.py --model qwen35_35b --smoke
```

The four separate GPU functions share the pinned Hy-MT2 CUDA `llama.cpp`
image at revision `fd27b2034905f8dadd8bd6d2cc44595f4929d391`.
The pinned engine was successfully exercised with **all four GGUF architectures**
in one-sentence L40S tests. Gemma 4 originally loaded but returned empty
final content with a 128-token default limit; enabling non-thinking chat
template behavior and using 512 output tokens with its recommended
sampling parameters resolved this one-sentence smoke. Do not infer robust
translation quality from this recovery.
The scripts **fail closed** if a dedicated SHA256 marker or byte count is
missing. They produce a single translated sentence only; this is not a full
benchmark. The test App shuts down after completion.

The opt-in `--all-models` mode has **successfully run all four actual GGUF
models concurrently** on four different NVIDIA L40S GPUs, with all four
nonempty translated responses. Use it only with four verified weight Volumes;
GPU charges apply.

```bash
modal run --profile YOUR_MODAL_PROFILE scripts/modal_four_model_gpu_smoke.py --all-models
```

### Four-model concurrent CUDA result

- Real run: https://modal.com/apps/bsmith888/main/ap-xLywKUBpPOz7NzMmlM4UeQ
- Evidence: [four-model runtime JSON](../reports/p4_four_l40s_models_runtime_smoke_v1.json)
- Result: **4/4 successful**, **4 unique NVIDIA GPU UUIDs**, **peak overlapping model executions = 4**.
- Hy-MT2: loaded in 20.604 s; sampled VRAM 31,151 MiB.
- Index-Translate: loaded in 24.774 s; sampled VRAM 35,335 MiB.
- Gemma 4: loaded in 16.266 s; sampled VRAM 32,973 MiB.
- Qwen3.5: loaded in 27.159 s; sampled VRAM 35,336 MiB.
- Each model translated: *The little fox crossed the bridge at sunrise.*
- These figures are **model-load-to-ready within ephemeral GPU functions**,
  not internet-facing HTTP cold-start latency and not precise VRAM peaks.
- Every model's GPU worker uses `min_containers=0`, `buffer_containers=0`,
  and `max_containers=1`. The test app stops after completion.
- No models or GGUF files were re-downloaded for the concurrent CUDA run.

## Production integration gate

The existing `modal_app.py` intentionally deploys only a CPU gateway and CPU
mock worker. The test scripts do not rewrite it, add unauthenticated HTTP
endpoints, issue PostgreSQL migrations, or silently switch the mock path.

To make all four real models available through the API:

1. **Completed:** all four GGUFs pass full-file SHA256 and one-sentence
   individual and concurrent L40S inference.
2. **Still needed:** benchmark 1,000-character contexts, repeatability,
   timeouts, shutdown and model-specific prompt behavior.
3. Register four real GPU classes/functions **inside the existing shared Modal
   App** with isolated load-once and idle scale-down. Do not deploy a second
   app with the same name and inadvertently remove the CPU gateway.
4. Route model-specific jobs from the authenticated CPU gateway, preserving
   PostgreSQL idempotency, durable results and reconciliation.
5. If direct per-model HTTP URLs are needed, use protected web endpoints;
   public unprotected GPU functions are prohibited.
6. **Completed:** a four-model simultaneous load/reservation test, not merely
   GPU identity scheduling; actual deployed API integration is still separate.

**Gate status:** **four physical L40S GPUs with four real GGUF model
loads and translated outputs VERIFIED in the same interval**. Production
job routing, load-once resident workers, long-input reliability and
public endpoint integration **NOT YET DEPLOYED**.
