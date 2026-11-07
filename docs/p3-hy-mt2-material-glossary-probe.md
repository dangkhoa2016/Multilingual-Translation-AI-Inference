# P3 — Hy-MT2 material terminology and glossary diagnostic on L40S

**Date:** 2026-11-07
**Modal workspace:** `bsmith888`
**Paid ephemeral run:** https://modal.com/apps/bsmith888/main/ap-pLsJxw986vGNZwT48heILc
**Status:** 40/40 requests completed; no production deployment.

## Research question

The prior 16-case multilingual diagnostic revealed a potentially serious flaw:
Vietnamese `chiếc la bàn bạc` (*silver compass*) became brass or copper in
translations into four target languages. Does a focused, **explicitly supplied
glossary** improve fidelity without altering the model or the CUDA runtime?

This is a **development probe**, not a certified translation-quality benchmark
and not an independent experiment with qualified human reference translations.

## Frozen setup

- Same **official Hy-MT2-30B-A3B Q8_0** weights and Modal Volume as the accepted
  CUDA smoke. Full weights already verified in the immutable model lock.
- SHA256: `d4e74d3b9479db5a7e2e4728879e15554b385e9549b411cc8b0ad03b2970ce98`.
- Pinned `llama.cpp` commit:
  `fd27b2034905f8dadd8bd6d2cc44595f4929d391`.
- NVIDIA L40S × 1; no always-on worker. GPU maximum containers: 1.
- Model server context 4096 tokens, batch/ubatch 256/128, one request at a time.
- Decoding: temperature 0.7, top-p 1, top-k -1, repetition penalty 1, seed 42.
- Baseline prompt: same translation-only user instruction used in the earlier
  Hy-MT2 diagnostic.
- Glossary prompt: identical translation instruction followed by the explicit
  terms `bạc = silver`, `đồng = copper`, `vàng = gold` plus instructions
  to preserve material distinctions, negations, identifiers and the Latin-script
  personal name `Lâm`.
- Dataset: five Vietnamese texts (one previous narrative and four new material
  probes) × four target languages (EN/DE/JA/KO) × two prompt variants = **40
  requests**. Variant order alternates by case to reduce, not eliminate, run-order bias.
- Source text ≤ 1,000 Python Unicode characters.
- Corpus SHA256:
  `63c03fd52780863ed946dee7bfbdd65235740c759fc5cbfdd6dccbdbd5cb2a10`.
- Source fixture:
  [`hy_mt2_material_glossary_probe_v1.json`](../benchmarks/hy_mt2_material_glossary_probe_v1.json).
- Hard limits: GPU Function timeout 650 seconds, internal budget 500 seconds,
  combined output budget 9,000 tokens, no parallel GPU replicas.

## Measured results

| Metric | Observed |
|---|---:|
| Completed requests | **40/40** |
| Failed requests | **0** |
| Generated tokens total | **4,850** |
| Model server start-to-ready (internal) | **34.746 s** |
| GPU Function execution duration (internal) | **74.203 s** |
| Modal `.remote()` wall time from Codespaces | **82.318 s** |
| Highest observed GPU memory | **31,191 MiB** |
| Stop reason | None |
| Estimated GPU-only compute at previously observed $1.95/GPU-hour | **~$0.0402** |

The memory value is **not a precisely instrumented instantaneous peak**, because
this run sampled `nvidia-smi` after each request. GPU compute estimate is not an
invoice and excludes CPU/storage/platform fees. The `.remote()` figure includes
the Modal scheduling/startup portion but is **not** client-to-production-HTTP
latency. Only one cold model initialization was observed.

## Material correctness: preliminary comparison

| Evidence subset | Baseline | With glossary |
|---|---:|---:|
| Correct *silver-compass* material in previously seen narrative, 4 directions | **0/4** | **4/4** |
| Expected material **lexical hints** in 4 new short sources × 4 languages | 34/36 | 36/36 |
| Literal preservation of Latin-script name `Lâm` in EN and DE outputs | 1/8 | 8/8 |

The 34/36 and 36/36 counts are **lexical-presence indicators, not semantic
accuracy percentages**: several source sentences explicitly say *not copper*
or *not gold*, so a target sentence can contain every material term and still
reverse the relationship. The script's Korean material detection was corrected
offline to avoid the ordinary particle `은` being mistaken for the material
silver; Japanese detection was also refined. All **original text outputs,
request times and GPU measurements were preserved without running GPU again**.

### Observed examples

**Previously seen narrative, silver compass:**

| Direction | Baseline | Glossary |
|---|---|---|
| VI→EN | `brass compass` | `silver compass` |
| VI→DE | `Kupferkompass` (copper) | `silberne Kompassgerät` (silver) |
| VI→JA | `銅製の羅針盤` (copper) | `銀製の羅針盤` (silver) |
| VI→KO | `구리 나침반` (copper) | `은으로 만든 나침반` (silver) |

**New short source, copper box beside a silver key:**

- EN baseline used `bronze box`; glossary used `copper box`.
- DE baseline used `bronzene Schachtel`; glossary used `kupferne Schatulle`.
- The Japanese/Korean versions used copper appropriately in this source under
  both prompts.

**Critical VI→DE instruction reversal:**

- Vietnamese source: `không thay bạc bằng đồng khi sản xuất`
  (*do not replace silver with copper during production*).
- Baseline: `wurde kein Kupfer durch Silber ersetzt`
  (*no copper was replaced by silver*). This **reverses the direction** and
  changes an instruction into a past-tense assertion.
- Glossary: `darf Silber nicht durch Kupfer ersetzt werden`
  (*silver must not be replaced by copper*). Correct relation for this case.

**Caveat:** Some non-target problems remain. VI→EN still uses `a little girl`
for gender-unspecified `một em bé`, with and without glossary. These are reasons
not to claim general translation perfection.

## Repeatability and compliance

- CPU-only validation (does not allocate GPU):
  `modal run --profile bsmith888 scripts/modal_hy_mt2_material_glossary_probe.py`.
- Opt-in bounded paid run:
  `modal run --profile bsmith888 scripts/modal_hy_mt2_material_glossary_probe.py --run`.
- Raw responses, runtime metadata and offline annotations:
  [JSON results](../reports/p3_hy_mt2_material_glossary_probe_v1.json).
- Machine-readable manual inspection:
  [JSON preliminary review](../reports/p3_hy_mt2_material_glossary_review_v1.json).
- Simple per-request metrics:
  [CSV](../reports/p3_hy_mt2_material_glossary_probe_v1.csv).

No PostgreSQL rows, model registry, worker deployment, API tokens, secrets,
long-lived GPU containers or stored model weights were changed. The model Volume
was **reused**, not downloaded or rehashed.

## Evaluation limitations and next gate

1. The four language directions of the old narrative are **retests of a known
   failure**, not independent held-out examples.
2. The other four Vietnamese texts are newly authored but intentionally target
   the observed class of material/negation errors, and do not form a general
   multilingual translation benchmark.
3. One seed and one generation per case are insufficient for robustness
   estimates. The two prompts have different lengths, which can affect
   latency/prompt caching; this does not measure a production QPS distribution.
4. Automated material-term indicators cannot assess adequacy, grammar,
   context, intent, gender, names or naturalness.
5. German, Japanese and Korean native-speaker human assessment remains open.
6. The prior verified fairy-tale archive was **not available** in Codespaces.
   For an independent reference-based benchmark, FLORES+ is a candidate
   (https://huggingface.co/datasets/openlanguagedata/flores_plus), but it has
   **gated access** and CC BY-SA 4.0 licensing; the current Codespaces has no
   authenticated access/accepted conditions. Do not bypass dataset gating or
   copy licensed reference text indiscriminately into a public repository.
7. Before selecting a default model, freeze a truly independent evaluation
   corpus and glossary version; perform chrF++ reference scoring and human
   adequacy review, multiple seeds, all eight directions, and near-1,000
   character samples. Reuse identical cases for Index/Gemma/Qwen.

**Decision:** glossary is promising for this known error class; **Hy-MT2 is
still NOT production-ready**. CPU gateway remains mock-only.
