# Contributing

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](CONTRIBUTING.vi.md)

Thank you for contributing to Multilingual Translation AI Inference.

## Before proposing a change

1. Search existing issues and read [architecture](../docs/architecture.md),
   [deployment](../docs/deployment.md), and [model licensing](../MODEL_LICENSE.md).
2. Discuss changes to the API contract, model sources, weight handling or billing
   controls before implementing them.
3. Keep credentials, third-party model weights and personally identifiable
   translation inputs **out of commits and issue attachments**.
4. Match the existing English/Vietnamese documentation layout. Any new
   user-facing Markdown guide must have a matching `.vi.md` or English partner,
   with working language-switch links.

## Local validation

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
python -m ruff check .
python scripts/audit_public_repository.py
```

CPU-only tests are sufficient for ordinary pull requests. Do not run live
Modal GPU tests without an agreed cost envelope and access approval.

## Pull request checklist

- A focused, descriptive Conventional Commit message (e.g.
  `fix(api): reject invalid translation payloads`).
- Prefer small, reviewable source changes; aim for **at most ~600 changed
  code lines per commit**. Long bilingual documentation changes can be
  larger when necessary.
- Add or update unit tests, document the behavior, and explain any
  breaking API/database changes.
- Do not invent historical commit timestamps, rewrite another person's
  authorship, or claim checks you have not run.
- Preserve upstream attribution and verify third-party license constraints.

Use the [pull request template](PULL_REQUEST_TEMPLATE.md).
