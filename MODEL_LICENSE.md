# Third-party model licenses and attribution

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](MODEL_LICENSE.vi.md)

**The MIT license of this repository covers its original source code, not the
third-party model weights.** Every model listed below is owned and licensed by
its upstream author. This repository does not redistribute model weights.

All four original checkpoints and GGUF releases were checked at their **pinned
Hugging Face revisions**. Their model-card metadata declared **Apache-2.0**,
and the applicable text can be read in
[Apache License, Version 2.0](THIRD_PARTY_LICENSES/Apache-2.0.txt).
For hosted inference or redistribution, independently review the exact pinned
upstream model license, notices, trademarks, applicable law and any third-party
components before commercial use.

| Model deployed | Original checkpoint | GGUF distribution | Card license |
|---|---|---|---|
| Tencent Hy-MT2-30B-A3B | [Tencent original](https://huggingface.co/tencent/Hy-MT2-30B-A3B) | [Tencent GGUF](https://huggingface.co/tencent/Hy-MT2-30B-A3B-GGUF) | Apache-2.0 |
| Index-Translate-35B-A3B-preview | [IndexTeam original](https://huggingface.co/IndexTeam/Index-Translate-35B-A3B-preview) | [IndexTeam GGUF](https://huggingface.co/IndexTeam/Index-Translate-35B-A3B-preview-GGUF) | Apache-2.0 |
| Gemma 4 31B IT | [Google original](https://huggingface.co/google/gemma-4-31B-it) | [Unsloth GGUF](https://huggingface.co/unsloth/gemma-4-31B-it-GGUF) | Apache-2.0 |
| Qwen3.5-35B-A3B | [Qwen original](https://huggingface.co/Qwen/Qwen3.5-35B-A3B) | [Unsloth GGUF](https://huggingface.co/unsloth/Qwen3.5-35B-A3B-GGUF) | Apache-2.0 |

## Exact provenance

Immutable checkpoint and GGUF revisions, file sizes, SHA256 values, and
dedicated Modal Volume names are recorded in
[the model lock manifest](models/four_l40s_workers_q8_0_manifest.json).
Runtime validation checks the recorded SHA256 verification marker before
loading a GGUF. The manifest's metadata is a reproducibility record; it
does not replace a review of the upstream legal texts.

For Hy-MT2, Tencent includes an upstream `LICENSE.txt` in both the original
and GGUF repositories. Qwen's original repository also contains a license
file. Google's Gemma 4 license information is available via
[Google's official Gemma 4 Apache-2.0 page](https://ai.google.dev/gemma/apache_2).
For IndexTeam and Unsloth GGUF releases where a standalone license file was
not present in the pinned file listing, the corresponding pinned model-card
license declaration was used; do not misrepresent that as an independently
signed licensing grant.

## What this repository does *not* grant

- No ownership or relicense rights over upstream model weights.
- No permission to use the Tencent, IndexTeam, Google, Unsloth or Qwen trademarks.
- No claim that cloud provider terms, datasets or externally served data are MIT.
- No guarantee that licensing terms or legal requirements remain unchanged
  if you switch to a different checkpoint or artifact revision.

See [third-party notices](NOTICE.md), [model selection](docs/models.md),
and [source LICENSE](LICENSE). This summary is informational, not legal advice.
