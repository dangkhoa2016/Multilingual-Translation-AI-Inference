# Development and review

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](development.vi.md)

The project is a Python application with FastAPI, SQLAlchemy,
PostgreSQL and Modal. You can test the API and job state machine
**without a GPU or a cloud account**.

## Run locally

```bash
git clone https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference.git
cd Multilingual-Translation-AI-Inference
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env

# Replace the sample Bearer token with a random local-only secret.
set -a; source .env; set +a
python scripts/local_demo.py
```

The example defaults to SQLite and mock translation. Mock responses
are labelled as such; they are not proof of GPU inference.

## Verification commands

```bash
python -m pytest -q
python -m ruff check .
python -m compileall -q src modal_app.py scripts tests
python scripts/audit_public_repository.py
```

CI runs CPU-only tests and documentation checks on GitHub.
Do not put actual tokens, database URLs or licensed model weights
in fixtures, workflow logs or pull requests.

## API contract

- `GET /health`: process health (public; not a deep readiness probe).
- `GET /v1/models`: authenticated model catalog.
- `POST /v1/jobs/translations`: one model, HTTP 202.
- `POST /v1/jobs/benchmarks`: 1–4 model keys, HTTP 202.
- `GET /v1/jobs/{job_id}`: authenticated polling.
- `POST /v1/jobs/{job_id}/runs/{run_id}/retry`: explicit retry for
  confirmed failure only, subject to quotas.

Example request body:

```json
{
  "model": "hy_mt2_30b",
  "source_language": "en",
  "target_language": "vi",
  "text": "The little fox crossed the bridge at sunrise.",
  "options": {"preserve_formatting": true}
}
```

Include `Authorization: Bearer YOUR_TOKEN`; an
`Idempotency-Key` is recommended to avoid duplicate jobs. The
content must contain 1–1,000 nonblank Unicode code points, with
different source and target languages among `en`, `vi`, `de`,
`ja`, `ko`.

## Contributing code and documentation

Keep model-specific inference decisions behind the GPU runtime boundary.
Preserve the PostgreSQL transaction and claim-token semantics.
For each user-facing Markdown document, supply matching English and
Vietnamese versions with working language-switch links. Prefer
small, focused source commits and explain behavior changes in tests.

See [contribution guide](../.github/CONTRIBUTING.md),
[architecture](architecture.md) and [security](../.github/SECURITY.md).
