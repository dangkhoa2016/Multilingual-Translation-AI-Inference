# Engineering decisions and trade-offs

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](design-decisions.vi.md)

These are the stable architectural choices behind the current runtime,
not a chronological change log.

## One App with four independent model workers

All four GPU classes and the CPU gateway are defined in one
[`modal_app.py`](../modal_app.py). Each model has its own
dedicated Volume, prompt/decoding behavior and GPU container.
This supports intermittent traffic at lower idle GPU compute
cost than four always-on deployments.

Trade-off: cold starts require tens of gigabytes of model loading,
and four concurrent L40S allocations depend on workspace capacity.
Scale-to-zero does not eliminate persistent Volume or database costs.

## PostgreSQL as durable source of truth

A job is committed to PostgreSQL before asynchronous Modal dispatch.
Claim tokens fence duplicate runs and results are persisted before
the client polls. `spawn()` cannot be transactionally committed
together with PostgreSQL, so the system distinguishes definite
failures from uncertain outcomes. It never automatically retries
an uncertain GPU execution.

We intentionally do not require Redis, Celery or Sidekiq for this
sporadic inference workload. PostgreSQL does not replace a future
specialized queue if throughput or fairness requirements increase.

## Provider-independent resources

The App, Secret names, environment variables and API contract do
not hard-code a particular PostgreSQL hosting company.
Cloud provider migrations should preserve stable resource names,
migrate database contents, verify schema, then update secrets.

## Model provenance and licenses

GGUF files are pinned by repository revision, exact filename, bytes
and SHA256; CPU verification happens before model startup.
The project source is MIT, while model weights retain their
upstream Apache-2.0 declarations. No weights are committed to Git.

## Security and cost caveats

The service exposes only the authenticated CPU API, not the per-GPU
loopback model server. A user-selected estimated budget can restrict
admission, but it is not a true spending cap. A separate Modal
Workspace Budget and real alert delivery are operator responsibilities.

See [architecture](architecture.md), [model licensing](../MODEL_LICENSE.md),
and [operations](operations.md).
