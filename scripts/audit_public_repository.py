"""Offline public repository review: bilingual docs, licensing, references and metadata.

No network/API/Modal access. Safe to execute in GitHub Actions and local CI.
Project docs describe current behavior without publishing internal task
codes, account-specific endpoints or timestamped status labels.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]

REQUIRED = [
    "README.md", "README.vi.md", "LICENSE",
    "LICENSE-NOTES.md", "LICENSE-NOTES.vi.md",
    "MODEL_LICENSE.md", "MODEL_LICENSE.vi.md",
    "NOTICE.md", "NOTICE.vi.md",
    "CHANGELOG.md", "CHANGELOG.vi.md",
    "CITATION.cff", "VERSION", "pyproject.toml",
    "THIRD_PARTY_LICENSES/Apache-2.0.txt",
    ".github/CODEOWNERS", ".github/dependabot.yml",
    ".github/SECURITY.md", ".github/SECURITY.vi.md",
    ".github/CONTRIBUTING.md", ".github/CONTRIBUTING.vi.md",
    ".github/SUPPORT.md", ".github/SUPPORT.vi.md",
    ".github/CODE_OF_CONDUCT.md", ".github/CODE_OF_CONDUCT.vi.md",
    ".github/PULL_REQUEST_TEMPLATE.md", ".github/PULL_REQUEST_TEMPLATE.vi.md",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".github/workflows/python-validation.yml",
    ".github/workflows/repository-audit.yml",
    "docs/architecture.md", "docs/architecture.vi.md",
    "docs/configuration.md", "docs/configuration.vi.md",
    "docs/models.md", "docs/models.vi.md",
    "docs/deployment.md", "docs/deployment.vi.md",
    "docs/operations.md", "docs/operations.vi.md",
    "docs/reliability.md", "docs/reliability.vi.md",
    "docs/benchmarking.md", "docs/benchmarking.vi.md",
    "docs/development.md", "docs/development.vi.md",
    "docs/roadmap.md", "docs/roadmap.vi.md",
    "docs/design-decisions.md", "docs/design-decisions.vi.md",
]

LINK = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")
INTERNAL_CODE = re.compile(r"\b(?:P|M|R|Q)[1-9]\b|\bphase\s*\d+\b", re.IGNORECASE)
FIXED_STATUS_DATE = re.compile(r"\b20\d\d-\d\d-\d\d\b")
PRIVATE_ACCOUNTS = ("bsmith888", "Dilara Ha", "60597850+x8o8x")
MODEL_IDS = {"hy_mt2_30b", "index_35b", "gemma4_31b_it", "qwen35_35b"}


def all_public_markdown():
    """Skip raw generated reports; keep current human-facing documents."""
    docs = [*ROOT.glob("*.md"), *ROOT.glob("docs/**/*.md"),
            *ROOT.glob(".github/**/*.md")]
    return sorted(p for p in docs if p.is_file())


def counterpart(path: Path) -> Path:
    if path.name.endswith(".vi.md"):
        return path.with_name(path.name.replace(".vi.md", ".md"))
    return path.with_name(path.stem + ".vi.md")


def audit() -> list[str]:
    errors: list[str] = []
    for name in REQUIRED:
        if not (ROOT / name).is_file():
            errors.append("Required path missing: " + name)
    docs = all_public_markdown()
    for path in docs:
        relative = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        partner = counterpart(path)
        if not partner.is_file():
            errors.append(relative + ": bilingual counterpart missing: " + partner.name)
        if not any("Language / Ngôn ngữ:" in line for line in text.splitlines()[:6]):
            errors.append(relative + ": missing header language switch")
        if partner.name not in "\n".join(text.splitlines()[:6]):
            errors.append(relative + ": language switch target missing")
        for regex, label in (
            (INTERNAL_CODE, "internal milestone code"),
            (FIXED_STATUS_DATE, "hard-coded ISO date in public guide"),
        ):
            match = regex.search(text)
            if match:
                errors.append(f"{relative}: {label}: {match.group(0)}")
        for marker in PRIVATE_ACCOUNTS:
            if marker.lower() in text.lower():
                errors.append(relative + ": private/account-specific attribution leaked")
        for dest in LINK.findall(text):
            link = dest.strip().split(" ", 1)[0].strip("<>")
            parsed = urlsplit(link)
            if parsed.scheme or link.startswith("#") or link.startswith("/"):
                continue
            local = (path.parent / unquote(parsed.path)).resolve()
            try:
                local.relative_to(ROOT.resolve())
            except ValueError:
                errors.append(relative + f": link escapes repository: {link}")
                continue
            if not local.exists():
                errors.append(relative + f": broken relative link: {link}")
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8") if (ROOT / "LICENSE").exists() else ""
    for term in ("MIT License", "Đăng Khoa <i.am@dangkhoa.dev>"):
        if term not in license_text:
            errors.append("MIT license missing identity or text: " + term)
    model_license = (ROOT / "MODEL_LICENSE.md").read_text(encoding="utf-8") if (ROOT / "MODEL_LICENSE.md").exists() else ""
    if not all(item in model_license for item in (
        "Hy-MT2", "Index-Translate", "Gemma 4", "Qwen3.5", "Apache-2.0",
    )):
        errors.append("Model license register does not cover all four third-party models")
    manifest = ROOT / "models/four_l40s_workers_q8_0_manifest.json"
    if not manifest.is_file():
        errors.append("Model manifest missing")
    else:
        import json
        try:
            models = json.loads(manifest.read_text(encoding="utf-8"))["models"]
            if set(models) != MODEL_IDS:
                errors.append("Model manifest no longer enumerates four backends")
            for key, row in models.items():
                if (row["license_on_model_cards"] != "apache-2.0"
                        or len(row["gguf_lfs_sha256"]) != 64
                        or len(row["gguf_revision"]) != 40):
                    errors.append(key + ": invalid locked license/source provenance")
        except (ValueError, KeyError, TypeError):
            errors.append("Malformed model manifest")
    if (ROOT / ".env").is_file() and ".env" not in (ROOT / ".gitignore").read_text():
        errors.append("Local .env not ignored")
    return errors


def main() -> int:
    issues = audit()
    if issues:
        print(f"PUBLIC REPOSITORY AUDIT FAILED: {len(issues)} findings", file=sys.stderr)
        for issue in issues:
            print(" - " + issue, file=sys.stderr)
        return 1
    print(f"PUBLIC REPOSITORY AUDIT PASS: {len(all_public_markdown())} bilingual guides,"
          f" {len(REQUIRED)} required assets, model license provenance and local links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
