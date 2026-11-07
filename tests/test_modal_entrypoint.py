"""Modal CLI must discover app when deploying modal_app.py."""

import modal_app
from translation_ai_inference.resource_names import MODAL_APP_NAME


def test_modal_cli_app_discovery():
    assert modal_app.app is modal_app.modal_application
    assert modal_app.app.name == MODAL_APP_NAME
