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

These values come from the
[public GPU execution summary](../reports/four_gpu_parallel_inference.json). The implementation uses a verified `llama.cpp`
CUDA revision, model-specific decoding parameters, a 4,096-token
context and one inference stream per GPU container.

## Per-model inference options

Both `POST /v1/jobs/translations` and `POST /v1/jobs/benchmarks` accept an **optional**
`model_configs` object keyed by the *selected* API model key. Each model can receive a
different set of sampling overrides, and omitted fields retain its documented defaults.
There is no need to edit or rebuild the GPU worker for these per-request overrides.

```json
{
  "models": ["hy_mt2_30b", "qwen35_35b"],
  "source_language": "en",
  "target_language": "vi",
  "text": "The fox crossed the bridge.",
  "options": {"preserve_formatting": true},
  "model_configs": {
    "hy_mt2_30b": {"temperature": 0.2, "top_p": 0.9, "max_tokens": 1024},
    "qwen35_35b": {"temperature": 0.65, "top_k": 30, "seed": 1234}
  }
}
```

For one-model translation, use `model` instead of `models` and include only
that model in `model_configs`. Without the object (or with `{}`), existing
requests keep their original decoding defaults and idempotency hash.

**Available per-model fields:**

- Sampling: `temperature`, `top_p`, `top_k`, `min_p`, `typical_p`,
  `top_n_sigma`, `dynatemp_range`, `dynatemp_exponent`, `xtc_probability`,
  `xtc_threshold`, `mirostat`, `mirostat_tau`, `mirostat_eta`.
- Repetition: `repeat_penalty`, `repeat_last_n`, `frequency_penalty`,
  `presence_penalty`, `dry_multiplier`, `dry_base`, `dry_allowed_length`,
  `dry_penalty_last_n`.
- Output: `max_tokens` (1–3072, default 1536), `seed` (-1–4294967295),
  `stop` (1–8 nonempty strings, at most 100 characters each),
  `ignore_eos` (Boolean), `enable_thinking` (Boolean, optional).

The API rejects unknown names, non-finite numbers, invalid types, out-of-range
values and configs for unselected models with HTTP 422. Examples of bounds:
`temperature` 0–2, `top_p`/`min_p` 0–1, `top_k` -1–1000.
The code-defined model defaults remain in
`src/multilingual_translation_ai_inference/model_options.py` and are applied
only when an override was not supplied. The same submitted config is stored in
PostgreSQL and reused for any explicitly approved retry. A different config
under the same `Idempotency-Key` results in HTTP 409; use a fresh key for new work.

**Not request-overridable:** GGUF/revision, `ctx_size`, GPU layers,
batch/ubatch size, concurrency, llama-server process arguments, arbitrary
chat messages, `stream` and other server internals. These are engine/deployment
settings, not per-request decoding parameters. The 4,096-token server context
remains fixed for the deployed profile; the output budget does not guarantee
available context for every prompt. `enable_thinking=true` may cause a
reasoning-style response to be rejected by this translation-only pipeline.
GPU quality/cost for new custom profiles has not been benchmark-verified.

## Supported input contract

The gateway accepts arbitrary user-provided language codes or names (for
example `fr`, `zh-Hant`, `Arabic`) without a fixed whitelist; source and target
labels must differ under case-insensitive comparison (`en` and `EN` match,
but `en` and `English` are not resolved as aliases). Labels must be printable,
include a letter and contain 1–64 characters. A model may report `UNSUPPORTED_LANGUAGE_PAIR` or produce
inaccurate text without reporting failure; **acceptance is not quality proof**.
Input length is at most 1,000 Unicode code points (not UTF-8 bytes).

See [API reliability evidence](reliability.md) and
[model licensing](../MODEL_LICENSE.md). Changing model revision or
quantization invalidates the stored verification evidence until
the new artifact is independently tested.
