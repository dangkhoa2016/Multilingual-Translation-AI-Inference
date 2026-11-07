# Security policy

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](SECURITY.vi.md)

## Scope

This is an independent, self-hosted translation inference service. Each
operator is responsible for database credentials, API tokens, cloud
accounts, GPU billing, external access, and retention settings.

## Reporting vulnerabilities

**Do not open a public issue containing exploit details, secrets or
private user text.** Use GitHub's private vulnerability reporting/security
advisory feature for this repository when available, or contact
**Đăng Khoa <i.am@dangkhoa.dev>** privately with a minimal reproduction.

Include the affected code path, expected impact, safe reproduction steps
and relevant version. Never attach an actual production token or database URL.

## Current security boundary

- All `/v1` endpoints require a bearer token; `/health` is public.
- GPU workers bind their internal server to loopback, not an external URL.
- PostgreSQL stores durable job state and idempotency keys.
- Uncertain outcomes do **not** trigger automatic inference retries.
- App-level USD amounts are estimates, not provider billing guarantees.
- A complete external security assessment and multi-tenant isolation
  are **not** claimed.

Report and coordinate a fix privately before public disclosure.
