# Deployment — Modal GPU inference and PostgreSQL

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](deployment.vi.md)

This runbook deploys one **CPU API gateway** and four independent NVIDIA L40S
model workers into one Modal App. It assumes you control your Modal
workspace and PostgreSQL database. GPU operations are billable.

## Requirements

- Python 3.12 with `pip`, and your own Modal account; CLI authentication is covered below.
- A reachable PostgreSQL database, preferably with TLS and a pooled
  runtime connection. Use a direct URL for Alembic migrations.
- Two named Modal Secrets for API/database; a separate HF_TOKEN Secret is used only for GGUF staging.
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

## PostgreSQL URLs: runtime and migrations

The API gateway and workers use `TRANSLATION_INFERENCE_DATABASE_URL`, whereas Alembic uses `TRANSLATION_INFERENCE_MIGRATION_DATABASE_URL` for schema updates. Both must refer to **the same PostgreSQL database**. The local SQLite example is not a deployment URL.

| Variable | Used by | Connection |
|---|---|---|
| `TRANSLATION_INFERENCE_DATABASE_URL` | CPU gateway and workers, via the Modal PostgreSQL Secret | Pooled PostgreSQL endpoint if offered; direct also works within connection limits |
| `TRANSLATION_INFERENCE_MIGRATION_DATABASE_URL` | Alembic on the machine running schema upgrades | **Direct PostgreSQL endpoint**, not a transaction pooler; stored in the private local `.env` |

If your provider offers **both pooled and direct URLs**, use the pooled URL for runtime and the direct URL for migration. If your provider offers **only a direct URL**, you may use **the same direct URL for both variables**, as long as both the migration machine and Modal can connect. Hosts, ports and credentials may differ, but the database/schema must be the same. Follow the provider's TLS settings and percent-encode special characters in URL credentials.

Ensure the migration account can create or change the schema and the runtime account has the application permissions it needs. Your local migration machine must reach the direct endpoint; Modal containers must reach the runtime endpoint. Alembic code falls back to the runtime URL when the migration variable is absent; nevertheless, **this deployment guide explicitly configures a direct migration URL**, so migrations are not inadvertently sent through a pooler. After loading the private `.env`, follow [Prepare the database schema](#prepare-the-database-schema).

**Only the runtime URL goes into the Modal PostgreSQL Secret.** Do not put the migration URL in the Modal Secret or notebook. The [local environment template](../.env.example) intentionally keeps SQLite for local use and includes a **commented** direct-migration URL that you can fill in privately for PostgreSQL deployment.

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

**Recommended: provision both Secrets from one private `.env`.**
No JSON files are required. Copy `.env.example` to `.env` **once**, replace all
placeholders, uncomment the direct migration URL and use `chmod 600 .env`.
Keep this file out of Git. Preview first, then explicitly create resources:

```bash
python scripts/deployment/create_modal_secrets.py --profile "$MODAL_PROFILE" --environment "$MODAL_ENVIRONMENT"
python scripts/deployment/create_modal_secrets.py --profile "$MODAL_PROFILE" --environment "$MODAL_ENVIRONMENT" --apply
```

The script sends **only** the runtime PostgreSQL URL to the database Secret
and the Bearer token plus approved optional quotas to the API Secret.
The migration URL stays local. The initial dispatcher is always
`modal-cpu-mock`, even if local `.env` uses `inline-mock`.
The Modal SDK refuses to replace existing Secrets. If one Secret is created
and the next operation fails, inspect Modal before retrying; the two
creations are not a single transaction. The script does not migrate the
database, deploy the App, stage weights, or start GPU workers.

**Alternative: manual JSON provisioning (fully supported).**
Use the two private JSON files and the original commands below instead.
Protect each file with `0600` permissions, keep it outside Git, and
never combine these setup paths on an existing deployment.

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

## Authenticate Hugging Face downloads (CPU staging only)

GGUF staging uses a **third, independent Modal Secret** named
`multilingual-translation-ai-inference-huggingface-download`, containing
only `HF_TOKEN`. Use a Hugging Face read-only or scoped token and accept
any applicable model access terms. Authentication can improve access
limits; it does not guarantee faster network throughput. The staging
image already enables high-performance `hf_xet` transfers.

Put `HF_TOKEN=hf_your_private_read_token` into your existing private
`.env` file (or another untracked dotenv file) and run `chmod 600 .env`.
Do not paste tokens into shell arguments, source files, notebooks or logs.
Only `HF_TOKEN` is sent to the new Secret, never PostgreSQL credentials
or the translation API Bearer token.

```bash
# Read-only preview, without reading the token:
python scripts/deployment/configure_huggingface_access.py \
  --profile "$MODAL_PROFILE" --environment "$MODAL_ENVIRONMENT"

# Explicitly create the third Secret; refuses to replace an existing one:
python scripts/deployment/configure_huggingface_access.py \
  --profile "$MODAL_PROFILE" --environment "$MODAL_ENVIRONMENT" \
  --env-file .env --apply
modal secret list --profile "$MODAL_PROFILE" --env "$MODAL_ENVIRONMENT"
```

Instead of `--env-file`, the helper accepts a private `HF_TOKEN`
environment variable or a hidden interactive terminal prompt. For
noninteractive notebooks, use `--env-file`. Keep the two API/PostgreSQL
Secrets unchanged. This third Secret is attached **only to the four CPU
staging functions**, never the gateway or GPU workers. Creation does not
download weights, deploy the App or run GPUs.

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
modal profile current --profile "$MODAL_PROFILE"
modal volume list --profile "$MODAL_PROFILE" --env "$MODAL_ENVIRONMENT"

# NEW INSTALLATIONS ONLY: create four empty Volumes in the selected environment.
CONFIRM_TRANSLATION_GPU_VOLUME_CREATION=YES bash scripts/deployment/create_volumes.sh

# Preview a single model; no transfer without --stage:
modal run --profile "$MODAL_PROFILE" --env "$MODAL_ENVIRONMENT" \
  scripts/models/stage_model_weights.py --model hy_mt2_30b

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
    subprocess.run(["modal", "volume", "ls", "--profile", os.environ["MODAL_PROFILE"],
                    "--env", os.environ["MODAL_ENVIRONMENT"],
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

Expect revision `0006_queued_recovery_intent` at head. Resolve migration errors
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

GPU workers default to `min_containers=0` and `scaledown_window=60` seconds to reduce cold starts between notebook requests. Idle GPU workers may incur charges before scaling to zero. Tune the window to your operating requirements.

The App contains:
- `translation_inference_fastapi_cpu_gateway` — FastAPI, CPU only.
- `translation_inference_cpu_mock_job_worker` — optional mock fallback.
- `HyMT2L40SWorker`, `IndexTranslateL40SWorker`,
  `Gemma4L40SWorker`, `Qwen35L40SWorker` — one GPU each, scale-to-zero.
- `translation_inference_cpu_operations_safety_monitor` — optional
  CPU-only PostgreSQL checker, with scheduling disabled by default.
- `translation_inference_cpu_queued_recovery` — optional CPU coordinator;
  no schedule by default and no GPU dispatch without separate permission.

Deploying the code does not necessarily switch an existing API Secret
to GPU mode. The active dispatcher is controlled by
`TRANSLATION_DISPATCHER_MODE`. `modal-gpu` enables real translation;
`modal-cpu-mock` returns explicitly simulated results.

## Optional CPU queued-run recovery

The additional CPU-only `translation_inference_cpu_queued_recovery` function
has **no schedule by default**. After database migration, an operator may
enable hourly recovery of definitively `queued` runs when deploying:

```bash
# Only when an operator wants automated sweeps; still CPU mock by default.
TRANSLATION_QUEUED_RECOVERY_SCHEDULE=hourly modal deploy --profile "$MODAL_PROFILE" --env "$MODAL_ENVIRONMENT" modal_app.py
```

Do not enable this in place of the default deployment without approval:
CPU/DB work has a cost. `modal-gpu` queued recovery is separately
disabled until the authentication Secret contains
`TRANSLATION_QUEUED_RECOVERY_ALLOW_GPU=YES`, requiring an explicit
budget-aware operator change. An authorized GPU recovery sweep can start
real paid workers; the default GPU setting is **NO**. A stored dispatch
intent prevents mock jobs from being promoted to GPU after mode changes;
legacy jobs with unknown intent remain untouched. See
[operations](operations.md) for safety and manual reconciliation.

## Validate the authenticated API

The gateway root `GET /` serves a static, responsive English welcome page;
`GET /?lang=vi` switches to Vietnamese. Both locales link to this deployment
guide and `/health`. It does not require a token, access PostgreSQL, download
models or start GPU inference. This is **not** a public translation
website: job submission/retrieval under `/v1/` remains Bearer-protected.
The public, rate-limited `GET /v1/models` catalog is the sole exception;
automatic Swagger/OpenAPI documentation stays disabled.

Set your own HTTPS gateway URL from the Modal deployment output:

```bash
export TRANSLATION_GATEWAY_BASE_URL="https://YOUR_GATEWAY.modal.run"
curl -fsS "$TRANSLATION_GATEWAY_BASE_URL/health"

# Public, rate-limited model catalog (no Bearer token required):
curl -fsS "$TRANSLATION_GATEWAY_BASE_URL/v1/models"

# Job creation/retrieval still requires Bearer auth; load the token privately.
```

These checks confirm gateway health and public catalog metadata only; they do not validate client credentials. In the
initial `modal-cpu-mock` mode, they do **not** establish GPU readiness.
Complete the explicit mode switch below **before** GPU smoke testing.

For an existing deployment, change `TRANSLATION_API_BEARER_TOKEN` using the [safe token rotation guide](token-rotation.md). This is separate from changing dispatcher mode, and does not require restaging GGUF weights.

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
