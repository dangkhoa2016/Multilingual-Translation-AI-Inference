# Model catalog and reproducible artifacts

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](models.vi.md)

The four translation backends are **distinct model families**, not four
replicas of the same weights. All use GGUF `Q8_0` quantization for a
single independently scaling **NVIDIA L40S 48 GB** GPU per model.

| API model key | Full model name | GGUF distributor | Weight size | Source license |
|---|---|---|---:|---|
| `hy_mt2_30b` | Tencent Hy-MT2-30B-A3B | Tencent | 31.99 GB | Apache-2.0 |
| `index_35b` | Index-Translate-35B-A3B-preview | IndexTeam | 37.80 GB | Apache-2.0 |
| `gemma4_31b_it` | Google Gemma 4 31B IT | Unsloth | 32.64 GB | Apache-2.0 |
| `qwen35_35b` | Qwen3.5-35B-A3B | Unsloth | 36.90 GB | Apache-2.0 |

**Source provenance:** the
[immutable model manifest](../models/four_l40s_workers_q8_0_manifest.json)
records checkpoint repository and revision, GGUF repository and revision,
exact filename and file size, SHA256, Volume, and verified runtime status.
The worker checks the local hash-verification marker and size before
loading the model; the GPU does not download weights.

## Observed real GPU compatibility

Each model successfully loaded its pinned Q8_0 artifact and produced
a nonempty English-to-Vietnamese response. Four separate L40S GPU UUIDs
were observed with overlapping execution windows.

| Model | Measured load-to-ready | Highest sampled VRAM |
|---|---:|---:|
| Tencent Hy-MT2 | 20.60 s | 31,151 MiB |
| Index-Translate | 24.77 s | 35,335 MiB |
| Gemma 4 IT | 16.27 s | 32,973 MiB |
| Qwen3.5 | 27.16 s | 35,336 MiB |

These values come from the specific
[four-model execution report](../reports/four_gpu_parallel_inference.json);
they are **not** guaranteed peaks, SLAs or a demonstration of
translation accuracy. The implementation uses a verified `llama.cpp`
CUDA revision, model-specific decoding parameters, a 4,096-token
context and one inference stream per GPU container.

## Supported input contract

The gateway accepts source/target language codes `en`, `vi`, `de`,
`ja`, and `ko`, with different source and target languages.
These are accepted directions, **not guaranteed translation quality**.
Input length is at most 1,000 Unicode code points (not UTF-8 bytes).

See [quality evaluation](benchmarking.md) and
[model licensing](../MODEL_LICENSE.md). Changing model revision or
quantization invalidates the stored verification evidence until
the new artifact is independently tested.
