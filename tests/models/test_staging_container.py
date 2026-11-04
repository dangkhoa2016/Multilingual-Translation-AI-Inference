"""Offline checks for the source and filesystem available to Modal staging."""
import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path

import modal
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/models/stage_model_weights.py"


def load_staging(monkeypatch, *, remote=False):
    name = "staging_container_test"
    if remote:
        module = types.ModuleType(name)
        module.__file__ = "/root/stage_model_weights.py"
        monkeypatch.setattr(modal, "is_local", lambda: False)

        def reject_local_file(*args, **kwargs):
            raise AssertionError("Container import must not mount a local repository file")

        monkeypatch.setattr(modal.Image, "add_local_file", reject_local_file)
    else:
        spec = importlib.util.spec_from_file_location(name, SCRIPT)
        module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    exec(compile(SCRIPT.read_text(), module.__file__, "exec"), module.__dict__)
    return module


def test_flat_remote_module_does_not_require_local_repository(monkeypatch):
    staging = load_staging(monkeypatch, remote=True)
    assert staging.MANIFEST == Path(staging.IMAGE_MANIFEST)
    assert set(staging.WORKERS) == {"hy_mt2_30b", "index_35b", "gemma4_31b_it", "qwen35_35b"}


def test_staging_image_explicitly_includes_imported_project_package(monkeypatch):
    included = []
    original = modal.Image.add_local_python_source

    def record_source(image, *modules, **kwargs):
        included.extend(modules)
        return original(image, *modules, **kwargs)

    monkeypatch.setattr(modal.Image, "add_local_python_source", record_source)
    load_staging(monkeypatch)
    assert "multilingual_translation_ai_inference" in included


@pytest.mark.parametrize("model", ["hy_mt2_30b", "index_35b", "gemma4_31b_it", "qwen35_35b"])
@pytest.mark.parametrize("fault", [None, "size", "checksum"])
def test_staging_verifies_or_rejects_each_model(monkeypatch, tmp_path, model, fault):
    staging = load_staging(monkeypatch)
    payload = b"tiny synthetic GGUF fixture"
    digest = hashlib.sha256(payload).hexdigest()
    spec = {"gguf_filename": "fixture.gguf", "gguf_lfs_sha256": digest,
            "gguf_size_bytes": len(payload), "gguf_repository": "synthetic/model",
            "gguf_revision": "pinned-synthetic-revision"}
    if fault == "size":
        spec["gguf_size_bytes"] += 1
    elif fault == "checksum":
        spec["gguf_lfs_sha256"] = "0" * 64
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"models": {model: spec}}))
    monkeypatch.setattr(staging, "IMAGE_MANIFEST", str(manifest))
    monkeypatch.setattr(staging, "VOL_ROOT", tmp_path)
    downloads, commits = [], []

    def download(**kwargs):
        downloads.append(kwargs)
        destination = Path(kwargs["local_dir"]) / kwargs["filename"]
        destination.write_bytes(payload)
        return str(destination)

    hub = types.ModuleType("huggingface_hub")
    hub.hf_hub_download = download
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    monkeypatch.setattr(staging, "VOLUMES", {
        model: types.SimpleNamespace(commit=lambda: commits.append(model)),
    })
    if fault:
        with pytest.raises(RuntimeError, match="length mismatch|SHA256 mismatch"):
            staging.perform_cpu_staging(model)
        assert commits == []
        assert not (tmp_path / staging.marker_filename(model)).exists()
        return
    first = staging.perform_cpu_staging(model)
    assert first["status"] == "verified_and_committed"
    marker = json.loads((tmp_path / staging.marker_filename(model)).read_text())
    assert marker["sha256_verified_locally"] == digest
    assert marker["repo_revision"] == spec["gguf_revision"]
    assert commits == [model]
    second = staging.perform_cpu_staging(model)
    assert second["status"] == "already_verified"
    assert len(downloads) == 1
    assert downloads[0]["revision"] == spec["gguf_revision"]
    assert downloads[0]["token"] is True


def test_huggingface_staging_secret_is_required_only_for_cpu_workers(monkeypatch):
    recorded = []
    original = modal.Secret.from_name

    def record(name, **kwargs):
        recorded.append((name, kwargs))
        return original(name, **kwargs)

    monkeypatch.setattr(modal.Secret, "from_name", staticmethod(record))
    staging = load_staging(monkeypatch)
    from multilingual_translation_ai_inference.resource_names import (
        MODAL_HUGGINGFACE_DOWNLOAD_SECRET_NAME,
    )

    assert recorded == [
        (MODAL_HUGGINGFACE_DOWNLOAD_SECRET_NAME, {"required_keys": ["HF_TOKEN"]})
    ]
    assert staging.CPU_ARGS["secrets"] == [staging.HUGGINGFACE_DOWNLOAD_SECRET]
    assert staging.CPU_ARGS.get("gpu") is None
    gateway_source = (ROOT / "modal_app.py").read_text()
    assert "MODAL_HUGGINGFACE_DOWNLOAD_SECRET_NAME" not in gateway_source
