"""Shared fixtures and helpers for notebook client tests."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK = ROOT / "notebooks" / "translation_api_demo.ipynb"


def _normalize_notebook_sources(notebook):
    """Accept nbformat source as either a string or a list of lines."""
    for cell in notebook["cells"]:
        source = cell["source"]
        if isinstance(source, list) and all(isinstance(line, str) for line in source):
            cell["source"] = "".join(source)
        elif not isinstance(source, str):
            raise TypeError("Notebook source must be a string or a list of strings.")
    return notebook


def _notebook():
    return _normalize_notebook_sources(json.loads(NOTEBOOK.read_text(encoding="utf-8")))


def _code_cells(notebook):
    return [cell["source"] for cell in notebook["cells"] if cell["cell_type"] == "code"]


def _code_by_id(notebook):
    codes = {cell["id"]: cell["source"] for cell in notebook["cells"]
             if cell["cell_type"] == "code"}
    # Legacy fixture for existing unit tests only. User-facing workflows are
    # verified separately with individually executed notebook cells.
    codes["settings"] = "\n".join((codes["request-key-internals"], codes["settings"], codes["advanced-settings"]))
    return codes


def _run_helpers(code, state):
    for cid in ("settings", "secret-loader", "http-client", "validation-payload",
                "submit-preflight", "poll-summary"):
        exec(compile(code[cid], str(NOTEBOOK), "exec"), state)


def _bind_accepted_test_references(state):
    """Legacy test fixtures represent accepted submissions for the current input."""
    for kind, path, key, multi in (
        ("single", "/v1/jobs/translations", "SINGLE_MODEL_IDEMPOTENCY_KEY", False),
        ("multi", "/v1/jobs/benchmarks", "MULTI_MODEL_IDEMPOTENCY_KEY", True),
    ):
        record = state.get("submitted_" + kind)
        if (isinstance(record, dict) and record.get("_gateway_origin") == state["API_BASE_URL"]
                and "_request_fingerprint" not in record):
            record["_request_fingerprint"] = state["_request_fingerprint"](
                path, state["_payload"](multi_model=multi), state[key]
            )




RECOVERY_GUIDE_IDS = (
    "advanced-usage",
    "request-identity-guide",
    "get-only-recovery-guide",
    "secrets-setup-guide",
)


def _advanced_guide(notebook):
    """Review all short recovery topics as one logical guide."""
    by_id = {cell["id"]: cell["source"] for cell in notebook["cells"]}
    return "\n".join(by_id[cid] for cid in RECOVERY_GUIDE_IDS)
