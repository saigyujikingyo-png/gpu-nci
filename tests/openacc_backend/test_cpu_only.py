"""Public CPU-only selector gate. No evaluation and no device initialization."""
import ctypes as ct
import os
from pathlib import Path
import pytest
from .support import Recorder
from reference.abi import options,BACKEND_UNAVAILABLE


def test_cpu_only_openacc_selector_is_unavailable():
    path,output=os.environ.get('NCI_CPU_LIBRARY'),os.environ.get('NCI_OPENACC_RECEIPTS')
    if not path or not output:
        pytest.fail('manual package must bind the actual CPU-only library and exclusive receipt root')
    recorder=Recorder(path,Path(output)/'cpu-selector','production-cpu-only')
    opts,handle,error=options(backend=1),ct.c_void_p(0x1234),ct.create_string_buffer(512)
    status=recorder.raw.create(ct.byref(opts),ct.byref(handle),error,len(error))
    recorder.retain('create-rejected','cpu-only-openacc-selector',status,error.value.decode(),
                    dict(options=bytes(opts),errbuf=error.raw))
    assert status==BACKEND_UNAVAILABLE and handle.value is None
