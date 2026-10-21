"""These native suites are opt-in and mandatory when explicitly selected."""
import os
from pathlib import Path
import pytest
from .support import Recorder, json_new


def pytest_configure(config):
    config.addinivalue_line('markers','integration: actual library required when native suite selected')


def gpu_environment():
    for name in ('NVCOMPILER_ACC_SYNCHRONOUS','PGI_ACC_SYNCHRONOUS','CUDA_LAUNCH_BLOCKING'):
        if name in os.environ:
            pytest.fail('force-sync variable must be absent: '+name)
    if os.environ.get('ACC_DEVICE_TYPE') != 'nvidia' or os.environ.get('ACC_DEVICE_NUM') != '0':
        pytest.fail('manual package must explicitly select NVIDIA device 0')


@pytest.fixture(scope='session')
def public():
    path, output = os.environ.get('NCI_OPENACC_LIBRARY'), os.environ.get('NCI_OPENACC_RECEIPTS')
    if not path or not output:
        pytest.fail('manual package must supply NCI_OPENACC_LIBRARY and exclusive NCI_OPENACC_RECEIPTS; GPU NOT TESTED')
    gpu_environment()
    root = Path(output)
    root.mkdir(exist_ok=True)
    recorder = Recorder(path, root / 'public', 'production-shared-library')
    yield recorder
    json_new(recorder.directory / 'end.json', dict(evaluations=recorder.evaluations,
              live_contexts=len(recorder.live), native_acceptance='requires external complete pytest/trace/receipt verification'))


@pytest.fixture(scope='session')
def bridge():
    path, output = os.environ.get('NCI_OPENACC_BRIDGE'), os.environ.get('NCI_OPENACC_RECEIPTS')
    if not path or not output:
        pytest.fail('manual package must supply NCI_OPENACC_BRIDGE and exclusive NCI_OPENACC_RECEIPTS; hooks NOT TESTED')
    gpu_environment()
    from .private import Bridge
    root = Path(output)
    root.mkdir(exist_ok=True)
    recorder = Recorder(path, root / 'private', 'same-production-objects-test-only-bridge')
    recorder.hooks = Bridge(recorder.raw.lib)
    yield recorder
    json_new(recorder.directory / 'end.json', dict(evaluations=recorder.evaluations,
              live_contexts=len(recorder.live), native_acceptance='requires external complete pytest/trace/receipt verification'))
