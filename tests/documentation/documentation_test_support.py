"""Publication-stage checks shared by bilingual README tests."""
import subprocess

import pytest

README_NAMES = ("README.md", "README.vi.md")


def _readmes_ever_published(root):
    # An exported or shallow tree cannot prove publication has never happened.
    if not (root / ".git").exists():
        return None
    try:
        shallow = subprocess.run(
            ["git", "rev-parse", "--is-shallow-repository"],
            cwd=root, text=True, capture_output=True, check=False,
        )
        if shallow.returncode != 0 or shallow.stdout.strip() != "false":
            return None
        result = subprocess.run(
            ["git", "log", "--full-history", "-1", "--format=%H", "HEAD", "--", *README_NAMES],
            cwd=root, text=True, capture_output=True, check=False,
        )
    except OSError:
        return None
    return bool(result.stdout.strip()) if result.returncode == 0 else None


def require_published_readmes(root):
    paths = tuple(root / name for name in README_NAMES)
    missing = [path.name for path in paths if not path.is_file()]
    if all(not path.exists() for path in paths) and _readmes_ever_published(root) is False:
        pytest.skip("Bilingual READMEs are not introduced in this Git revision's history.")
    assert not missing, "Missing published README files: " + ", ".join(missing)
    return paths
