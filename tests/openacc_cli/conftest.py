"""Explicit opt-in only. A requested native suite fails closed, never skips."""
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "e2e"))


def pytest_addoption(parser):
    parser.addoption("--openacc-cli-native", action="store_true", default=False,
                     help="collect the finite real OpenACC CLI suite (requires frozen inputs)")


def pytest_ignore_collect(collection_path, config):
    if collection_path.name == "test_native.py":
        return not config.getoption("--openacc-cli-native")


def pytest_sessionfinish(session, exitstatus):
    if session.config.getoption("--openacc-cli-native"):
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None and reporter.stats.get("skipped"):
            session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.fixture(scope="session")
def executables(request):
    # Explicit file/nodeid selection bypasses pytest_ignore_collect. Check the
    # option before requesting atom metadata or inspecting any native input.
    if not request.config.getoption("--openacc-cli-native"):
        pytest.fail("native CLI fixtures require --openacc-cli-native")
    request.getfixturevalue("cube_atom_bytes")
    result = {}
    for name in ("NCI_DRIVER", "NCI_OPENACC_DRIVER", "NCI_CLI"):
        value = os.environ.get(name)
        if not value:
            pytest.fail(f"required frozen native input {name} is unset")
        path = Path(value).resolve(strict=True)
        if not path.is_file():
            pytest.fail(f"{name} is not a regular file")
        result[name] = path
    assert result["NCI_DRIVER"] != result["NCI_OPENACC_DRIVER"]
    return result


@pytest.fixture(scope="session")
def cube_atom_bytes():
    value = os.environ.get("NCI_CUBE_ATOM_BYTES", "")
    if not value.isascii() or not value.isdecimal() or not 0 < int(value) <= 2**63-1:
        pytest.fail("NCI_CUBE_ATOM_BYTES must bind independently checked compiled atom size")
    return int(value)
