"""Public C ABI slab equivalence, independent mathematical truth, tiny inputs."""
import ctypes as ct
from itertools import product
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
from numpy.testing import assert_array_equal

from reference.abi import (DIAGNOSTIC, FULL, INVALID_ARGUMENT, INVALID_INPUT,
                           NUMERIC_FAILURE, OK, UNSUPPORTED, Evaluation, options)
from reference.fields import fd4, periodic_fourier
from slab_cases import (FIELDS, J, assert_reference, assert_same_fields, assert_stats,
                        descriptor_bytes, slab, stats_counts)

pytestmark = pytest.mark.integration
PERIODIC = list(product((False, True), repeat=3))


def evaluate_partition(library, rho, periodic, block, mode, threads=1, **kwargs):
    opts = options(mode=mode, threads=threads, **kwargs)
    original_opts = bytes(opts)
    full = Evaluation(rho, J, periodic, mode)
    pieces, counts, statuses = [], np.zeros(11, dtype=np.int64), []
    source = rho.copy()
    with library.context(opts) as handle:
        full_source, full_desc = full.rho.copy(), descriptor_bytes(full)
        status, error = library.run(handle, full)
        assert status in (OK, INVALID_INPUT), error
        assert_array_equal(full.rho, full_source)
        assert descriptor_bytes(full) == full_desc
        for start in range(0, rho.shape[0], block):
            case = slab(rho, start, min(block, rho.shape[0] - start), periodic, mode)
            packed, desc = case.rho.copy(), descriptor_bytes(case)
            status, error = library.run(handle, case)
            assert status in (OK, INVALID_INPUT), (start, status, error)
            assert_stats(case)
            assert_array_equal(case.rho, packed)
            assert descriptor_bytes(case) == desc
            if status == INVALID_INPUT:
                assert case.stats.valid_points == case.stats.numeric_failures == 0
            counts += stats_counts(case.stats)
            statuses.append(status)
            pieces.append(case)
    assembled = Evaluation(rho, J, periodic, mode)
    for name in FIELDS:
        if getattr(assembled, name) is not None:
            setattr(assembled, name, np.concatenate([getattr(c, name) for c in pieces], axis=0))
    assembled.stats = full.stats  # Counts are independently checked below.
    assert_array_equal(counts, stats_counts(full.stats))
    assert_same_fields(assembled, full)
    assert_array_equal(rho, source)
    assert bytes(opts) == original_opts
    return assembled, statuses


@pytest.mark.parametrize("periodic", PERIODIC)
@pytest.mark.parametrize("block", [1, 3, 4, 7])
@pytest.mark.parametrize("mode", [FULL, DIAGNOSTIC])
def test_partition_all_axes_sizes_and_modes(library, periodic, block, mode):
    rho, grad, hess = periodic_fourier((7, 9, 11), J,
        [(.1, (1, 2, 1), .2), (.08, (2, -1, 0), -.4)])
    case, statuses = evaluate_partition(library, rho, periodic, block, mode)
    assert_reference(case, rho, grad, hess, periodic)
    if not periodic[0] and block == 1:
        assert statuses[:2] == [INVALID_INPUT] * 2
        assert statuses[-2:] == [INVALID_INPUT] * 2


@pytest.mark.parametrize("periodic", [(False, False, False), (True, True, True)])
@pytest.mark.parametrize("block", [1, 3, 5])
def test_nx5_duplicate_halos_and_short_tail(library, periodic, block):
    rho, grad, hess = periodic_fourier((5, 7, 9), J, [(.1, (1, 1, 2), .3)])
    case, _ = evaluate_partition(library, rho, periodic, block, DIAGNOSTIC)
    assert_reference(case, rho, grad, hess, periodic)


def test_threads_1_2_4_same_fields_not_a_benchmark(library):
    periodic = (True, False, True)
    rho, grad, hess = periodic_fourier((7, 9, 11), J, [(.1, (1, 2, 1), .2)])
    baseline = None
    for threads in (1, 2, 4):
        case, _ = evaluate_partition(library, rho, periodic, 3, DIAGNOSTIC, threads)
        assert_reference(case, rho, grad, hess, periodic)
        if baseline is not None:
            assert_same_fields(case, baseline)
            assert bytes(case.stats) == bytes(baseline.stats)
        baseline = case


@pytest.mark.parametrize("location", [(0, 0, 0), (3, 2, 0)])
@pytest.mark.parametrize("periodic", [(True, True, True), (False, True, False)])
def test_allowed_negative_seams_and_mixed_corners(library, location, periodic):
    rho = np.ones((7, 9, 11))
    rho[location] = -5e-12
    grad, hess = fd4(rho, J)
    case, _ = evaluate_partition(library, rho, periodic, 3, DIAGNOSTIC,
                                  negative_tolerance=1e-10)
    assert_reference(case, rho, grad, hess, periodic)
    if all(periodic):
        corner2 = tuple((np.array(location) - [2, 2, 0]) % rho.shape)
        corner3 = tuple((np.array(location) - [2, 2, 2]) % rho.shape)
        assert case.flags[corner2] & 8
        assert not case.flags[corner3] & 8


def test_global_all_invalid_is_completed_abi3(library):
    rho = np.full((5, 7, 9), 1e-10)
    case, statuses = evaluate_partition(library, rho, (False,) * 3, 1, DIAGNOSTIC)
    assert statuses == [INVALID_INPUT] * 5
    assert case.stats.total_points == rho.size
    assert case.stats.invalid_points == rho.size
    assert case.stats.valid_points == case.stats.numeric_failures == 0
    for name in FIELDS[:-1]:
        assert np.all(np.isnan(getattr(case, name)))


def test_true_numeric_failure_populates_slab_and_counts(library):
    rho = np.ones((5, 5, 5))
    rho[2, 2, 2], rho[3, 2, 2] = 1e-250, 2
    counts = np.zeros(11, dtype=np.int64)
    with library.context(options(rho_min=1e-260)) as handle:
        for start in range(3):
            case = slab(rho, start, 1, (False,) * 3, jacobian=np.eye(3))
            source = case.rho.copy()
            status, error = library.run(handle, case)
            assert status == (NUMERIC_FAILURE if start == 2 else INVALID_INPUT), error
            assert_stats(case)
            assert_array_equal(case.rho, source)
            counts += stats_counts(case.stats)
    assert_array_equal(counts[:4], [75, 0, 75, 1])
    assert case.flags[0, 2, 2] & 16
    for name in FIELDS[:-1]:
        assert np.all(np.isnan(getattr(case, name)))


@pytest.mark.parametrize("mutation", ["missing_halo", "extra_right", "wrong_origin",
    "y_partial", "z_partial", "y_origin", "stride", "negative_stride"])
@pytest.mark.parametrize("periodic_x", [False, True])
@pytest.mark.parametrize("start,count", [(0, 1), (2, 3), (6, 1)])
def test_unsupported_slab_descriptor_leaves_buffers_and_stats(library, mutation,
                                                             periodic_x, start, count):
    case = slab(np.ones((7, 9, 11)), start, count, (periodic_x, True, True))
    if mutation == "missing_halo":
        case.tile.input_shape[0] -= 1
    elif mutation == "extra_right":
        case.rho = np.ones((case.rho.shape[0] + 1, 9, 11))
        case.tile.input_shape[0] += 1
        case.tile.rho_capacity = case.rho.size
    elif mutation == "wrong_origin":
        case.tile.input_origin[0] += 1
    elif mutation in ("y_partial", "z_partial"):
        case.tile.tile_count[1 if mutation == "y_partial" else 2] -= 1
    elif mutation == "y_origin":
        case.tile.input_origin[1] = 1
    else:
        case.tile.input_strides[2] = 2 if mutation == "stride" else -1
    assert_rejected(library, case, UNSUPPORTED)


def assert_rejected(library, case, expected):
    case.stats.total_points = 739  # Preflight may not erase prior caller state.
    before, source, stats = case.snapshot(), case.rho.copy(), bytes(case.stats)
    with library.context() as handle:
        status, error = library.run(handle, case)
    assert status == expected, (status, error)
    assert case.unchanged(before)
    assert bytes(case.stats) == stats
    assert_array_equal(case.rho, source)


@pytest.mark.parametrize("field", ["rho_capacity", "field_capacity", "flags_capacity",
                                  "grad_capacity", "hess_capacity"])
def test_slab_each_capacity_minus_one(library, field):
    case = slab(np.ones((7, 9, 11)), 2, 1, (True,) * 3)
    setattr(case.tile, field, getattr(case.tile, field) - 1)
    assert_rejected(library, case, INVALID_ARGUMENT)


@pytest.mark.parametrize("plane", [0, -1])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1e-9])
def test_preflight_scans_halo_without_writes(library, plane, bad):
    case = slab(np.ones((7, 9, 11)), 3, 1, (True,) * 3)
    case.rho[plane, -1, -1] = bad
    assert_rejected(library, case, INVALID_INPUT)


@pytest.mark.parametrize("name", ["rdg", "signedrho", "lambda2", "grad", "hess", "flags"])
def test_alias_reaches_final_halo_not_just_output_extent(library, name):
    case = slab(np.ones((7, 9, 11)), 3, 1, (True,) * 3)
    nin = case.rho.size
    storage = np.ones(nin + 6 * case.flags.size + 8)
    case.rho = storage[:nin].reshape(case.rho.shape)
    target = getattr(case, name)
    if name == "flags":
        alias = storage[nin-1:].view(np.uint8)[:target.size].reshape(target.shape)
    else:
        alias = storage[nin-1:nin-1+target.size].reshape(target.shape)
    setattr(case, name, alias)
    before = storage.copy()
    assert_rejected(library, case, INVALID_ARGUMENT)
    assert_array_equal(storage, before)


@pytest.mark.parametrize("mutation", ["start_min", "count_min", "origin_min",
    "shape_min", "global_overflow", "global_byte_limit", "input_overflow", "halo_overflow"])
def test_extreme_extent_rejected_in_isolated_process(library, mutation):
    code = r'''
import os, sys
import numpy as np
from reference.abi import Library, INVALID_ARGUMENT, UNSUPPORTED
from slab_cases import slab
from test_x_slabs import assert_rejected
case = slab(np.ones((7,9,11)), 3, 1, (True,True,True))
kind = sys.argv[1]
if kind in ('start_min','count_min','origin_min','shape_min'):
    name = dict(start_min='tile_start', count_min='tile_count', origin_min='input_origin', shape_min='input_shape')[kind]
    getattr(case.tile, name)[0] = -(2**63)
elif kind == 'global_overflow':
    case.tile.global_n[:] = (2**62+1, 8, 5)
elif kind == 'global_byte_limit':
    case.tile.global_n[:] = (2**54, 5, 5)
elif kind == 'input_overflow':
    case.tile.input_shape[0] = 2**63-1
else:
    case.tile.global_n[:] = (2**63-1, 5, 5)
    case.tile.tile_count[0] = 2**63-2
expected = UNSUPPORTED if kind == 'origin_min' else INVALID_ARGUMENT
assert_rejected(Library(os.environ['NCI_LIBRARY']), case, expected)
'''
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(root), str(Path(__file__).parent)])
    result = subprocess.run([sys.executable, "-c", code, mutation], cwd=root, env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
