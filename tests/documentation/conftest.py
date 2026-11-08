from pathlib import Path

import pytest
from documentation_test_support import require_published_readmes


@pytest.fixture
def published_readmes():
    return require_published_readmes(Path(__file__).resolve().parents[2])
