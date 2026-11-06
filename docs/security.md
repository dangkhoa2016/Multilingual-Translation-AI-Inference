# API gateway security

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](security.vi.md)

The CPU gateway validates Bearer credentials before accepting JSON bodies or
dispatching any jobs. The read-only `GET /v1/models` catalog is public and
rate-limited; all other `/v1/` routes require Bearer authentication. The
public `/` homepage is static and bilingual, without Secrets or job data;
the unauthenticated `/health` endpoint reports CPU gateway liveness only. The
interactive Swagger UI and public OpenAPI schema are disabled.

## Request limits before authentication

Every `/v1/` request uses fixed minute windows on the process's monotonic clock:
by default **120 requests per peer/minute** and **600 per process/minute**.
Exhaustion returns 429 with `Retry-After` **before comparing tokens** or reading
bodies. Valid credentials also obey this ceiling. Rotating peers can evict old
peer counters from RAM but cannot reset the process-wide counter.
Fixed windows allow bursts around minute boundaries.

`TRANSLATION_MAX_REQUESTS_PER_MINUTE_PER_PEER` and
`TRANSLATION_MAX_REQUESTS_PER_MINUTE_PER_PROCESS` configure these ceilings.
Separately, `GET /v1/jobs/{job_id}` uses a PostgreSQL-shared owner quota,
default **120 per UTC minute**, configured by `TRANSLATION_MAX_JOB_POLLS_PER_MINUTE`.
Malformed job UUIDs fail validation before consuming polling quota.
Health and catalog handlers use neither database nor GPU. The public catalog
obeys the same per-peer/process request limits, but missing or invalid tokens
on catalog requests do not count as authentication failures.

## Failed authentication protection

By default, **three failed Bearer attempts within five minutes** against
the same ASGI peer identity cause HTTP **429** and a **15-minute** temporary
lockout in that gateway process. Earlier failures return HTTP **401** with
`WWW-Authenticate: Bearer`. A lockout responds with `Retry-After` in seconds.
Within the remaining request budget, successful authentication clears the
peer's failed-attempt history, including during that period. This failure
signal still compares eligible tokens; the pre-auth ceiling bounds those
comparisons independently.

These defaults are adjustable through the API authentication Modal Secret:

| Variable | Default | Description |
|---|---:|---|
| `TRANSLATION_AUTH_FAILURE_LIMIT` | `3` | Failed attempts before local lockout |
| `TRANSLATION_AUTH_FAILURE_WINDOW_SECONDS` | `300` | Sliding window for failures |
| `TRANSLATION_AUTH_LOCKOUT_SECONDS` | `900` | Temporary lockout duration |
| `TRANSLATION_AUTH_MAX_TRACKED_CLIENTS` | `4096` | Maximum peer records per process |
| `TRANSLATION_MAX_API_BODY_BYTES` | `65536` | Body cap on protected requests |

All configured values must be positive and within validated bounds.
This guard uses bounded in-process memory; it does not add database calls or
start any GPU worker. An expired lockout resets the sliding failure window.

## Token strength

The deployed gateway requires a **16–4096-character printable ASCII** Bearer token
(without spaces or control characters, including tabs and newlines). The notebook
uses the same token policy. Prefer a randomly generated token from a
secrets manager (for example, `secrets.token_urlsafe(32)`), not a memorable
password. On an existing installation, verify token length privately before
redeployment and coordinate any token rotation with API clients. Follow [safe Bearer token rotation](token-rotation.md).

## Peer identity and deployment limits

The guard uses the IP address in the trusted ASGI client scope. It **never**
parses a caller-supplied `X-Forwarded-For` or `Forwarded` header. The hosting
platform or trusted reverse proxy must supply a reliable peer identity. If a
proxy reports a single shared address for multiple users, their failed-attempt
counters share a bucket; valid credentials bypass the failure signal but
still obey the shared peer request ceiling.

**Important: the limit is per gateway process, not a global per-IP promise.**
Modal can run multiple CPU gateway containers, and the in-memory counters
do not persist across container restarts or synchronize between replicas.
A flood of distinct peers can also evict older counters from bounded memory.
To enforce a strict limit across instances, use a trusted-edge WAF/rate
limiter or an atomic shared store with vetted proxy/IP handling. Do not rely on
these local counters alone for internet-scale DDoS protection.

## Request and response safeguards

- Bearer credentials are checked before reading a potentially oversized or
  malformed request body. Invalid credentials cannot force JSON parsing.
- For authenticated `/v1/` requests, bodies exceeding the configured cap
  return HTTP **413**, including requests without `Content-Length`.
- All `/v1/` responses, including the public catalog, send `Cache-Control: no-store` and
  `X-Content-Type-Options: nosniff`. Tokens are never included in error bodies.
- Job quotas, idempotency, and estimated GPU budget limits remain separate
  controls against authenticated abuse and accidental paid inference.
- The API is **single-tenant**: one shared Bearer token does not establish
  independent customer authorization. Rotate credentials if compromised.

The public, rate-limited catalog `GET /v1/models` is read-only: `dispatch_enabled` describes
configuration, `runtime_verified` summarizes historical validation, and
`runtime_status="not_checked"` means no live GPU probe occurred. The existing
`enabled` field is retained for backward compatibility and never guarantees
current GPU readiness. Neither `GET /v1/models` nor `GET /health` starts GPUs.

## Optional access metadata

Set `TRANSLATION_AUDIT_LOG_ENABLED=true` to emit JSON to stdout with an
allowlisted method, route template, HTTP status, authentication outcome and
duration. Records omit tokens, bodies, translations, queries, UUIDs, IPs and
owners. Unknown routes use `/v1/unmatched`; unhandled handler errors return a
generic 500 response. Logging defaults off. When enabled, events are bounded
by the process request limit per minute; excess events are dropped. This is
best-effort operational metadata, not a complete forensic audit trail.
Operators control retention and access; reverse proxy/hosting logs need their
own policy.

## Verification and incident response

Run the offline regression checks without GPU allocation:

```bash
python -m pytest -q tests/api/test_auth_guard.py
python -m pytest -q
python -m ruff check .
```

A `401` indicates missing/invalid credentials; `429` with
`Too many failed authentication attempts` indicates the local authentication
guard; `429` for a job quota has a different detail. In either case honor
`Retry-After`. Avoid repeatedly retrying a paid POST with an uncertain result:
retain its idempotency key and reconcile the job before proceeding.

Changing a Modal Secret may require a controlled application rollover. Do not
print credentials, copy request bodies into logs or publish live job IDs.
See [configuration](configuration.md), [deployment](deployment.md), and
[operations](operations.md).
