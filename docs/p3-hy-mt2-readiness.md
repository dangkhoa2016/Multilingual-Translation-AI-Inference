# P3 — Hy-MT2 30B-A3B Q8_0: source pinning and readiness

**Checked:** 2026-11-07 (Codespaces, CPU/network only). **Status: PRE-FLIGHT PASSED; GPU NOT VERIFIED.**

This is a reproducible, metadata-only prerequisite to GPU trials. It must not be
interpreted as a working translation engine or evidence of model quality.

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
  **CUDA compilation and GGUF model loading have NOT been tested.**

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
checkout**. When the GPU stage is approved, use a separately scoped, one-time
download into a Modal Volume with streamed SHA256 validation, and mount that
Volume only for the model worker. Do not put credentials into the manifest.

Proposed first translation smoke: text-only, context 4096 tokens, 1 concurrent
request, max output 128 tokens, one L40S, `min_containers=0`,
`buffer_containers=0`, `max_containers=1`. Load the model once from a
verified Volume, not from HF on every API request. Do not register workers,
enable GPU or allocate Model Volume until the checks below pass.

At the checked public Modal price of **USD 0.000542/GPU-second**, a 300-second
GPU allocation would be ~USD 0.163 for GPU time alone. Additional CPU,
memory, volumes, networking, idle/cold-start time and account pricing
are separate. L40S scheduling/account quota has **not** been proven.

## 4. Release gates — MUST remain false

- [x] Exact source/GGUF revisions, size, license metadata and metadata SHA256 pinned.
- [x] GGUF magic/version/architecture/counts verified by bounded range.
- [x] llama.cpp source tree contains a `hy_v3` model loader at a pinned SHA.
- [x] CPU-only compile + `llama-server --version` on Codespaces.
- [ ] Compile and execute pinned llama-server binary in the intended CUDA image.
- [ ] Download full GGUF once, verify **locally computed** SHA256 against lock.
- [ ] Verify actual tensor loading, text-generation/chat template, and EOS handling.
- [ ] Measure L40S peak VRAM, cold/warm latency and 1000-character translation quality.
- [ ] Confirm available L40S quota/region/budget in workspace `bsmith888`.
- [ ] Keep real-inference enable flags disabled until after full smoke review.

Even with source/header metadata checks, **no model has translated text** in this
project. The currently deployed CPU functions produce only
`is_mock_result=true` output and must remain unchanged for now.

Primary sources:
- https://huggingface.co/tencent/Hy-MT2-30B-A3B
- https://huggingface.co/tencent/Hy-MT2-30B-A3B-GGUF
- https://github.com/ggml-org/llama.cpp/pull/25395
- https://github.com/ggml-org/llama.cpp/issues/25657
- https://modal.com/pricing
