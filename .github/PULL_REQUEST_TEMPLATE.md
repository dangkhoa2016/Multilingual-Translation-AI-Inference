# Pull request / Yêu cầu hợp nhất

> 🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](PULL_REQUEST_TEMPLATE.vi.md)

## Summary / Tóm tắt

<!-- English overview. Vietnamese may be added below. -->

## Motivation and scope

<!-- Why this is needed, and what it intentionally does not change. -->

## Verification

- [ ] Unit tests passed (`python -m pytest -q`)
- [ ] Ruff passed (`python -m ruff check .`)
- [ ] Publication safety tests passed (`python -m pytest -q tests/security/test_publication_safety.py`)
- [ ] Matching English/Vietnamese documentation updated
- [ ] No tokens, model weights, personal data or secret paths committed
- [ ] Upstream copyright and licenses preserved

## Risk and rollback

<!-- Include migrations, API compatibility, cost and rollback details. -->

> 🌐 [Tiếng Việt](PULL_REQUEST_TEMPLATE.vi.md)
