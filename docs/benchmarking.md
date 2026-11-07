# Translation benchmarking — evidence and quality review

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](benchmarking.vi.md)

## What has been verified

The repository includes **real** Modal L40S execution reports. It does
not use synthetic JSON alone to claim a model is capable of inference.

| Evidence | What it demonstrates | What it does *not* demonstrate |
|---|---|---|
| [Four-GPU inference](../reports/four_gpu_parallel_inference.json) | Four model loads and nonempty responses on distinct GPUs | Translation accuracy |
| [API four-model benchmark](../reports/gpu_api_four_model_benchmark.json) | Authenticated jobs, PostgreSQL persistence and nonmock outputs | Ranking by adequacy |
| [1,000-character boundary](../reports/unicode_input_boundary.json) | Valid input boundary across four models | Long-document performance |
| [Hy-MT2 multilingual diagnostic](../reports/hy_mt2_quality_diagnostic.json) | Outputs in eight directional language cases | Reference-based score |
| [Hy-MT2 terminology review](../reports/hy_mt2_material_glossary_review.json) | Specific material/wording failure analysis | A general solution to mistranslation |

The Hy-MT2 diagnostic covers English↔Vietnamese, German↔Vietnamese,
Japanese↔Vietnamese and Korean↔Vietnamese. Sixteen cases completed,
but the absence of automatic warnings **did not imply semantic
correctness**.

## Important fidelity findings

Human inspection found examples of the meaning of material terms being
changed, including a source **silver compass** rendered with a different
material. A glossary-based prompt improved some known cases, but did
not prove accuracy on unseen sentences. This issue should be assessed
for all model families, not treated as a Hy-MT2-only edge case.

No model in this repository has a published independent, adequately
large, human-reviewed reference-based accuracy score. Do **not**
advertise a winner or a perfect translator using the current reports.

## Suggested fair evaluation protocol

1. Fix source examples independently of model outputs: short and long
   passages, negation, numbers, units, idioms, names, culturally specific
   phrases, markdown and placeholders.
2. Cover all eight translation directions and use qualified reviewers
   for German, Japanese and Korean as well as Vietnamese and English.
3. Use the same source data, permissible token budget and well-documented
   decoding settings for each model. Preserve model-specific chat
   formatting required by the upstream architecture.
4. Record adequacy (meaning), fluency, terminology, omissions,
   additions, format preservation and unsupported hallucinations.
5. Report reviewer agreement and uncertainty. If COMET/BLEU are used,
   specify the metric implementation and its reference translation.
6. Keep model outputs and review notes under source-controlled,
   privacy-safe artifacts only; avoid real users' private text.

## Reproduce the existing evidence

```bash
# CPU-only: validate stored reports and manifest, no GPU allocations
python -m pytest -q
PYTHONPATH=src python scripts/verify_hy_mt2_metadata.py

# Real GPU is billable: only run with approved resources
PYTHONPATH=src python scripts/modal_four_model_gpu_smoke.py --help
PYTHONPATH=src python scripts/api_reliability_smoke.py --help
```

Original artifacts and review notes are retained under
[`reports/`](../reports) with stable descriptive names. Their timestamps
are machine-level provenance; they are not a claim that a benchmark
remains current indefinitely. See [model catalog](models.md)
and [reliability](reliability.md).
