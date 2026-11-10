"""Guard the fresh-installation GPU deployment order in both published runbooks."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("filename", ["deployment.md", "deployment.vi.md"])
def test_gpu_smoke_is_after_explicit_mode_activation(filename):
    text = (ROOT / "docs" / filename).read_text(encoding="utf-8")
    mock_secret = text.index('"TRANSLATION_DISPATCHER_MODE": "modal-cpu-mock"')
    deploy = text.index("modal deploy --profile")
    preview = text.index("set_dispatch_mode.py --to-gpu")
    activation = text.index("set_dispatch_mode.py --to-gpu --apply")
    verified_health = text.index('inference_enabled=true and phase="gpu"') if filename == "deployment.md" else text.index('inference_enabled=true và phase="gpu"')
    paid_smoke = text.index("PYTHONPATH=src python scripts/api/smoke_gpu.py --run")
    assert mock_secret < deploy < preview < activation < verified_health < paid_smoke
    assert '--profile "$MODAL_PROFILE" --environment "$MODAL_ENVIRONMENT"' in text
    assert '--base-url "$TRANSLATION_GATEWAY_BASE_URL"' in text
    assert text.count("PYTHONPATH=src python scripts/api/smoke_gpu.py --run") == 2


@pytest.mark.parametrize("filename", ["deployment.md", "deployment.vi.md"])
def test_project_package_is_installed_before_volume_staging(filename):
    text = (ROOT / "docs" / filename).read_text(encoding="utf-8")
    install = text.index("python -m pip install -e '.[dev]'")
    staging = text.index("modal run scripts/models/stage_model_weights.py --model")
    migration = text.index("alembic -c db/alembic.ini upgrade head")
    assert text.index("git clone https://github.com/dangkhoa2016/") < install
    assert install < staging < migration
    assert text.count("python -m pip install -e '.[dev]'") == 1
    assert text.count("source .venv/bin/activate") == 1
