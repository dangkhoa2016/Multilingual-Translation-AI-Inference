# Hy-MT2 L40S — Synthetic diagnostic results

**Caution:** Not a certified quality benchmark; no human-reviewed reference translations.
Do not report BLEU/COMET/translation accuracy from this diagnostic.

- Status: completed
- Completed outputs: 16/16
- Cases with automatic fidelity warnings: 0
- Modal client call wall time: 52.271 seconds (includes scheduling, but not an external HTTP gateway benchmark)
- Server load to ready: 17.246 seconds
- Highest sampled GPU memory: 31189 MiB (200 ms sampling, not exact peak)
- Dataset SHA256: c58fefdde648a1d69e53fdecd111da2593fcb17c3108076b2fa76c58763cdc2a

| Case | Time (s) | Completion tokens | Warnings |
|---|---:|---:|---|
| en_to_vi_structured | 0.787 | 84 | none |
| en_to_vi_narrative | 2.86 | 387 | none |
| vi_to_en_structured | 0.462 | 56 | none |
| vi_to_en_narrative | 1.811 | 230 | none |
| de_to_vi_structured | 0.61 | 77 | none |
| de_to_vi_narrative | 2.851 | 378 | none |
| vi_to_de_structured | 0.671 | 85 | none |
| vi_to_de_narrative | 2.876 | 379 | none |
| ja_to_vi_structured | 0.645 | 81 | none |
| ja_to_vi_narrative | 4.394 | 582 | none |
| vi_to_ja_structured | 0.707 | 89 | none |
| vi_to_ja_narrative | 2.853 | 376 | none |
| ko_to_vi_structured | 0.616 | 77 | none |
| ko_to_vi_narrative | 4.33 | 569 | none |
| vi_to_ko_structured | 0.729 | 92 | none |
| vi_to_ko_narrative | 3.04 | 402 | none |

## Human review required

Compare each source and output in the JSON report for adequacy, fluency, named entities, numbers, negation, omitted clauses, added meaning, honorifics, paragraph breaks and domain terminology. Use qualified DE/JA/KO reviewers.

P2 CPU gateway remains mock-only; no production GPU API is deployed.
