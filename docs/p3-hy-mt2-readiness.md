# P3 — Hy-MT2 30B-A3B Q8_0: source pinning and readiness

**Checked:** 2026-11-07 (Codespaces, Modal CPU and Modal L40S).
**Status: integrity, CUDA build, and single-sentence GPU smoke PASSED;
production readiness NOT established.**

This records metadata, full-file SHA256 and a successful single-sentence
L40S smoke. It is not evidence of broad translation quality or production readiness.

## 1. Locked public artifacts

| Item | Exact reference |
|---|---|
| Original checkpoint | `tencent/Hy-MT2-30B-A3B` |
| Original revision | `d3ead4dba61c09aac60a261a96ad1df3e705febb` |
| GGUF repository | `tencent/Hy-MT2-30B-A3B-GGUF` (official) |
| GGUF revision | `fd3dcbb6b31e9e03923ef4f9f42500f74c3851c3` |
| GGUF filename | `Hy-MT2-30B-A3B-Q8_0.gguf` |
| Quant | Q8_0 |
| GGUF bytes | 31,985,729,376 (~29.79 GiB) |
| GGUF SHA256 (HF LFS/Xet metadata) | `d4e74d3b9479db5a7e2e4728879e15554b385e9549b411cc8b0ad03b2970ce98` |
| Model architecture | `hy_v3` |
| License displayed by both repository cards | Apache-2.0 |
| llama.cpp upstream commit | `fd27b2034905f8dadd8bd6d2cc44595f4929d391` |
| llama.cpp architecture file | `src/models/hy-v3.cpp` |
| Architecture file SHA256 | `c173397670ff141b4a83424cf7d05f8b08f585b4a7a3fa3da36cc40f6b7a8814` |

Machine-readable lock: [`models/hy_mt2_30b_q8_0.lock.json`](../models/hy_mt2_30b_q8_0.lock.json).

Also pinned and SHA256-checked the small source `config.json`, `chat_template.jinja`,
and `LICENSE.txt`; hashes are in the JSON lock.

### Verification evidence

- Both exact immutable Hugging Face revisions returned HTTP 200 and Apache-2.0 license metadata.
- Official GGUF metadata exposes the declared size and LFS SHA256.
- HTTP HEAD on the **pinned** GGUF returned matching `x-linked-etag` and `x-linked-size`.
- An HTTP **206 Partial Content** response returned the first **8 KiB only**, not
  the entire 32 GB file. Parsed GGUF v3 header: architecture `hy_v3`,
  766 tensor entries, 37 metadata records.
- A separate bounded **8 MiB** range inspection found `general.file_type=7`,
  matching `LLAMA_FTYPE_MOSTLY_Q8_0=7` in the pinned llama.cpp `include/llama.h`.
  This still does not verify the full tensor body.
- Pinned llama.cpp tree contains `llama_model_hy_v3::load_arch_tensors`.
  The architecture was merged upstream in
  [PR #25395](https://github.com/ggml-org/llama.cpp/pull/25395) on 2026-07-13.
  Early implementations had tensor-name compatibility issues
  ([issue #25657](https://github.com/ggml-org/llama.cpp/issues/25657)).
  **Static source presence does not guarantee this GGUF loads.**
- **CPU-only source build PASSED** on Codespaces: the pinned tarball built
  `llama-server` and `--version` returned `0.9.0-dev (build 0, commit unknown)`.
  The version string has no Git SHA because the source was downloaded as a
  GitHub tarball rather than cloned with `.git`; provenance is the pinned
  archive URL + verified `hy-v3.cpp` SHA256, not that version string.
  Re-running with prebuilt Web UI downloads disabled also passed.
  The later CUDA build and GGUF load passed; see section 6.

## 2. Read-only reproducible verification

```bash
# Uses public metadata and a tiny bounded GGUF byte-range only:
.venv/bin/python scripts/verify_hy_mt2_p3.py --online
# Optional deeper header verification: reads at most 8 MiB, still NOT full weights.
.venv/bin/python scripts/verify_hy_mt2_p3.py --online --deep-header

# Verify a GGUF downloaded separately. This streams the ENTIRE local file
# once to calculate its actual SHA256; it does not invoke a GPU:
.venv/bin/python scripts/verify_hy_mt2_p3.py \
  --local-gguf /path/to/Hy-MT2-30B-A3B-Q8_0.gguf
```

The script fails closed if revisions, license metadata, source small-file hashes,
remote blob SHA256/size, header fields or pinned llama.cpp source differ.
It **never** downloads full model weights itself.

### CPU-only llama.cpp source/build check (no model weights)

For an optional manual CPU-only compilation preflight of the exact locked
llama.cpp source on a development machine with CMake and C++ compiler:

```bash
bash scripts/build_hy_mt2_llama_cpu_preflight.sh
```

This downloads only upstream source code, verifies the pinned `hy-v3.cpp` source
hash, compiles `llama-server` with `GGML_CUDA=OFF`, and prints its version.
It may consume significant local CPU time. Successful compilation does **not**
mean a GGUF is loadable or usable on NVIDIA L40S.

## 3. Memory estimate and risk on one L40S

Modal advertises L40S with **48 GB memory**. The GGUF file occupies ~32.0 GB
on disk, leaving **roughly 16 GB nominal difference** before considering
GGUF load representation, CUDA buffers, activations, MoE routing, KV cache,
context and runtime overhead. This is **not a measured VRAM budget**.

At verification time, the Codespaces repository filesystem had far less
free space than the 31.99 GB model. **Never download GGUF weights into the Git
checkout**. A separately scoped, one-time CPU download into a Modal Volume has now been
completed and SHA256-verified. The GPU worker will mount the Volume only
for the controlled smoke test. Do not put credentials into the manifest.

Proposed first translation smoke: text-only, context 4096 tokens, 1 concurrent
request, max output 128 tokens, one L40S, `min_containers=0`,
`buffer_containers=0`, `max_containers=1`. Load the model once from a
verified Volume, not from HF on every API request. Keep the production
CPU gateway unchanged and register no permanent GPU inference workers until
the extended-input and quality gates are reviewed.

At the checked public Modal price of **USD 0.000542/GPU-second**, a 300-second
GPU allocation would be ~USD 0.163 for GPU time alone. Additional CPU,
memory, volumes, networking, idle/cold-start time and account pricing
are separate. A short L40S probe **successfully allocated** one GPU in
workspace `bsmith888`, but future availability is not guaranteed.

## 4. Verification gates — production readiness still false

- [x] Exact source/GGUF revisions, size, license metadata and metadata SHA256 pinned.
- [x] GGUF magic/version/architecture/counts verified by bounded range.
- [x] llama.cpp source tree contains a `hy_v3` model loader at a pinned SHA.
- [x] CPU-only compile + `llama-server --version` on Codespaces.
- [x] Compile pinned llama-server CUDA image and execute binary on an actual L40S.
- [x] Download full GGUF once into Modal Volume; compute entire SHA256 and match lock.
- [x] Load full GGUF and produce an EN→VI translation through llama-server.
- [ ] Evaluate tokenizer/EOS behavior across varied prompts and boundary cases.
- [ ] Measure L40S peak VRAM, cold/warm latency and 1000-character translation quality.
- [ ] Independently verify ongoing quota, region availability and monthly budget in workspace `bsmith888`.
- [ ] Keep real-inference enable flags disabled until after full smoke review.

A one-sentence **real translation** has now succeeded using the temporary GPU
smoke application. This does **not** enable the production translation API:
the currently deployed CPU gateway and worker still produce only
`is_mock_result=true` output and must remain unchanged for now.

Primary sources:
- https://huggingface.co/tencent/Hy-MT2-30B-A3B
- https://huggingface.co/tencent/Hy-MT2-30B-A3B-GGUF
- https://github.com/ggml-org/llama.cpp/pull/25395
- https://github.com/ggml-org/llama.cpp/issues/25657
- https://modal.com/pricing


## 5. P3 Volume staging, 2026-11-07

Hy-MT2 GGUF was downloaded by a **Modal CPU-only Function** into the named
Volume `translation-ai-inference-hy-mt2-30b-a3b-gguf-weights`.
It was NOT downloaded to Codespaces and NO GPU was used for the transfer.

- Exact size: **31,985,729,376 bytes**.
- Full-file SHA256 computed on the actual downloaded file:
  `d4e74d3b9479db5a7e2e4728879e15554b385e9549b411cc8b0ad03b2970ce98`.
- Result: **MATCH** with pinned official metadata; commit to Modal Volume succeeded.
- CPU transfer: **83.53 seconds**, download + SHA256 + Volume commit:
  **112.63 seconds**.
- Run: https://modal.com/apps/bsmith888/main/ap-MKJy24KYePNqS0Sr3j7YzG
- Files: official GGUF, `hy_mt2_q8_0_verified.json`, small Hugging Face cache metadata.
- Script: `scripts/modal_hy_mt2_stage_weights.py` (safe to rerun, verifies before reuse).

This satisfies full-file integrity; CUDA/GPU loading subsequently passed in section 6.
Volume storage remains billable until the artifact is removed. No extra
GPU worker or API endpoint was deployed by this step.


## 6. CUDA image and real L40S smoke succeeded

Pinned CUDA image `im-OWf7a9328NJoqBcqox4lo1` built all 332 CMake/Ninja
steps after applying the CUDA-driver-at-link workaround. The structural CPU
build check passed and the L40S runtime executed `llama-server --version`
with commit `fd27b2034`.

On 2026-11-07, the temporary GPU Function loaded the verified 31.99 GB GGUF
and completed a real English → Vietnamese OpenAI-compatible chat completion:

> Input: The little fox crossed the bridge at sunrise.

> Hy-MT2 output: Chú cáo nhỏ đã băng qua cây cầu vào lúc bình minh.

- Modal run: https://modal.com/apps/bsmith888/main/ap-USXThCPld9Q3wcuULmEC8c
- Within-function model load-to-ready: **21.21 s**.
- Within-function start-to-completion: **21.583 s**.
- Observed GPU memory: **31,167 MiB**; samples are NOT guaranteed peak VRAM.
- Prompt/completion tokens: **45 / 22**, total **67**.
- Full SHA256 was checked on CPU before the GPU run; persisted Volume marker
  is verified on GPU.
- The temporary Modal app stopped after the smoke; the public CPU API remains
  mock-only.

See [L40S smoke details](p3-hy-mt2-l40s-smoke.md) and
[smoke report](../reports/p3_hy_mt2_l40s_smoke.json).

Remaining blockers: 1,000-character and multi-language benchmark, reproducible
quality scoring / human review, accurate GPU peak measurement and production
budget/error handling. No permanent GPU worker has been deployed.
