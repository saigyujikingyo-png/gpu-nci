"""Only the real configured CLI and driver may satisfy integration tests."""
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def executables():
    values = {name: os.environ.get(name) for name in ("NCI_DRIVER", "NCI_CLI")}
    if not all(values.values()):
        pytest.skip("NCI_DRIVER/NCI_CLI unset: real CLI-to-native pipeline NOT TESTED")
    paths = {name: Path(value).resolve() for name, value in values.items()}
    for name, path in paths.items():
        if not path.is_file():
            pytest.fail(f"configured {name} is not a file: {path}")
    return paths
