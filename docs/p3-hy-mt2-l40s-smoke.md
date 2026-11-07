# P3 Hy-MT2 Q8_0 — Controlled L40S smoke test

**Date:** 2026-11-07. **Workspace:** `bsmith888`.
**Target:** verify actual GPU load and translate one English sentence into Vietnamese.

The P2 public CPU gateway and mock worker are unchanged. This test uses
a temporary Modal application; **no permanent GPU endpoint** is created.

## Locked inputs

- Source checkpoint: `tencent/Hy-MT2-30B-A3B`, revision
  `d3ead4dba61c09aac60a261a96ad1df3e705febb`.
- Official GGUF: `Hy-MT2-30B-A3B-Q8_0.gguf`, revision
  `fd3dcbb6b31e9e03923ef4f9f42500f74c3851c3`.
- Full weights size: 31,985,729,376 bytes.
- SHA256 computed on actual file and matched:
  `d4e74d3b9479db5a7e2e4728879e15554b385e9549b411cc8b0ad03b2970ce98`.
- Stored in Modal Volume `translation-ai-inference-hy-mt2-30b-a3b-gguf-weights`.
- llama.cpp source revision `fd27b2034905f8dadd8bd6d2cc44595f4929d391`.
- CUDA build: `nvidia/cuda:12.8.1-devel-ubuntu22.04`, `GGML_CUDA=ON`,
  `CMAKE_CUDA_ARCHITECTURES=89`, source pinned by SHA.
- GPU: one NVIDIA L40S, `max_containers=1`, `min_containers=0`.

## Actual GPU probe (completed)

A short Modal L40S probe confirmed:
- Driver: 610.57.04
- Compute capability: 8.9
- VRAM: 46,068 MiB total; 45,484 MiB free at probe time.
- Run: https://modal.com/apps/bsmith888/main/ap-o4elOqrfp1XIuzmsFS39YM

Pricing queried from this workspace: L40S USD 1.95/hour;
Volume USD 0.09/GiB-month. These are unit rates, not an incurred-cost invoice.

## Source staging (completed)

Weights were downloaded by a CPU-only Modal Function into the single named Volume.
The entire downloaded file was hashed and matched the official LFS metadata,
then committed with `hy_mt2_q8_0_verified.json`.

- Download duration: 83.53 seconds.
- Total stage + full hash + commit: 112.63 seconds.
- Run: https://modal.com/apps/bsmith888/main/ap-MKJy24KYePNqS0Sr3j7YzG

## CUDA image linking issue and correction

The first CUDA Image Builder compiled `libggml-cuda.so`, but the final
`llama-server` executable failed to link:

`libcuda.so.1, needed by libggml-cuda.so, not found`,
followed by unresolved `cuMemCreate` and related CUDA Driver API references.

The CUDA driver is provided by NVIDIA on the GPU runtime, **not** as the real
driver during the image build. The pinned build was modified to set
`CMAKE_EXE_LINKER_FLAGS=-Wl,--allow-shlib-undefined`, matching llama.cpp
container build practice without injecting a stub driver into the runtime.

The failed first build did not load weights or allocate a GPU.

Related: https://github.com/ggml-org/llama.cpp/issues/23357

## Execution

```bash
# Source/metadata verification (no GPU or model transfer):
.venv/bin/python scripts/verify_hy_mt2_p3.py --online --deep-header

# Build and inspect CUDA binary structurally on Modal CPU only:
.venv/bin/modal run --profile bsmith888 scripts/modal_hy_mt2_gpu_smoke.py

# Explicit, single L40S run. Requires preverified weights:
.venv/bin/modal run --profile bsmith888 scripts/modal_hy_mt2_gpu_smoke.py --smoke
```

GPU smoke parameters:
- Context 4096 tokens, one slot, batch 256, ubatch 128, GPU layers 99.
- One short English→Vietnamese input, 128 output tokens max.
- Prompt and decoding follow Hy-MT2 guidance: temperature 0.7,
  top_p 1, top_k -1, repeat penalty 1.
- Expected metadata: load-to-ready latency, end-to-end latency, observed
  GPU memory (sampled, **not exact peak**), usage token counts and output.
- A GPU Function timeout of 720 seconds is configured. The script terminates
  the local model server and the ephemeral application scales down.
- Positive smoke only proves one sentence was served. It is **not** a
  1000-character benchmark, human quality review, or production approval.

Actual CUDA and translation results belong in `reports/p3_hy_mt2_l40s_smoke.json`.
Do not set `ready_for_real_inference=true` until the remaining gates pass.


## Completed CUDA image and GPU smoke: 2026-11-07

- First image build failed only at final linker due missing build-time
  `libcuda.so.1`; source, GGUF and model data were not involved.
- Fixed with `-Wl,--allow-shlib-undefined`. Full CUDA build passed
  **332/332** steps; image ID: `im-OWf7a9328NJoqBcqox4lo1`.
- CPU structural check passed:
  https://modal.com/apps/bsmith888/main/ap-1JzXJZuaREWCpFkotTxsoD
- L40S runtime successfully executed pinned CUDA `llama-server`:
  version `0.9.0-dev (build 12182, commit fd27b2034)`.
- Actual 31.99 GB GGUF was loaded, health endpoint became ready and
  OpenAI-compatible /v1/chat/completions returned one EN→VI translation.
- **Input:** The little fox crossed the bridge at sunrise.
- **Output:** Chú cáo nhỏ đã băng qua cây cầu vào lúc bình minh.
- Within-function load-to-ready **21.21 seconds**, total **21.583 seconds**.
- Observed memory used **31,167 MiB**, **not** exact peak.
- Prompt **45 tokens**, completion **22 tokens**, total **67 tokens**.
- GPU function terminated successfully, not deployed as long-running server.
- Run: https://modal.com/apps/bsmith888/main/ap-USXThCPld9Q3wcuULmEC8c
- Result JSON: [P3 L40S smoke report](../reports/p3_hy_mt2_l40s_smoke.json).

**Limitations:** One sentence establishes functional compatibility, not
translation accuracy across domains or 1,000-character inputs. The 21.583s
metric is measured inside the function and excludes Modal scheduling and
container provisioning. GPU memory is sampled via nvidia-smi rather than an
externally measured true peak. No claim of production readiness is made.
