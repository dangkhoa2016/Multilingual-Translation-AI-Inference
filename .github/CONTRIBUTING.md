# Contributing

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](CONTRIBUTING.vi.md)

Contributions are welcome, whether you are trying the project for the first
time or extending a deployment. You do not need a GPU or cloud account to
improve the documentation, examples or CPU-tested application code.

## Ways to contribute

- Report a reproducible bug or clarify an installation step.
- Improve English/Vietnamese guides and notebook instructions.
- Share a small API integration example.
- Discuss model backends, deployment options or translation evaluation in
  [GitHub Issues](https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference/issues).

For usage questions, see [support](SUPPORT.md). Report vulnerabilities through
the [security policy](SECURITY.md).

## Before proposing a change

1. Search existing issues for related work. The [architecture](../docs/architecture.md),
   [deployment](../docs/deployment.md) and [model licensing](../MODEL_LICENSE.md)
   guides explain the relevant parts of the project.
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
python -m pytest -q tests/security/test_publication_safety.py
```

CPU-only tests are sufficient for ordinary pull requests. Do not run live
Modal GPU tests without an agreed cost envelope and access approval.

## Pull request checklist

- A focused, descriptive Conventional Commit message (e.g.
  `fix(api): reject invalid translation payloads`).
- Keep each pull request focused on a clear problem or improvement.
- Add or update unit tests, document the behavior, and explain any
  breaking API/database changes.
- Describe the checks you ran and any limitations a reviewer should know.
- Preserve upstream attribution and verify third-party license constraints.

Use the [pull request template](PULL_REQUEST_TEMPLATE.md).
