"""Public ABI recording and bytewise guards; no production internals imported."""
import ctypes as ct
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests/oracle'))
from reference.abi import (Library, Options, Stats, Tile, DOUBLE_P, U8_P, ptr,
                           options, OK)

FIELDS = ('rdg', 'signedrho', 'lambda2', 'grad', 'hess', 'flags')
MAX_EVALS = 512


def fingerprint(path):
    path = Path(path).resolve(strict=True)
    data = path.read_bytes()
    return dict(path=str(path), sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))


def json_new(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def byte_snapshot(case):
    return dict(rho=case.rho.tobytes(), tile=bytes(case.tile), stats=bytes(case.stats),
                **{name: None if getattr(case, name) is None else getattr(case, name).tobytes()
                   for name in FIELDS})


def assert_unchanged(case, before):
    assert byte_snapshot(case) == before


def guard_case(case):
    """64-byte canaries around each actual allocation, including rho and stats."""
    guards = []
    for name in ('rho', *FIELDS):
        array = getattr(case, name)
        if array is None:
            continue
        backing = np.full(array.nbytes + 128, 0xD7, dtype=np.uint8)
        view = backing[64:-64].view(array.dtype).reshape(array.shape)
        view[...] = array
        setattr(case, name, view)
        guards.append(backing)
    storage = (ct.c_uint8 * (88 + 128))(*([0xD7] * (88 + 128)))
    stats = Stats.from_buffer(storage, 64)
    ct.memmove(ct.byref(stats), bytes(case.stats), 88)
    case.stats = stats
    case._stats_backing = storage
    case._guards = guards
    return case


def check_guards(case):
    for array in getattr(case, '_guards', []):
        assert np.all(array[:64] == 0xD7) and np.all(array[-64:] == 0xD7)
    if hasattr(case, '_stats_backing'):
        raw = bytes(case._stats_backing)
        assert raw[:64] == raw[-64:] == bytes([0xD7]) * 64


class Recorder:
    """Every native call is retained immediately, even when a later assertion fails."""
    def __init__(self, path, directory, role):
        self.path = Path(path).resolve(strict=True)
        self.receipt = fingerprint(self.path)
        self.directory = Path(directory)
        self.directory.mkdir()  # exclusive; a consumed directory is never reused
        self.role, self.ordinal, self.evaluations, self.live = role, 0, 0, set()
        self.raw = Library(self.path)
        json_new(self.directory / 'library.json', dict(schema_version=1, role=role,
                 library=self.receipt, abi_sizes=[ct.sizeof(x) for x in (Options, Tile, Stats)]))

    def retain(self, kind, case_id, status, error, blobs=None, **extra):
        self.ordinal += 1
        stem = f'{self.ordinal:04d}'
        files = {}
        for name, data in (blobs or {}).items():
            file = self.directory / f'{stem}-{name}.bin'
            with file.open('xb') as stream:
                stream.write(data)
            files[name] = fingerprint(file)
        value = dict(schema_version=1, kind=kind, case_id=case_id, ordinal=self.ordinal,
                     library=self.receipt, status=int(status), error=error,
                     artifacts=files, **extra)
        json_new(self.directory / f'{stem}.json', value)
        return value

    @contextmanager
    def context(self, opts=None, case_id='context'):
        opts = options(backend=1) if opts is None else opts
        assert len(self.live) < 2, 'frozen simultaneous-context ceiling'
        handle, error = ct.c_void_p(), ct.create_string_buffer(512)
        before = bytes(opts)
        rc = self.raw.create(ct.byref(opts), ct.byref(handle), error, len(error))
        self.retain('create', case_id, rc, error.value.decode('utf-8'),
                    dict(options=before, errbuf=error.raw), backend=int(opts.backend),context_token=handle.value)
        assert bytes(opts) == before
        assert rc == OK and handle.value, (rc, error.value)
        self.live.add(handle.value)
        try:
            yield handle
        finally:
            rc = self.raw.destroy(handle, error, len(error))
            self.retain('destroy', case_id, rc, error.value.decode('utf-8'), dict(errbuf=error.raw),context_token=handle.value)
            self.live.remove(handle.value)
            assert rc == OK, (rc, error.value)

    def run(self, handle, case, case_id, arguments=None):
        assert self.evaluations < MAX_EVALS
        self.evaluations += 1
        before = byte_snapshot(case)
        error = ct.create_string_buffer(512)
        args = [handle, ct.byref(case.tile), ptr(case.rho), ptr(case.rdg),
                ptr(case.signedrho), ptr(case.lambda2), ptr(case.grad), ptr(case.hess),
                ptr(case.flags, U8_P), ct.byref(case.stats), error, len(error)]
        for index, value in (arguments or {}).items():
            args[index] = value
        rc = self.raw.evaluate(*args)
        after = byte_snapshot(case)
        blobs = {'input-rho': before['rho'], 'tile': before['tile'],
                 'stats-before': before['stats'], 'stats-after': after['stats'],
                 'errbuf': error.raw}
        for name in FIELDS:
            if after[name] is not None:
                blobs[name] = after[name]
        self.retain('evaluate', case_id, rc, error.value.decode('utf-8'), blobs,
                    shape=list(case.flags.shape), input_shape=list(case.rho.shape),
                    tile_start=list(case.tile.tile_start), context_token=handle.value,
                    mutations=sorted((arguments or {}).keys()))
        check_guards(case)
        assert before['rho'] == after['rho'], 'caller rho was changed'
        assert before['tile'] == after['tile'], 'caller descriptor was changed'
        assert fingerprint(self.path) == self.receipt, 'loaded library changed'
        if rc in (0, 3, 4) and not arguments and case.stats.total_points == case.flags.size:
            invalid = (case.flags & 31) != 0
            for name in FIELDS[:-1]:
                field = getattr(case, name)
                if field is not None:
                    assert np.all(field[invalid].view(np.uint64) == 0x7ff8000000000000), 'noncanonical invalid field or retained poison'
        return rc, error.value.decode('utf-8')
