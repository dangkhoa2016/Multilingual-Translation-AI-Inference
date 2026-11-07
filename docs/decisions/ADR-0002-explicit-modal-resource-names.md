# ADR-0002 — Explicit Modal App, Function, Secret and Volume names

Status: Accepted in P1 source code (resources **not** created automatically)
Date: 2026-11-06

## Decision

Use human-readable identifiers with project purpose, model family, model size,
and the stored content, not generic names such as `app`, `volume1`, `data`,
`model-cache` or cryptic shorthand. Exact strings live in
`src/translation_ai_inference/resource_names.py` and are reproduced in both README files.

- App: `translation-ai-inference-api-and-model-workers`.
- PostgreSQL connection Secret: `translation-ai-inference-postgresql-connection`.
- Gateway: `translation_inference_fastapi_cpu_gateway`.
- Mock CPU: `translation_inference_cpu_mock_job_worker`.
- Each model receives a separately named `translation-ai-inference-<model>-gguf-weights` Volume.
- Actual L40S worker functions are reserved per model with distinct names but are
  intentionally not registered in P1; registration will occur after P3/P4 gates.

## Consequences

A deployment cannot silently create a generic model Volume. GPU resources are only
created after validated weights, runtime compatibility, account quota and cost budget.
Name changes later require an explicit migration rather than a transparent rename.
The PostgreSQL connection Secret name is stable across hosting providers.
