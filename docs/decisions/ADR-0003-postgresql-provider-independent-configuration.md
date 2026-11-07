# ADR-0003 — PostgreSQL provider-independent names and configuration

- **Date:** 2026-11-07
- **Status:** Accepted in source; no cloud resources have been renamed or created by this change.

## Decision

The service uses PostgreSQL as a database protocol, but **never encodes a hosting provider**
in Modal resource names, environment variable names, Python identifiers, or the API title.
The provider can be Neon now and another PostgreSQL host later.

| Purpose | Stable identifier |
|---|---|
| Modal App | `translation-ai-inference-api-and-model-workers` |
| Modal PostgreSQL Secret | `translation-ai-inference-postgresql-connection` |
| Runtime connection env key | `TRANSLATION_INFERENCE_DATABASE_URL` |
| Migration connection env key | `TRANSLATION_INFERENCE_MIGRATION_DATABASE_URL` |
| API Bearer Secret | `translation-ai-inference-api-authentication` |

Old draft identifiers such as `translation-ai-inference-modal-neon`,
`translation-ai-inference-neon-postgresql-database`, and
`TRANSLATION_NEON_DATABASE_URL` are **not supported aliases**; there was no
previous cloud deployment to migrate at the time of this ADR.

## Provider switch procedure

1. Provision another PostgreSQL-compatible database and check supported extensions/schema.
2. Apply Alembic migrations against the new direct database URL.
3. Migrate/verify durable data, if applicable, before any DNS/Secret cutover.
4. Update only the connection string under the same Modal Secret/env key.
5. Verify `/health`, job submission, results and recovery, then retire old credentials.

Pooler requirements vary: prefer pooled runtime URL for bursty serverless calls,
use direct connection for schema migrations, and avoid assuming all providers
support Neon-specific suspend or pooling features.

## Consequences

App/Secret names remain stable across Neon, RDS, Supabase, self-managed Postgres,
and other PostgreSQL providers. Switching the provider is a credentials/data
migration, not a rename of inference API resources. The change does not alter
the four independently named model weight Volumes.
