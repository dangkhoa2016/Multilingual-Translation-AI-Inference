# Roadmap and evidence boundaries

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](roadmap.vi.md)

The project is a **working, authenticated GPU inference preview**.
Four distinct GGUF models have completed real translation jobs
through Modal and PostgreSQL. Operational compatibility is not
an independent certificate of translation quality or production security.

## Verified

- Four dedicated L40S workers load pinned GGUF artifacts.
- Parallel execution across four distinct GPUs has been observed.
- The CPU API writes and polls durable PostgreSQL jobs.
- One-model and four-model API requests return nonmock results.
- The exact 1,000 Unicode-codepoint input boundary was exercised.
- Small-scale same-model concurrency and warm container reuse were tested.
- An hourly CPU operations monitor runs without allocating GPUs.
- Idempotency, quota admission and uncertain-state handling have
  automated CPU regression coverage.

## Still required before a stable public release

1. **Translation quality:** a fixed multilingual reference corpus,
   reviewers for all eight directions, fidelity/terminology scoring
   and disagreement analysis. Prior Hy-MT2 tests already exposed
   material-substitution errors.
2. **Operational resilience:** isolated staging fault injection, delayed
   acknowledgements, recovery, queue load and sustained reliability tests.
3. **Security:** multi-tenant isolation if applicable, penetration review,
   token lifecycle and data retention controls.
4. **Real spending controls:** an operator-approved Modal Workspace
   Budget and an external alert destination; estimated per-run admission
   cannot measure provider billing.
5. **Release qualification:** documentation, compatibility, CI and
   independent quality results before announcing a stable version.

No unverified throughput SLA, benchmark winner or guarantee of
cost-free GPU idle storage is implied by this roadmap.

See [benchmarking](benchmarking.md), [reliability](reliability.md),
[operations](operations.md) and [community support](../.github/SUPPORT.md).
