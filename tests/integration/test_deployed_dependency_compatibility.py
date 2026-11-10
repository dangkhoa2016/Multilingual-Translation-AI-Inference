"""Keep the CPU validation profile aligned with the deployed gateway API pins."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PINS = ROOT / "constraints/deployed-gateway.txt"
MODAL_APP = ROOT / "modal_app.py"
WORKFLOW = ROOT / ".github/workflows/python-validation.yml"
PACKAGES = {"fastapi", "pydantic", "sqlalchemy"}


def _parse_pins():
    pins = {}
    for line in PINS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        package, separator, version = line.partition("==")
        assert separator and package.lower() not in pins and version
        pins[package.lower()] = version
    return pins


def test_gateway_dependency_compatibility_versions_match_modal_image():
    pins = _parse_pins()
    assert set(pins) == PACKAGES
    tree = ast.parse(MODAL_APP.read_text(encoding="utf-8"))
    deployed = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr == "pip_install":
            deployed.update(
                arg.value for arg in node.args
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            )
    for package, version in pins.items():
        assert f"{package}=={version}" in {value.lower() for value in deployed}


def test_cpu_ci_uses_deployed_core_pins_as_separate_validation_job():
    ci = WORKFLOW.read_text(encoding="utf-8")
    assert "deployed-gateway-dependency-compatibility:" in ci
    assert "-c constraints/deployed-gateway.txt -e '.[dev]'" in ci
    assert ci.count("python -m pytest -q") >= 2
    assert "python -m pip check" in ci
