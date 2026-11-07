# Hy-MT2 Q8_0 — L40S multilingual translation diagnostics

**Date:** 2026-11-07. **Modal profile:** `bsmith888`.
**Run:** https://modal.com/apps/bsmith888/main/ap-E1plbicNjAqkqO9u5yZAY2

## Purpose and evidence boundaries

This run extends the previously accepted single-sentence CUDA smoke into an
**opt-in synthetic diagnostic**, not an independently scored translation-quality
benchmark. The earlier P1/P2 CPU API remains mock-only; this diagnostic uses a
one-shot Modal App, never deploys a production translation endpoint and does not
modify PostgreSQL jobs.

The earlier fairy-tale benchmark archive was **not located in this Codespaces
workspace**. Therefore this run uses the new, clearly labeled synthetic fixture
`benchmarks/hy_mt2_diagnostic_v1.json`, **not** the prior verified benchmark.

## Reproducibility

- Model: `hy_mt2_30b`, official `Hy-MT2-30B-A3B-Q8_0.gguf`, **31,985,729,376 bytes**.
- SHA256 verified before execution:
  `d4e74d3b9479db5a7e2e4728879e15554b385e9549b411cc8b0ad03b2970ce98`.
- GGUF and model revisions: `models/hy_mt2_30b_q8_0.lock.json` (unchanged).
- Engine commit: `fd27b2034905f8dadd8bd6d2cc44595f4929d391`; CUDA/L40S image derived
  from the already verified smoke build.
- One NVIDIA L40S; one model server; one slot; context size 4096; batch/ubatch
  256/128; 99 GPU layers; CUDA compute 8.9; max GPU Function instances 1.
- Hy-MT2 official one-user-message translation instruction, no system message:
  translate into the target language; output **only** the translation.
- Sampling: temperature 0.7, top-p 1, top-k -1, repeat penalty 1, seed 42.
- Output limits: 300 tokens for structured cases; 1100 for narrative cases.
- Runtime bounds: Function timeout 720s, internal GPU processing budget 590s,
  total completion token budget 14,000; concurrency 1.
- Fixture SHA256:
  `c58fefdde648a1d69e53fdecd111da2593fcb17c3108076b2fa76c58763cdc2a`.

Dataset: **16 cases**, comprising one structured test plus one story test in each
of the eight directions EN↔VI, DE↔VI, JA↔VI and KO↔VI. Narrative source length
is **617–969 Unicode characters**; these cases approach the 1,000-character API
input ceiling but do not uniformly reach it. Structured cases test technical
placeholders, identifiers and HTML-like markup. There are no qualified,
human-reviewed target-language reference translations in this dataset.

## Observed L40S performance

| Metric | Observed result |
|---|---:|
| Requests with non-empty output | **16/16** |
| Failed requests or token-cap completion | **0** |
| Automated literal / markup / paragraph warnings | **0** |
| Model launch → server ready (inside GPU Function) | **17.246 s** |
| GPU Function runtime (internal) | **47.488 s** |
| Modal `.remote()` call wall time from Codespaces | **52.271 s** |
| Structured case latency, mean / range | **0.653 s** / 0.462–0.787 s |
| Narrative case latency, mean / range | **3.127 s** / 1.811–4.394 s |
| Total generated output tokens | **3,944** |
| Completion tokens / request elapsed time, aggregate | **~130.41 tokens/s** |
| Highest sampled GPU VRAM | **31,189 MiB** |
| GPU memory samples / sampling errors | **211 / 0** |
| GPU Function stopped and Modal App completed | **Yes** |

Notes: warm request latencies are sequential inference requests made **after the
model became ready**. `.remote()` time includes the request to Modal and GPU
container scheduling but does **not** represent client→production HTTP gateway
latency. Sampling is approximately every 200 ms: 31,189 MiB is **not the exact
instantaneous peak**, nor a worst-case bound at 1,000 characters. This is only
one cold invocation, not a multi-trial latency or scale-to-zero study.

At the previously observed **USD 1.95 per GPU-hour**, 47.488 seconds corresponds
to **approximately USD 0.0257 in GPU compute only**. This is **not** a verified
Modal invoice; other CPU, storage or platform charges may apply.

## Preliminary semantic inspection — failures despite zero automated warnings

The literal / markup checks caught **zero** issues, but a targeted comparison of
source and output identified a repeated **material substitution** in the shared
Vietnamese narrative. The source contains `chiếc la bàn bạc` (*silver compass*).

| Direction | Actual model phrase | Meaning | Finding |
|---|---|---|---|
| VI→EN | `brass compass` | Brass compass | Wrong material |
| VI→DE | `Kupferkompass` | Copper compass | Wrong material |
| VI→JA | `銅製の羅針盤` | Copper compass | Wrong material |
| VI→KO | `구리 나침반` | Copper compass | Wrong material |

All four translations of **this one shared narrative** have the same conceptual
error. This is **not** a statistically valid failure rate across independent
sentences or the overall language pairs.

Other examples: Latin-script name `Lâm` was changed to `Lin` in VI→EN and VI→DE;
VI→EN introduced the unsupported gender `little girl` for `một em bé`.
Some translations paraphrase `khăn đỏ` as scarf/handkerchief, which needs
contextual human review rather than an automatic judgment. Japanese/Korean
fluency and proper-name transliteration have **not** been professionally
reviewed.

**Important:** the EN→VI and DE→VI narrative fixtures were sentence-trimmed to
remain below the 1,000-character input cap. Those outputs end with the source
text and **must not** be flagged as omissions of sentences that were never sent.

Reference materials:
- [Full actual model outputs](../reports/p3_hy_mt2_quality_diagnostic_v1.json)
- [Per-request CSV](../reports/p3_hy_mt2_quality_diagnostic_v1.csv)
- [Automatically generated execution summary](../reports/p3_hy_mt2_quality_diagnostic_v1.md)
- [Preliminary review annotations](../reports/p3_hy_mt2_quality_review_v1.json)

## Evaluation decision and remaining gates

**Decision: NOT PRODUCTION READY.** Translation completion is operationally
functional on one L40S, but **semantic fidelity is not yet acceptable by
default** for high-accuracy applications. No BLEU/COMET/chrF score is claimed.
Zero mechanical warnings is not a semantic-quality pass.

Next evaluation should use a properly versioned parallel/reference corpus and
native-language reviewers; include named entities, negation, numbers, format,
terminology and a full 1,000-character sample for **every** language direction.
Test glossary/terminology instructions separately from the frozen default
prompt, evaluate multiple seeds, and repeat cold/warm + idle scale-to-zero.
Then apply the **same fixed suite** to Index-Translate and the other candidates.
Keep model registry disabled for production real inference until all gates pass.

## Re-running with explicit cost control

```bash
# CPU-only: validates the fixture; does not allocate an L40S
.venv/bin/modal run --profile bsmith888 scripts/modal_hy_mt2_quality_benchmark.py

# Paid one-shot L40S run, bounded to at most sixteen requests
.venv/bin/modal run --profile bsmith888 scripts/modal_hy_mt2_quality_benchmark.py --run

# Optional paid short diagnostic; still starts model once
.venv/bin/modal run --profile bsmith888 scripts/modal_hy_mt2_quality_benchmark.py --run --max-cases 2
```

Do not repeat the GPU run merely to regenerate reports. No Volume recreation,
weight redownload, API redeploy or PostgreSQL change was needed for this result.
