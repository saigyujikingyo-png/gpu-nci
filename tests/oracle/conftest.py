import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reference.abi import Library  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: requires actual NCI_LIBRARY")


@pytest.fixture(scope="session")
def library():
    path = os.environ.get("NCI_LIBRARY")
    if not path:
        pytest.skip("NCI_LIBRARY unset: actual production CPU library NOT TESTED")
    if not Path(path).is_file():
        pytest.fail(f"NCI_LIBRARY was supplied but is not a file: {path}")
    try:
        return Library(path)
    except (OSError, AttributeError) as exc:
        pytest.fail(f"cannot load actual NCI_LIBRARY ABI: {exc}")
