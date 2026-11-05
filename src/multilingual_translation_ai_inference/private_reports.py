"""Restricted runtime probe output shared by command-line tools."""
import json
import os
import tempfile
from pathlib import Path


def save_private_report(report: dict, *, filename: str, repository_root: Path,
                        temp_parent: str | None = None) -> Path:
    """Persist a private, unique runtime report outside Git; never publish IDs."""
    parent = Path(temp_parent or tempfile.gettempdir()).resolve()
    if parent == repository_root.resolve() or repository_root.resolve() in parent.parents:
        raise ValueError("Runtime reports cannot be saved inside the repository")
    name = filename
    if name not in {
        "gpu_api_translation.json", "gpu_api_four_model_benchmark.json",
        "unicode_input_boundary.json", "concurrent_model_jobs.json", "gpu_container_reuse.json",
        "deployed_gpu_readiness.json", "postgresql_gpu_jobs.json",
    }:
        raise ValueError("Unsupported runtime report filename")

    def contains_private_ids(value):
        if isinstance(value, dict):
            return any(
                key in {"job_id", "job_ids", "idempotency_key", "status_url",
                        "run_id", "gpu_uuid", "request_id", "trace_id", "test_job_id"}
                or contains_private_ids(nested)
                for key, nested in value.items()
            )
        if isinstance(value, (list, tuple)):
            return any(contains_private_ids(item) for item in value)
        return False

    if contains_private_ids(report):
        raise ValueError("Private runtime identifiers must not be serialized")
    directory = Path(tempfile.mkdtemp(prefix="mtai-api-smoke-", dir=parent))
    path = directory / name
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return path
