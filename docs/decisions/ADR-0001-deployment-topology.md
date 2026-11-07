# ADR-0001: One Modal App with four independently scaling L40S model workers

- **Date:** 2026-11-06
- **Status:** Accepted in prior planning, awaiting runtime verification

## Context

Translation calls are sporadic and mostly text-only (~1,000 characters). Each candidate GGUF Q8_0 is ~32–38 GB, requiring room for KV cache and engine overhead. The goal is the best translation quality possible under one L40S 48 GB **per model**, not a forced single common model.

## Decision

1. One source repository and one Modal App containing CPU FastAPI gateway and four independent GPU functions/classes.
2. Workers use L40S 48 GB; each pool starts at `min_containers=0`, `buffer_containers=0`, `max_containers=1`.
3. Async `.spawn()` is the default for submitting model work; PostgreSQL persists jobs/results and partial benchmark outputs.
4. Weights are cached once in dedicated volumes; models are started only when needed, not by web polling.
5. The first GPU smoke is Hy-MT2 Q8_0; Index follows; Gemma 4 IT and Qwen3.5 follow after P1–P2 reliability gates.

## Reasons

- Independent scale-to-zero minimizes billed idle GPU time compared with always-on GPUs.
- Fits model-specific chat templates and configs into one codebase without coupling failure domains.
- Keeps GET/read traffic CPU-only and allows partial benchmark results.

## Consequences and constraints

- Cold starts and model loads can be large; async response is mandatory in v1.
- Four concurrent workers are **not guaranteed** until workspace L40S quota is checked.
- GGUF Q8 size is not equal to peak VRAM; P3/P4 must log VRAM and may adapt context/quant if OOM.
- Modal `spawn()` is not transactional with PostgreSQL; reconciliation and idempotency must be implemented and tested in P2.
- Database, model volumes, CPU gateway, and transfer can still incur cost even when no GPU is warm.

## Alternatives not chosen

- **One A100 80GB holding all four Q8 files:** the sum of weights alone (~139 GB) exceeds 80GB; would require swapping models or quantization and is not the selected architecture.
- **Four always-on GPU deployments:** too expensive for infrequent usage.
- **Redis/Celery/Sidekiq workers for v1:** not necessary for the stated workload; Modal background functions + PostgreSQL are sufficient if recovery logic is implemented.
