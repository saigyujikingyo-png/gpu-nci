"""One guarded host-address fixture for the mapped-object-limit rejection."""
from contextlib import contextmanager
import ctypes as ct
import json
import mmap
import sys

import numpy as np

LIMIT = (1 << 31) - 1
NZ = LIMIT // (25 * 96) + 1
COUNT = 25 * NZ
PAGE = 4096
PROOF_CAP = 4096
MAP_FLAGS, RW_PROTECTION = 0x22, 3  # Linux private/anonymous; read/write.
LAYOUT = (('rho', 2, 8), ('rdg', 3, 8), ('signedrho', 4, 8),
          ('lambda2', 5, 8), ('grad', 6, 24), ('hess', 7, 48), ('flags', 8, 1))


def rounded(size):
    return (size + PAGE - 1) // PAGE * PAGE


ARENA_BYTES = sum(rounded(COUNT * width + 128) for _, _, width in LAYOUT)
RW_BYTES = sum(rounded(315 * width + 128) for _, _, width in LAYOUT)
ERROR = (f'OpenACC object 5 needs {96 * COUNT} bytes; the installed runtime '
         f'supports at most {LIMIT} bytes per mapped object')


def _system():
    assert sys.platform == 'linux' and ct.sizeof(ct.c_void_p) == 8 and mmap.PAGESIZE == PAGE
    assert mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS == MAP_FLAGS
    assert mmap.PROT_READ | mmap.PROT_WRITE == RW_PROTECTION
    libc = ct.CDLL(None, use_errno=True)  # OS mapping only; never an NCI library.
    libc.mmap.argtypes = [ct.c_void_p, ct.c_size_t, ct.c_int, ct.c_int, ct.c_int, ct.c_int64]
    libc.mmap.restype = ct.c_void_p
    libc.mprotect.argtypes = [ct.c_void_p, ct.c_size_t, ct.c_int]
    libc.mprotect.restype = ct.c_int
    libc.munmap.argtypes = [ct.c_void_p, ct.c_size_t]
    libc.munmap.restype = ct.c_int
    return libc


def _buffer_at(address, size):
    return np.ctypeslib.as_array((ct.c_uint8 * size).from_address(address))


@contextmanager
def reserve(case):
    """Only the frozen native case reserves the large, mostly inaccessible VM."""
    assert case.rho.shape == case.flags.shape == (5, 7, 9)
    original = {name: getattr(case, name) for name, _, _ in LAYOUT}
    guards = case._guards
    libc = _system()
    base = libc.mmap(None, ARENA_BYTES, 0, MAP_FLAGS, -1, 0)
    if base is None or base == ct.c_void_p(-1).value:
        raise OSError(ct.get_errno(), 'mapped-limit mmap failed')
    try:
        offset = 0
        owned = []
        for name, _, width in LAYOUT:
            prefix = base + offset
            if libc.mprotect(prefix, rounded(315 * width + 128), RW_PROTECTION):
                raise OSError(ct.get_errno(), 'mapped-limit mprotect failed')
            backing = _buffer_at(prefix, 315 * width + 128)
            backing.fill(0xD7)
            view = backing[64:-64].view(original[name].dtype).reshape(original[name].shape)
            view[...] = original[name]
            setattr(case, name, view)
            owned.append(backing)
            offset += rounded(COUNT * width + 128)
        case._guards = owned
        case._mapped_limit_base = base
        yield case
    finally:
        # Restore case-owned references before unmap; never access local views after it.
        for name, value in original.items():
            setattr(case, name, value)
        case._guards = guards
        if hasattr(case, '_mapped_limit_base'):
            del case._mapped_limit_base
        if libc.munmap(base, ARENA_BYTES):
            raise OSError(ct.get_errno(), 'mapped-limit munmap failed')


def guarded_error():
    storage = (ct.c_uint8 * 640)(*([0xD7] * 640))
    error = (ct.c_char * 512).from_buffer(storage, 64)
    ct.memset(error, 0, 512)
    return error, storage


def check_error_guard(storage):
    assert bytes(storage[:64]) == bytes(storage[-64:]) == bytes([0xD7]) * 64


def proof_blob(case, args, error_storage):
    """Capture actual argument addresses immediately before the public call."""
    rows = []
    offset = 0
    for name, argument, width in LAYOUT:
        rows.append(dict(name=name, argument=argument, pointer=ct.cast(args[argument], ct.c_void_p).value,
                         span_bytes=COUNT * width, backing_bytes=getattr(case, name).nbytes,
                         prefix_base=case._mapped_limit_base + offset,
                         prefix_bytes=rounded(315 * width + 128), permissions='rw-prefix/rest-none'))
        offset += rounded(COUNT * width + 128)
    for name, argument, size, storage in (('stats', 9, 88, case._stats_backing),
                                           ('errbuf', 10, 512, error_storage)):
        rows.append(dict(name=name, argument=argument, pointer=ct.cast(args[argument], ct.c_void_p).value,
                         span_bytes=size, backing_bytes=size, prefix_base=ct.addressof(storage),
                         prefix_bytes=size + 128, permissions='guarded-rw'))
    assert args[11] == 512
    value = dict(schema_version=1, arena_base=case._mapped_limit_base, arena_bytes=ARENA_BYTES,
                 page_bytes=PAGE, rw_bytes=RW_BYTES, external_guard_bytes=856, regions=rows)
    validate_proof(value, case.tile)
    raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode('ascii')
    assert len(raw) <= PROOF_CAP
    return raw


def validate_proof(value, tile):
    """Case-specific compare-only checks; no mapping, imports or native calls."""
    assert set(value) == {'schema_version', 'arena_base', 'arena_bytes', 'page_bytes',
                          'rw_bytes', 'external_guard_bytes', 'regions'}
    assert all(type(value[key]) is int for key in set(value) - {'regions'})
    assert (value['schema_version'], value['arena_bytes'], value['page_bytes'], value['rw_bytes'],
            value['external_guard_bytes']) == (1, 2348826624, 4096, 45056, 856)
    assert RW_BYTES + 856 == 45912 < 65536
    assert tuple(tile.global_n) == tuple(tile.tile_count) == tuple(tile.input_shape) == (5, 5, 894785)
    assert tuple(tile.tile_start) == tuple(tile.input_origin) == (0, 0, 0)
    assert tuple(tile.input_strides) == (5 * 894785, 894785, 1)
    assert (tile.rho_capacity, tile.field_capacity, tile.flags_capacity,
            tile.grad_capacity, tile.hess_capacity) == (22369625, 22369625, 22369625, 67108875, 134217750)
    objects = [8 * COUNT, 200, 200, 40 * NZ, 96 * COUNT, COUNT, 4 * COUNT, 4 * COUNT, 4 * COUNT]
    assert [i + 1 for i, size in enumerate(objects) if size > LIMIT] == [5]
    assert objects[4] == 2147484000 and 96 * (COUNT - 25) <= LIMIT
    def interval(start, size):
        assert type(start) is type(size) is int and start > 0 and size > 0
        assert start + size <= (1 << 63) - 1
        return start, start + size
    arena = interval(value['arena_base'], value['arena_bytes'])
    assert arena[0] % PAGE == 0
    rows = value['regions']
    assert type(rows) is list and len(rows) == 9
    spans, prefixes = [], []
    offset = 0
    for row, (name, argument, width) in zip(rows, (*LAYOUT, ('stats', 9, 88), ('errbuf', 10, 512))):
        assert set(row) == {'name', 'argument', 'pointer', 'span_bytes', 'backing_bytes',
                            'prefix_base', 'prefix_bytes', 'permissions'}
        assert all(type(row[key]) is int for key in set(row) - {'name', 'permissions'})
        assert row['name'] == name and row['argument'] == argument
        prefix = interval(row['prefix_base'], row['prefix_bytes'])
        span = interval(row['pointer'], row['span_bytes'])
        assert row['pointer'] == prefix[0] + 64
        if argument <= 8:
            assert row['permissions'] == 'rw-prefix/rest-none'
            assert row['backing_bytes'] == 315 * width and row['span_bytes'] == COUNT * width
            assert prefix == (arena[0] + offset, arena[0] + offset + rounded(315 * width + 128))
            assert span[1] + 64 <= arena[0] + offset + rounded(COUNT * width + 128) <= arena[1]
            offset += rounded(COUNT * width + 128)
        else:
            assert row['permissions'] == 'guarded-rw'
            assert row['backing_bytes'] == row['span_bytes'] == width
            assert row['prefix_bytes'] == width + 128
            assert prefix[1] <= arena[0] or prefix[0] >= arena[1]
        spans.append(span)
        prefixes.append(prefix)
    for ranges in (spans, prefixes):
        ordered = sorted(ranges)
        assert all(a[1] <= b[0] for a, b in zip(ordered, ordered[1:]))
