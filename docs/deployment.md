# Deployment — Modal GPU inference and PostgreSQL

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](deployment.vi.md)

This runbook deploys one **CPU API gateway** and four independent NVIDIA L40S
model workers into one Modal App. It assumes you control your Modal
workspace and PostgreSQL database. GPU operations are billable.

## Requirements

- Python 3.12 with `pip`, and your own Modal account; CLI authentication is covered below.
- A reachable PostgreSQL database, preferably with TLS and a pooled
  runtime connection. Use a direct URL for Alembic migrations.
- Two named Modal Secrets holding the database URL and API Bearer token.
- Before **real GPU inference**, four dedicated Modal Volumes containing
  the SHA256-verified pinned GGUF files. A **new installation** can create
  and populate them using the provisioning steps below; see
  [the model manifest](../models/four_l40s_workers_q8_0_manifest.json).
- An operator-approved cost envelope. **Do not assume a developer
  account or workspace budget is available.**

## Prepare the local project environment

Clone the repository (or open an existing checkout) and install the source
package **before** using any staging, migration or deployment scripts.
The commands below use a Bash shell and Python 3.12 or newer; Jupyter and
GPU hardware are not needed for preparation.

```bash
git clone https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference.git
cd Multilingual-Translation-AI-Inference
git checkout v1.0.0
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

If the project is already checked out, start at the `python3.12 -m venv`
command from the repository root. Your activated environment supplies the
`multilingual_translation_ai_inference` package imported by the staging
tool. This installs software locally; it does not stage weights or start GPU.

## Authenticate Modal and select an environment

Create your account at [Modal](https://modal.com), then use the CLI installed
in the activated virtualenv. Choose a local profile name and authenticate in
the browser; a Modal token is separate from the translation API Bearer token.

```bash
export MODAL_PROFILE=translation-demo
modal token new --profile "$MODAL_PROFILE"
modal profile current --profile "$MODAL_PROFILE"
modal environment list --profile "$MODAL_PROFILE"
export MODAL_ENVIRONMENT=main
```

Use an existing environment you control, or create a new one once:

```bash
# Optional: use a separate new environment instead of main.
# modal environment create translation-demo --profile "$MODAL_PROFILE"
# export MODAL_ENVIRONMENT=translation-demo
```

Keep both exports in the same terminal throughout provisioning, staging,
deployment and mode switching. Commands without explicit options inherit
`MODAL_PROFILE` and `MODAL_ENVIRONMENT`. Secrets, Volumes and the App must
all be in that same workspace/environment. Do not reuse a maintainer's profile.

## Configure credentials and Secrets (new installations only)

Work with **your own** Modal profile/environment and PostgreSQL instance.
Do not use an existing production Secret or Volume as a tutorial fixture.
For local migration tools, create an untracked `.env` from
[`.env.example`](../.env.example), replacing the example SQLite URL
with your own PostgreSQL URLs. The runtime URL can use a provider pooler;
`TRANSLATION_INFERENCE_MIGRATION_DATABASE_URL` should point to a
**direct** PostgreSQL connection. Never paste credentials into a Git-tracked
file.

This repository does not provision PostgreSQL. Create a database and role
with permission to create the schema, and allow connections from your local
migration machine and Modal containers. Obtain runtime and direct migration
URLs from your database provider. They must point to the **same database**.
Percent-encode special characters in URL usernames/passwords and use your
provider's TLS requirements. For example, the private local `.env` can contain:

```dotenv
TRANSLATION_INFERENCE_DATABASE_URL='postgresql+psycopg://DB_USER:URL_ENCODED_PASSWORD@RUNTIME_HOST:5432/DB_NAME?sslmode=require'
TRANSLATION_INFERENCE_MIGRATION_DATABASE_URL='postgresql+psycopg://DB_USER:URL_ENCODED_PASSWORD@DIRECT_HOST:5432/DB_NAME?sslmode=require'
TRANSLATION_API_BEARER_TOKEN='YOUR_OWN_LONG_RANDOM_TOKEN'
```

Replace every placeholder. Use the identical runtime URL in the database
Modal Secret and the identical Bearer token in the API Secret and clients.
Only the migration command needs the direct URL. Keep `.env` private; the
notebook does not automatically read it.

Create the following **two separate private JSON files outside Git**,
with permissions `0600`, before executing the commands below:

`/secure/translation-postgresql.json` (replace the URL with the runtime
URL from your private `.env`, without the surrounding shell quotes):

```json
{
  "TRANSLATION_INFERENCE_DATABASE_URL": "YOUR_OWN_RUNTIME_POSTGRES_URL"
}
```

`/secure/translation-api.json` (replace the token; add admission quotas only
when needed):

```json
{
  "TRANSLATION_API_BEARER_TOKEN": "YOUR_OWN_LONG_RANDOM_TOKEN",
  "TRANSLATION_DISPATCHER_MODE": "modal-cpu-mock"
}
```

Replace both `/secure/...` example paths with private paths on your own
computer. Generate a random Bearer token using a secure secret manager;
the quoted placeholders are **not** valid deployment credentials.

```bash
modal profile current
modal secret list --env "$MODAL_ENVIRONMENT"

# New installations ONLY: omit --force to avoid overwriting existing Secrets.
modal secret create --env "$MODAL_ENVIRONMENT" \
  multilingual-translation-ai-inference-postgresql-connection \
  --from-json /secure/translation-postgresql.json
modal secret create --env "$MODAL_ENVIRONMENT" \
  multilingual-translation-ai-inference-api-authentication \
  --from-json /secure/translation-api.json

# Verify resource names only. The CLI does not print Secret values.
modal secret list --env "$MODAL_ENVIRONMENT"
```

Keep the JSON files private, access-controlled and out of backups intended
for public sharing. Existing installations should **skip Secret creation**;
see [configuration](configuration.md) for the variable reference and the
single-key mode switch later in this guide. Creating a Secret or Volume does
not start GPU inference.

## Provision GGUF Volumes (new installations only)

The four Volumes are **not shipped with the repository**. If they are already
provisioned and verified, **skip this entire section**: never delete,
recreate or restage an existing production Volume just to follow a guide.

1. Review the four model entries, pinned revisions, file sizes and
   SHA256 hashes in the [model manifest](../models/four_l40s_workers_q8_0_manifest.json).
   Check Modal access, available storage and your approved cost budget.
2. Use `modal volume list` to inspect the **correct Modal profile and
   environment** before provisioning. For a fresh installation only,
   [`create_volumes.sh`](../scripts/deployment/create_volumes.sh) creates
   the four named empty Volumes when
   `CONFIRM_TRANSLATION_GPU_VOLUME_CREATION=YES` is set. It does **not**
   download weights; do not run it against existing Volumes.
3. [`stage_model_weights.py`](../scripts/models/stage_model_weights.py)
   stages **one model at a time** into its existing Volume using a Modal
   **CPU** task. Without `--stage` it only prints the selected model.
   With `--stage`, it downloads the pinned GGUF, checks byte length and
   full SHA256, writes the verified marker and commits the Volume.
   CPU execution, downloads and persistent storage may incur charges.
4. Confirm all four verified markers and GGUF files before deployment.
   A marker is not a substitute for the checksum validation performed
   by the staging script. Do not alter the manifest to bypass failures.

```bash
# Inspect the profile/environment selected above.
modal profile current
modal volume list --env "$MODAL_ENVIRONMENT"

# NEW INSTALLATIONS ONLY: create four empty Volumes in the selected environment.
CONFIRM_TRANSLATION_GPU_VOLUME_CREATION=YES bash scripts/deployment/create_volumes.sh

# Preview a single model; no transfer without --stage:
modal run scripts/models/stage_model_weights.py --model hy_mt2_30b

# Explicit CPU download/storage charges: stage all four models, one at a time.
for model in hy_mt2_30b index_35b gemma4_31b_it qwen35_35b; do
  modal run --profile "$MODAL_PROFILE" --env "$MODAL_ENVIRONMENT" \
    scripts/models/stage_model_weights.py --model "$model" --stage || break
done
```

Run the download loop only after accepting storage and CPU charges for about
139.33 GB of GGUF weights. Downloads occur in Modal CPU tasks, not on your
laptop. Each invocation must return `verified_and_committed` or
`already_verified`; stop on any failure. Re-running the same model with
`--stage` recomputes its full SHA256 before returning `already_verified`.
Do not continue to deployment if any of the four models was not verified.

Inspect the resulting files without allocating a GPU:

```bash
python - <<'PYTHON'
import json
import os
import subprocess
from pathlib import Path

models = json.loads(Path("models/four_l40s_workers_q8_0_manifest.json").read_text())["models"]
for key, spec in models.items():
    print(key, spec["gguf_filename"], spec["gguf_size_bytes"], "bytes", flush=True)
    subprocess.run(["modal", "volume", "ls", "--env", os.environ["MODAL_ENVIRONMENT"],
                    spec["modal_volume_name"], "/"], check=True)
PYTHON
```

Expect the exact `gguf_filename` and `gguf_size_bytes` from the manifest,
plus `hy_mt2_q8_0_verified.json` for Hy-MT2 or `verified_gguf_q8_0.json`
for each other model. Listing proves file presence, not checksum validity;
the successful staging result is the checksum check. A fresh installation
must prepare all four Volumes because the App references all four.

## Prepare the database schema

With the local project environment already installed and activated:

```bash
# Reuse the .env prepared in "Configure credentials and Secrets" above.
# It must contain TRANSLATION_INFERENCE_MIGRATION_DATABASE_URL (direct PostgreSQL).
# Do not overwrite it from .env.example or use the example SQLite URL.
set -a; source .env; set +a
alembic -c db/alembic.ini upgrade head
alembic -c db/alembic.ini current
```

Expect revision `0005_pending_admission` at head. Resolve migration errors
before deployment; check the direct URL, TLS, network and schema permissions
without publishing credentials. Back up existing databases and migrate before
rolling out this API. Revision 0003 widens language labels, 0004 adds missing
nullable telemetry columns, and 0005 creates stable admission locks; stored
jobs/results are retained. Review offline PostgreSQL SQL without connecting:

```bash
alembic -c db/alembic.ini upgrade head --sql > /secure/translation-schema.sql
```

This exports a fresh-install script; an existing database needs its actual
starting revision, for example `upgrade 0004_run_metrics:head --sql`. Online
upgrade inspects existing telemetry columns; offline PostgreSQL SQL uses
`ADD COLUMN IF NOT EXISTS`. Offline deployment SQL targets PostgreSQL only.

The API Secret uses `TRANSLATION_API_BEARER_TOKEN`, while the database
Secret uses `TRANSLATION_INFERENCE_DATABASE_URL`. For exact names and
optional quota settings, see [configuration](configuration.md). Never
paste a real token into a checked-in file.

## Deploy the App

By default, the CPU operations monitor is **not scheduled**. To opt into
hourly checks, set the deploy-time shell variable to `hourly`.
This is not a Modal Secret and does not enable GPU:

```bash
# Default: no scheduled monitoring.
modal deploy --profile "$MODAL_PROFILE" --env "$MODAL_ENVIRONMENT" modal_app.py

# Optional: one scheduled CPU check each hour.
TRANSLATION_OPERATIONS_MONITOR_SCHEDULE=hourly modal deploy --profile "$MODAL_PROFILE" --env "$MODAL_ENVIRONMENT" modal_app.py

modal app list --profile "$MODAL_PROFILE" --env "$MODAL_ENVIRONMENT"
```

Accepted values are `off` (default) and `hourly`; other values fail
on import/deploy. To disable an existing hourly schedule, redeploy with
`TRANSLATION_OPERATIONS_MONITOR_SCHEDULE=off` and verify the function's
**Details** page in Modal. Pushing source code alone does not update
an existing deployment. The function remains available for manual
**Run now**. Scheduled CPU runs and PostgreSQL queries can be billable
even when all GPU workers have scaled to zero.

The App contains:
- `translation_inference_fastapi_cpu_gateway` — FastAPI, CPU only.
- `translation_inference_cpu_mock_job_worker` — optional mock fallback.
- `HyMT2L40SWorker`, `IndexTranslateL40SWorker`,
  `Gemma4L40SWorker`, `Qwen35L40SWorker` — one GPU each, scale-to-zero.
- `translation_inference_cpu_operations_safety_monitor` — optional
  CPU-only PostgreSQL checker, with scheduling disabled by default.

Deploying the code does not necessarily switch an existing API Secret
to GPU mode. The active dispatcher is controlled by
`TRANSLATION_DISPATCHER_MODE`. `modal-gpu` enables real translation;
`modal-cpu-mock` returns explicitly simulated results.

## Validate the authenticated API

Set your own HTTPS gateway URL from the Modal deployment output:

```bash
export TRANSLATION_GATEWAY_BASE_URL="https://YOUR_GATEWAY.modal.run"
curl -fsS "$TRANSLATION_GATEWAY_BASE_URL/health"

# Load TRANSLATION_API_BEARER_TOKEN privately before running this command.
# Authentication is required for /v1 endpoints:
curl -fsS "$TRANSLATION_GATEWAY_BASE_URL/v1/models" \
  -H "Authorization: Bearer $TRANSLATION_API_BEARER_TOKEN"
```

These checks confirm gateway health and authentication only. In the
initial `modal-cpu-mock` mode, they do **not** establish GPU readiness.
Complete the explicit mode switch below **before** GPU smoke testing.

## Safe single-key mode switching and rollback

The helper uses Modal SDK `Secret.update()` to change **only**
`TRANSLATION_DISPATCHER_MODE` and preserve every other existing Secret
variable. It requires Modal Python SDK **1.3.5 or newer**, a working
authenticated gateway and a matching profile/environment. The default is
read-only. `--apply` is operator-controlled and performs a **recreate
rollover that can interrupt in-flight work**. Choose a maintenance window,
review active jobs and cloud budget, and do not retry uncertain GPU jobs.

```bash
# No mutation:
PYTHONPATH=src python scripts/deployment/set_dispatch_mode.py --to-mock

# Operator-approved, potentially disruptive mode switch:
# PYTHONPATH=src python scripts/deployment/set_dispatch_mode.py \
#   --to-mock --apply --profile YOUR_MODAL_PROFILE \
#   --environment YOUR_MODAL_ENVIRONMENT \
#   --base-url https://YOUR_GATEWAY.modal.run
```

To enable real GPU inference, first verify mock mode, model weights,
resource capacity and approved budget, then explicitly use `--to-gpu`.
On failure the helper **attempts** to restore the old mode and roll over
again, but cannot guarantee recovery if the cloud API is unavailable.
Always confirm gateway health and reconcile uncertain in-flight jobs.
It does not deploy new source code or replace the entire Secret.

## Enable GPU mode and run an opt-in smoke test

For a **new installation**, first verify all four weight Volumes, model
licenses, account GPU access, cloud budget and absence of in-flight jobs.
A mode change updates the existing Secret and recreates containers; it can
interrupt running jobs. Confirm the gateway is in mock mode before the
switch. The commands below target **your own** Modal profile/environment
and HTTPS gateway; the Bearer token must be loaded privately.

```bash
# 1. Safe preview (no cloud mutation):
PYTHONPATH=src python scripts/deployment/set_dispatch_mode.py --to-gpu \
  --profile "$MODAL_PROFILE" --environment "$MODAL_ENVIRONMENT" \
  --base-url "$TRANSLATION_GATEWAY_BASE_URL"

# 2. ONLY with operator approval (may interrupt running jobs):
PYTHONPATH=src python scripts/deployment/set_dispatch_mode.py --to-gpu --apply \
  --profile "$MODAL_PROFILE" --environment "$MODAL_ENVIRONMENT" \
  --base-url "$TRANSLATION_GATEWAY_BASE_URL"

# 3. Verify inference_enabled=true and phase="gpu" in the response:
curl -fsS "$TRANSLATION_GATEWAY_BASE_URL/health"

# 4. Explicit, billable single-model smoke:
PYTHONPATH=src python scripts/api/smoke_gpu.py --run

# Optional, billable four-model integration smoke:
# PYTHONPATH=src python scripts/api/smoke_gpu.py --run --all-models
```

Do not run step 4 until the helper has confirmed GPU mode and step 3
shows both required fields. The smoke script checks these conditions
again. It writes a sanitized summary to a private, restricted temporary
directory **outside this Git repository**, without persisting live job IDs
to tracked `reports/`; review any output before public sharing.

A submitted job returns HTTP 202 with `job_id` and `status_url`; poll
with the same token. `is_mock_result=false` indicates nonmock execution,
**not a guarantee of translation quality**. For rollback to mock mode,
use the preceding section's `--to-mock` instructions.

## After deployment

If setup fails, use the last successful stage to narrow down the problem:

| Failure | Check before continuing |
|---|---|
| Profile or environment not found | CLI login, selected workspace and environment creation |
| Secret or Volume not found | Exact resource names and the same environment on every command |
| Weight download or SHA256 failure | Pinned upstream artifact, network and staging logs; do not edit hashes to bypass failure |
| Database connection or migration failure | Matching database URLs, TLS, network access and role permissions |
| HTTP 401 | Client token matches the deployed API Secret |
| HTTP 429 after invalid Bearer credentials | Local three-strike lockout; respect `Retry-After`, then review [gateway security](security.md) |
| Health remains `mock-only` | Complete the mode switch and verify its result before GPU smoke |
| GPU job fails or becomes uncertain | Inspect Modal logs and persisted job state; preserve UUID/key and reconcile before retrying |

The deployment's HTTPS gateway URL is printed by `modal deploy`. Use that
URL, not an example URL or a separate worker endpoint. The first image build
and model cold start can take time; GPU readiness has not been independently
confirmed merely because deployment or `/health` succeeded.

Run the [operations checks](operations.md), inspect [reliability evidence](reliability.md),
and verify the upstream [model license declarations](../MODEL_LICENSE.md).
No credential, license or model weight is generated by this runbook.
