"""CPU-only checks for public README, bilingual docs, licenses and audit rules."""
from pathlib import Path

from scripts import audit_public_repository as audit_module


def test_full_public_repository_audit_passes():
    assert audit_module.audit() == []


def test_all_user_facing_markdown_has_partner_and_language_switch():
    docs = audit_module.all_public_markdown()
    assert len(docs) >= 40
    for doc in docs:
        counterpart = audit_module.counterpart(doc)
        assert counterpart.is_file()
        head = "\n".join(doc.read_text(encoding="utf-8").splitlines()[:6])
        assert counterpart.name in head
        assert "Language / Ngôn ngữ:" in head


def test_no_fixed_status_dates_or_internal_development_codes():
    for doc in audit_module.all_public_markdown():
        body = doc.read_text(encoding="utf-8")
        assert not audit_module.INTERNAL_CODE.search(body), doc
        assert not audit_module.FIXED_STATUS_DATE.search(body), doc
        assert all(not p.search(body) for p in audit_module.SENSITIVE_PATTERNS)


def test_license_attribution_and_model_separation():
    root = Path(__file__).resolve().parents[1]
    license_text = (root / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in license_text
    assert "Đăng Khoa <i.am@dangkhoa.dev>" in license_text
    notice = (root / "MODEL_LICENSE.md").read_text(encoding="utf-8")
    assert "MIT license" in notice
    assert "not the" in notice
    for model in ("Hy-MT2", "Index-Translate", "Gemma 4", "Qwen3.5"):
        assert model in notice
    assert "Apache License" in (
        root / "THIRD_PARTY_LICENSES/Apache-2.0.txt"
    ).read_text(encoding="utf-8")


def test_version_author_and_package_metadata_are_in_sync():
    import tomllib

    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["project"]["version"] == (root / "VERSION").read_text().strip()
    assert config["project"]["authors"] == [{
        "name": "Đăng Khoa", "email": "i.am@dangkhoa.dev",
    }]
    assert config["project"]["license"] == "MIT"
    assert not any("License ::" in c for c in config["project"].get("classifiers", []))
    assert (root / "CITATION.cff").exists()


def test_public_readme_has_functional_bilingual_badges():
    root = Path(__file__).resolve().parents[1]
    for name in ("README.md", "README.vi.md"):
        text = (root / name).read_text(encoding="utf-8")
        assert "python-validation.yml/badge.svg" in text
        assert "repository-audit.yml/badge.svg" in text
        assert "LICENSE" in text
        assert "MODEL_LICENSE" in text
        assert "docs/roadmap" in text
        assert not audit_module.INTERNAL_CODE.search(text)
