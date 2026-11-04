"""Modal CLI must discover app when deploying modal_app.py."""

import modal_app
from multilingual_translation_ai_inference.resource_names import MODAL_APP_NAME


def test_modal_cli_app_discovery():
    assert modal_app.app is modal_app.modal_application
    assert modal_app.app.name == MODAL_APP_NAME


def test_entrypoint_manifest_bundled_for_cpu_and_gpu_images():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    source = (root / "modal_app.py").read_text(encoding="utf-8")
    assert source.count(".add_local_file(MODEL_MANIFEST, CONTAINER_MANIFEST_PATH)") == 2
    assert 'CONTAINER_MANIFEST_PATH = "/root/models/four_l40s_workers_q8_0_manifest.json"' in source
