# Safe API Bearer token rotation

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](token-rotation.vi.md)

This project uses **one shared Bearer token** by design (single-tenant). Token rotation does not add tenants, enable GPU inference or change model weights. `GET /health` and `GET /v1/models` are public; job creation and retrieval continue to require Bearer authentication.

## When to rotate

Rotate compromised or potentially exposed credentials, on the schedule required by your security policy, or when transferring operations. Updating the Modal Secret **does not** update credentials stored in Rails applications, notebooks, external API clients or local `.env` files.

## Prerequisites and limitations

- Use an explicitly verified Modal profile and environment. Do not delete/recreate Secrets, use `modal secret create --force`, or restage the GGUF weights just to rotate credentials.
- Reconcile pending jobs before maintenance. The `recreate` rollover strategy can terminate active containers and interrupt requests or running jobs.
- **Zero-downtime rotation is not guaranteed** with a single shared token. Clients may receive HTTP 401 while switching credentials.
- Requires a Modal SDK/CLI with `Secret.update()` (added in 1.3.5), `python-dotenv`, permission to update the existing Secret and rollover the App.
- The helper changes only `TRANSLATION_API_BEARER_TOKEN`; `TRANSLATION_DISPATCHER_MODE` and GPU scheduling are untouched.
- Recreate replaces old containers before claiming that the old credential has been revoked.

## Step 1 — Prepare two private files

The existing file contains your **current** token (for example `/secure/current-api.env`), with `0600` permissions. The new file must contain only `TRANSLATION_API_BEARER_TOKEN`.

```bash
umask 077
export CURRENT_TOKEN_FILE="/secure/current-api.env"
export NEW_TOKEN_FILE="/secure/new-api.env"
chmod 600 "$CURRENT_TOKEN_FILE"
python - <<'PY'
from pathlib import Path
from secrets import token_urlsafe
import os

path = Path(os.environ['NEW_TOKEN_FILE'])
if path.exists():
    raise SystemExit('New token file already exists; refusing to overwrite.')
with path.open('x') as stream:
    stream.write('TRANSLATION_API_BEARER_TOKEN=' + token_urlsafe(48) + '\n')
path.chmod(0o600)
print('New private token file created; token value not displayed.')
PY
```

Never print, share or commit these files. Retain the old credential privately until the operation has been verified.

## Step 2 — Dry-run without network access

```bash
cd /path/to/Multilingual-Translation-AI-Inference
export MODAL_PROFILE=YOUR_MODAL_PROFILE
export MODAL_ENVIRONMENT=YOUR_MODAL_ENVIRONMENT

PYTHONPATH=src python scripts/deployment/rotate_api_bearer_token.py \
  --profile "$MODAL_PROFILE" \
  --environment "$MODAL_ENVIRONMENT" \
  --current-token-env-file "$CURRENT_TOKEN_FILE" \
  --new-token-env-file "$NEW_TOKEN_FILE"
```

Dry-run checks file permissions, token formats, and distinct credentials; it performs no network calls, Secret writes or container rollovers.

## Step 3 — Apply deliberately (service interruption possible)

Run only when clients have been coordinated and active jobs reviewed.

```bash
export TRANSLATION_GATEWAY_BASE_URL='https://YOUR_GATEWAY.modal.run'

PYTHONPATH=src python scripts/deployment/rotate_api_bearer_token.py \
  --profile "$MODAL_PROFILE" \
  --environment "$MODAL_ENVIRONMENT" \
  --current-token-env-file "$CURRENT_TOKEN_FILE" \
  --new-token-env-file "$NEW_TOKEN_FILE" \
  --base-url "$TRANSLATION_GATEWAY_BASE_URL" \
  --apply --confirm-job-interruption
```

The helper checks GET `/health`, verifies the current token by GET `/v1/jobs/not-a-uuid` (HTTP 422 after authentication), merges **only** `TRANSLATION_API_BEARER_TOKEN` with `Secret.update()`, runs `modal app rollover --strategy recreate`, then verifies the new token gets HTTP 422 and the old one HTTP 401. **No POSTs, job submissions or GPU allocations** are performed by these checks.

For verification failures other than throttling, the helper **attempts** to restore the old key and recreate containers again. A network or cloud failure can leave the outcome uncertain; investigate the Modal deployment and reconcile jobs rather than blindly retrying.

**Exit status:** `0` means acceptance of the new token and rejection of the old token were both verified. `2` means HTTP 429 prevented conclusive verification: the new Secret is left in place (no automatic rollback); the operator must reconcile the credentials manually. `1` means another failure occurred, and rollback may have been attempted. Never treat exit `2` as success or blindly rerun the helper.

## Step 4 — Update every trusted client

Update server-side credentials for Rails, API scripts, notebooks and other private integrations. Never embed the Bearer token in public HTML, browser JavaScript, release notes or documentation. Once verified, store the new credential in your secret manager and retire the old copy according to policy.

## Troubleshooting

- **HTTP 401:** a client may still use the old credential, or rollover has not completed.
- **HTTP 429:** respect `Retry-After`; repeated incorrect tokens can trigger lockout.
- **HTTP 422 at `/v1/jobs/not-a-uuid`:** the token passed authentication and the intentionally invalid job UUID was rejected, as designed.
- **Uncertain outcome:** inspect Modal Secret metadata, rollout history and redacted logs; never display credentials. Reconcile in-flight jobs first.

See [configuration](configuration.md), [security](security.md) and [deployment](deployment.md).
