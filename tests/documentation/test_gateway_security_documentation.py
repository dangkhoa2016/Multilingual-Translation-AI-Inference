"""Public-facing documentation must match the CPU authentication gateway contract."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_bilingual_security_guides_cover_gateway_contract():
    for filename in ("security.md", "security.vi.md"):
        guide = (ROOT / "docs" / filename).read_text(encoding="utf-8")
        for item in (
            "TRANSLATION_AUTH_FAILURE_LIMIT",
            "TRANSLATION_AUTH_FAILURE_WINDOW_SECONDS",
            "TRANSLATION_AUTH_LOCKOUT_SECONDS",
            "TRANSLATION_AUTH_MAX_TRACKED_CLIENTS",
            "TRANSLATION_MAX_API_BODY_BYTES",
            "Retry-After",
            "429",
            "X-Forwarded-For",
            "runtime_status",
            "dispatch_enabled",
        ):
            assert item in guide
        assert "GPU" in guide


def test_readmes_link_to_bilingual_security_guides(published_readmes):
    assert "docs/security.md" in (ROOT / "README.md").read_text()
    assert "docs/security.vi.md" in (ROOT / "README.vi.md").read_text()
