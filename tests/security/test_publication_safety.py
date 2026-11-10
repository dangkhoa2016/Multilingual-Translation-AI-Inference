"""Focused offline publication-safety checks; not a repository-style audit."""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK = ROOT / "notebooks/translation_api_demo.ipynb"
SENSITIVE_FIELD_NAMES = {
    "job_id", "job_ids", "test_job_id", "request_id", "trace_id",
    "workspace", "workspace_id", "device_id", "api_key", "api_token",
    "access_token", "authorization", "database_url", "input_text",
    "request_text", "password", "metered_cost_usd", "billed_cost_usd",
}
PRIVATE_VALUE = re.compile(
    r"(?i)(?:"
    r"\b(?:ghp_|gho_|ghs_|github_pat_|glpat-)[a-z0-9_-]{12,}"
    r"|\bsk-[a-z0-9_-]{30,}"
    r"|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    r"|[a-z0-9-]+\.(?:modal\.run|neon\.tech|onrender\.com)"
    r"|\b[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\b"
    r"|\b(?:agent-[a-f0-9]{32}|GPU-[a-f0-9]{8}-[a-f0-9-]{20,})\b"
    r"|[a-z0-9_.+-]+@[a-z0-9.-]+\.[a-z]{2,}"
    r")"
)
NOTEBOOK_PRIVATE_VALUE = re.compile(
    r"(?i)(?:"
    r"\b(?:ghp_|gho_|ghs_|github_pat_|glpat-)[a-z0-9_-]{12,}"
    r"|\bsk-[a-z0-9_-]{30,}"
    r"|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    r"|[a-z0-9-]+\.(?:modal\.run|neon\.tech|onrender\.com)"
    r")"
)
NOTEBOOK_CREDENTIAL = re.compile(
    r"""(?im)^\s*(?:API_TOKEN|TRANSLATION_API_BEARER_TOKEN)\s*=\s*['"][^'"]{12,}['"]"""
)
NOTEBOOK_DEFAULTS = (
    'DEMO_MODE = "offline"',
)



def notebook_problems(notebook):
    """Return actionable unsafe notebook states without external API calls."""
    problems = []
    if not isinstance(notebook, dict) or notebook.get("nbformat") != 4:
        return ["invalid notebook version"]
    cells = notebook.get("cells")
    if not isinstance(cells, list):
        return ["invalid notebook cell list"]
    if notebook.get("metadata", {}).get("widgets"):
        problems.append("saved widget state")
    code = []
    for cell in cells:
        if cell.get("attachments"):
            problems.append("saved attachments")
        source = cell.get("source", "")
        if isinstance(source, list):
            if not all(isinstance(line, str) for line in source):
                problems.append("invalid cell source")
                continue
            source = "".join(source)
        if not isinstance(source, str):
            problems.append("invalid cell source")
            continue
        # Search for actual credential-shaped values, not mere variable names.
        if NOTEBOOK_CREDENTIAL.search(source) or NOTEBOOK_PRIVATE_VALUE.search(source):
            problems.append("embedded credential or private identifier")
        if cell.get("cell_type") == "code":
            code.append(source)
            if cell.get("execution_count") is not None or cell.get("outputs"):
                problems.append("saved execution output")
    if not code:
        problems.append("missing code cells")
    all_code = "\n".join(code)
    for setting in NOTEBOOK_DEFAULTS:
        if setting not in all_code:
            problems.append("missing offline default: " + setting)
    return problems


def report_problems(report):
    problems = []
    if not isinstance(report, dict) or report.get("sanitized_for_publication") is not True:
        problems.append("missing publication sanitization approval")

    def visit(value, path):
        if isinstance(value, str):
            if PRIVATE_VALUE.search(value):
                problems.append("private runtime value: " + path)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")
        elif isinstance(value, dict):
            for key, item in value.items():
                if key.casefold() in SENSITIVE_FIELD_NAMES:
                    problems.append("private runtime field: " + path + "." + key)
                if key == "gpu_uuid" and (
                    not isinstance(item, str) or not item.startswith("GPU-REDACTED-")
                ):
                    problems.append("unredacted GPU identifier")
                visit(item, path + "." + key)
    visit(report, "report")
    return problems


def test_notebook_template_has_no_saved_output_secrets_or_live_defaults():
    assert notebook_problems(json.loads(NOTEBOOK.read_text(encoding="utf-8"))) == []


@pytest.mark.parametrize("field, value", [
    ("outputs", [{"output_type": "stream", "text": "private"}]),
    ("execution_count", 1),
])
def test_notebook_rejects_saved_execution_state(field, value):
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    target = next(cell for cell in notebook["cells"] if cell["cell_type"] == "code")
    target[field] = value
    assert "saved execution output" in notebook_problems(notebook)


def test_notebook_rejects_inline_token_and_paid_default():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    cell = next(cell for cell in notebook["cells"] if cell["cell_type"] == "code")
    cell["source"] = ["TRANSLATION_API_BEARER_TOKEN = 'synthetic-long-bearer-token'\n"]
    assert "embedded credential or private identifier" in notebook_problems(notebook)
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    for cell in notebook["cells"]:
        if cell.get("cell_type") == "code":
            src = cell["source"]
            text = "".join(src) if isinstance(src, list) else src
            cell["source"] = text.replace('DEMO_MODE = "offline"', 'DEMO_MODE = "gpu"')
    assert 'missing offline default: DEMO_MODE = "offline"' in notebook_problems(notebook)


def test_public_json_reports_are_sanitized_recursively():
    reports = sorted((ROOT / "reports").glob("*.json"))
    assert reports, "Expected published evidence reports"
    for path in reports:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert report_problems(data) == [], (path.name, report_problems(data))


def test_report_rejects_nested_identifiers_and_secrets():
    for unsafe in (
        {"sanitized_for_publication": True, "runs": [{"job_id": "synthetic"}]},
        {"sanitized_for_publication": True, "runs": [{"result": "https://private.modal.run"}]},
        {"sanitized_for_publication": True, "gpu_uuid": "GPU-123-456"},
        {"sanitized_for_publication": False},
    ):
        assert report_problems(unsafe)


def test_public_docs_and_notebooks_have_no_literal_access_tokens():
    # Lightweight credential check: documentation copy should not embed active-style tokens.
    files = [*ROOT.glob("*.md"), *(ROOT / "docs").rglob("*.md")]
    for path in files:
        text = path.read_text(encoding="utf-8")
        token_only = re.compile(
            r"(?i)\b(?:ghp_|gho_|ghs_|github_pat_|glpat-)[a-z0-9_-]{12,}"
            r"|\bsk-[a-z0-9_-]{30,}"
            r"|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
        )
        assert not token_only.search(text), path
