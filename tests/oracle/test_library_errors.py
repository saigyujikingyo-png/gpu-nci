"""Invalid descriptors never authorize reads beyond caller-owned buffers."""
import ctypes as ct
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from reference.abi import (DIAGNOSTIC, FULL, INVALID_ARGUMENT, INVALID_INPUT,
                           OK, UNSUPPORTED, Evaluation, U8_P, options, ptr)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("field,value", [
    ("abi_version", 0), ("abi_version", 2), ("struct_bytes", 0),
    ("struct_bytes", 41), ("backend", 99), ("output_mode", 99),
    ("omp_threads", 0), ("omp_threads", 17), ("reserved", 1),
    ("rho_min", 0), ("rho_min", -1), ("rho_min", float("nan")),
    ("rho_min", float("inf")), ("negative_tolerance", -1),
    ("negative_tolerance", float("nan")), ("negative_tolerance", float("inf")),
])
def test_create_rejects_bad_options_and_nulls_context(library, field, value):
    opts = options()
    setattr(opts, field, value)
    handle = ct.c_void_p(0x1234)  # Not dereferenced; failure must null this value.
    error = ct.create_string_buffer(128)
    status = library.create(ct.byref(opts), ct.byref(handle), error, len(error))
    assert status == INVALID_ARGUMENT
    assert handle.value is None


def test_null_create_destroy_arguments(library):
    opts, handle = options(), ct.c_void_p(0x1234)
    assert library.create(None, ct.byref(handle), None, 0) == INVALID_ARGUMENT
    assert handle.value is None
    assert library.create(ct.byref(opts), None, None, 0) == INVALID_ARGUMENT
    assert library.destroy(None, None, 0) == INVALID_ARGUMENT


@pytest.mark.parametrize("length", [0, 1, 4])
def test_error_buffer_is_bounded_and_terminated(library, length):
    opts = options()
    opts.abi_version = 99
    handle = ct.c_void_p()
    storage = (ct.c_char * 12)(*([b"X"] * 12))
    pointer = ct.cast(ct.byref(storage, 3), ct.POINTER(ct.c_char))
    result = library.create(ct.byref(opts), ct.byref(handle), pointer, length)
    assert result == INVALID_ARGUMENT
    raw = bytes(storage)
    assert raw[:3] == b"XXX"
    assert raw[3 + length:] == b"X" * (9 - length)
    if length:
        assert 0 in raw[3:3 + length]
    else:
        assert raw == b"X" * 12


def test_nonnull_zero_length_errbuf_success(library):
    opts, handle = options(), ct.c_void_p()
    storage = ct.create_string_buffer(b"UNCHANGED")
    before = storage.raw
    status = library.create(ct.byref(opts), ct.byref(handle), storage, 0)
    assert status == OK
    assert storage.raw == before
    assert library.destroy(handle, storage, 0) == OK
    assert storage.raw == before


@pytest.mark.parametrize("argument", ["context", "tile", "rho", "rdg",
                                    "signedrho", "lambda2", "flags", "stats"])
def test_required_null_arguments_leave_fields_untouched(library, argument):
    case = Evaluation(np.ones((5, 7, 9)))
    before = case.snapshot()
    names = ["context", "tile", "rho", "rdg", "signedrho", "lambda2", "grad",
             "hess", "flags", "stats"]
    error = ct.create_string_buffer(64)
    with library.context() as handle:
        args = [handle, ct.byref(case.tile), ptr(case.rho), ptr(case.rdg),
                ptr(case.signedrho), ptr(case.lambda2), ptr(case.grad), ptr(case.hess),
                ptr(case.flags, U8_P), ct.byref(case.stats)]
        args[names.index(argument)] = None
        status = library.evaluate(*args, error, len(error))
    assert status == INVALID_ARGUMENT
    assert case.unchanged(before)


def test_null_error_buffer_with_positive_length_is_rejected(library):
    opts, handle = options(), ct.c_void_p(0x1234)
    status = library.create(ct.byref(opts), ct.byref(handle), None, 1)
    assert status == INVALID_ARGUMENT
    assert handle.value is None


@pytest.mark.parametrize("field,value", [
    ("abi_version", 99), ("struct_bytes", 0), ("struct_bytes", 281),
    ("reserved", 1), ("rho_capacity", 0), ("field_capacity", -1),
    ("flags_capacity", 1), ("grad_capacity", 1), ("hess_capacity", 1),
])
def test_bad_tile_or_insufficient_capacity_is_untouched(library, field, value):
    case = Evaluation(np.ones((5, 7, 9)))
    setattr(case.tile, field, value)
    before = case.snapshot()
    with library.context() as handle:
        status, _ = library.run(handle, case)
    assert status == INVALID_ARGUMENT
    assert case.unchanged(before)


@pytest.mark.parametrize("field", ["rho_capacity", "field_capacity", "flags_capacity",
                                  "grad_capacity", "hess_capacity"])
def test_each_capacity_required_minus_one(library, field):
    case = Evaluation(np.ones((5, 7, 9)))
    setattr(case.tile, field, getattr(case.tile, field) - 1)
    before = case.snapshot()
    with library.context() as handle:
        status, _ = library.run(handle, case)
    assert status == INVALID_ARGUMENT
    assert case.unchanged(before)


@pytest.mark.parametrize("field", ["grad_capacity", "hess_capacity"])
def test_diagnostic_capacity_is_component_count_not_point_count(library, field):
    case = Evaluation(np.ones((5, 7, 9)))
    setattr(case.tile, field, case.rho.size)
    before = case.snapshot()
    with library.context() as handle:
        status, _ = library.run(handle, case)
    assert status == INVALID_ARGUMENT
    assert case.unchanged(before)


def test_spectral_condition_1001_rejected(library):
    case = Evaluation(np.ones((5, 5, 5)))
    case.tile.j_inv[:] = np.diag([1., 1, 1/1001]).ravel()
    before = case.snapshot()
    with library.context() as handle:
        status, _ = library.run(handle, case)
    assert status == INVALID_ARGUMENT
    assert case.unchanged(before)


@pytest.mark.parametrize("which", ["periodic", "minimum_dimension", "singular",
                                  "ill_conditioned", "nan_j", "inf_j"])
def test_bad_grid_descriptor(library, which):
    case = Evaluation(np.ones((5, 7, 9)))
    if which == "periodic":
        case.tile.periodic[1] = 2
    elif which == "minimum_dimension":
        case.tile.global_n[0] = case.tile.tile_count[0] = case.tile.input_shape[0] = 4
    elif which == "singular":
        case.tile.j_inv[:] = [0] * 9
    elif which == "ill_conditioned":
        case.tile.j_inv[:] = np.diag([1, 1, 1e-6]).ravel()
    else:
        case.tile.j_inv[0] = float("nan") if which == "nan_j" else float("inf")
    before = case.snapshot()
    with library.context() as handle:
        status, _ = library.run(handle, case)
    assert status == INVALID_ARGUMENT
    assert case.unchanged(before)


@pytest.mark.parametrize("which", ["tile_start", "tile_count", "input_origin", "stride"])
def test_initial_complete_grid_rejects_partial_layout(library, which):
    case = Evaluation(np.ones((5, 7, 9)))
    if which == "tile_start":
        case.tile.tile_start[1] = 1
        case.tile.tile_count[1] = 6
    elif which == "tile_count":
        case.tile.tile_count[1] = 6
    elif which == "input_origin":
        case.tile.input_origin[0] = -2
    else:
        case.tile.input_strides[2] = 2
    before = case.snapshot()
    with library.context() as handle:
        status, _ = library.run(handle, case)
    assert status == UNSUPPORTED
    assert case.unchanged(before)


@pytest.mark.parametrize("which", ["full_nonnull", "full_nonzero_capacity",
                                  "diagnostic_null_grad", "diagnostic_null_hess"])
def test_output_mode_pointer_contract(library, which):
    case = Evaluation(np.ones((5, 7, 9)))
    mode = FULL if which.startswith("full") else DIAGNOSTIC
    if which == "full_nonzero_capacity":
        case.grad = case.hess = None
    elif which == "diagnostic_null_grad":
        case.grad = None
    elif which == "diagnostic_null_hess":
        case.hess = None
    before = case.snapshot()
    with library.context(options(mode=mode)) as handle:
        status, _ = library.run(handle, case)
    assert status == INVALID_ARGUMENT
    assert case.unchanged(before)


@pytest.mark.parametrize("bad_rho", [float("nan"), float("inf"), -float("inf"), -1e-9])
def test_preflight_density_rejection_without_writes(library, bad_rho):
    case = Evaluation(np.ones((5, 7, 9)))
    case.rho[0, 0, 0] = bad_rho  # Even outside the finite valid interior.
    before = case.snapshot()
    with library.context() as handle:
        status, _ = library.run(handle, case)
    assert status == INVALID_INPUT
    assert case.unchanged(before)


def test_overflow_rejected_in_isolated_process(library):
    # Real allocations stay at 125 points, 375 gradient and 750 Hessian elements.
    # Unchecked int64 product wraps to 40, which would fit those capacities:
    # this catches overflow itself instead of short-circuiting on capacity=0.
    # Separate process makes an implementation crash/timeout a clear failed test.
    root = Path(__file__).resolve().parents[2]
    code = """
import os
import numpy as np
from reference.abi import Evaluation, Library, options, INVALID_ARGUMENT
lib = Library(os.environ['NCI_LIBRARY'])
case = Evaluation(np.ones((5,5,5)))
huge_shape = (2**62 + 1, 8, 5)
case.tile.global_n[:] = huge_shape
case.tile.tile_count[:] = huge_shape
case.tile.input_shape[:] = huge_shape
case.tile.input_strides[:] = (40, 5, 1)
assert case.tile.rho_capacity == case.tile.field_capacity == case.tile.flags_capacity == 125
assert case.tile.grad_capacity == 375 and case.tile.hess_capacity == 750
before = case.snapshot()
with lib.context(options()) as handle:
    status, error = lib.run(handle, case)
assert status == INVALID_ARGUMENT, (status, error)
assert case.unchanged(before)
print('OVERFLOW_REJECTED_WITHOUT_WRITES')
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=root, env=os.environ.copy(),
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OVERFLOW_REJECTED_WITHOUT_WRITES" in result.stdout


def test_int64_min_tile_count_rejected_before_extent_arithmetic(library):
    # Fortran logical .or. is not a short-circuit guarantee. A library must not
    # evaluate global_n - INT64_MIN while trying to reject a negative extent.
    root = Path(__file__).resolve().parents[2]
    code = """
import os
import numpy as np
from reference.abi import Evaluation, Library, options, INVALID_ARGUMENT
lib = Library(os.environ['NCI_LIBRARY'])
case = Evaluation(np.ones((5,5,5)))
case.tile.tile_count[0] = -(2**63)
before = case.snapshot()
with lib.context(options()) as handle:
    status, error = lib.run(handle, case)
assert status == INVALID_ARGUMENT, (status, error)
assert case.unchanged(before)
print('INT64_MIN_EXTENT_REJECTED_WITHOUT_WRITES')
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=root, env=os.environ.copy(),
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "INT64_MIN_EXTENT_REJECTED_WITHOUT_WRITES" in result.stdout
