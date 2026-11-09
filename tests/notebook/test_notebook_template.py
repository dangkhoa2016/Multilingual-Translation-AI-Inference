import re

import nbformat
from notebook_test_support import NOTEBOOK_PATH, notebook, source


def test_notebook_is_valid_and_unexecuted():
    nbformat.validate(nbformat.read(NOTEBOOK_PATH, as_version=4))
    cells = notebook()["cells"]
    assert len(cells) == 6
    assert [c["id"] for c in cells] == ["intro", "config", "instructions", "helpers", "full-demo", "results"]
    assert all(c.get("execution_count") is None and not c.get("outputs") for c in cells if c["cell_type"] == "code")

def test_only_two_modes_and_no_old_flags():
    content = source("config") + source("helpers") + source("full-demo")
    assert 'DEMO_MODE = "offline"' in content
    assert 'DEMO_RUN_ID = "auto"' in content
    for forbidden in ("ACKNOWLEDGE_PAID_GPU", "RUN_SINGLE_MODEL_POST", "RUN_MULTI_MODEL_POST",
                      "RUN_HEALTH_GET", "RUN_MODEL_CATALOG_GET", "RUN_SUBMITTED_JOB_POLL",
                      "LOAD_FROM_COLAB_SECRETS", "LOAD_FROM_KAGGLE_SECRETS"):
        assert forbidden not in content

def test_code_compiles_and_anchors_are_absent():
    for c in notebook()["cells"]:
        text = "".join(c["source"])
        if c["cell_type"] == "code":
            compile(text, c["id"], "exec")
        assert not re.search(r"\]\(#[^)]+\)", text)
