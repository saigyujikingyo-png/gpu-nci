"""Independent public-descriptor packing; never uses a backend packing routine."""
import ctypes as ct

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from reference.abi import DIAGNOSTIC, Evaluation
from reference.fields import INVALID, input_flags, nci, pack_hessian

FIELDS = ("rdg", "signedrho", "lambda2", "grad", "hess", "flags")
J = np.array([[.3, .05, -.02], [.02, .24, .04], [0, -.03, .2]])


def slab(rho, start, count, periodic, mode=DIAGNOSTIC, jacobian=J):
    nx, ny, nz = rho.shape
    result = Evaluation(np.ones((count, ny, nz)), jacobian, periodic, mode)
    result.tile.global_n[:] = rho.shape
    result.tile.tile_start[:] = (start, 0, 0)
    if periodic[0]:
        origin = start - 2
        planes = [(origin + k) % nx for k in range(count + 4)]
    else:
        origin = max(0, start - 2)
        planes = list(range(origin, min(nx, start + count + 2)))
    # Explicit plane copying makes the global-to-local mapping inspectable.
    result.rho = np.empty((len(planes), ny, nz), dtype=np.float64)
    for local, global_x in enumerate(planes):
        result.rho[local, :, :] = rho[global_x, :, :]
    result.tile.input_origin[:] = (origin, 0, 0)
    result.tile.input_shape[:] = result.rho.shape
    result.tile.rho_capacity = result.rho.size
    return result


def stats_counts(stats):
    return np.array([stats.total_points, stats.valid_points, stats.invalid_points,
                     stats.numeric_failures, *stats.bit_counts], dtype=np.int64)


def assert_stats(case):
    valid = (case.flags & INVALID) == 0
    expected = [case.flags.size, np.count_nonzero(valid), np.count_nonzero(~valid),
                np.count_nonzero(case.flags & 16)]
    expected += [np.count_nonzero(case.flags & (1 << bit)) for bit in range(7)]
    assert_array_equal(stats_counts(case.stats), expected)


def assert_same_fields(actual, expected):
    """Frozen same-build gate: exact finite bits and exact NaN masks."""
    for name in FIELDS:
        a, b = getattr(actual, name), getattr(expected, name)
        if a is None or b is None:
            assert a is b
        elif name == "flags":
            assert_array_equal(a, b)
        else:
            assert_array_equal(np.isnan(a), np.isnan(b))
            finite = np.isfinite(b)
            assert np.all(np.isfinite(a[finite]))
            assert_array_equal(a[finite].view(np.uint64), b[finite].view(np.uint64))


def assert_reference(case, rho, grad, hess, periodic, rho_min=1e-8):
    assert_array_equal(case.flags & 15, input_flags(rho, periodic, rho_min))
    assert not np.any(case.flags & (16 | 128))
    valid = (case.flags & INVALID) == 0
    assert np.all(case.flags[valid] & 64)
    assert np.all((case.flags[~valid] & 96) == 0)
    for name in FIELDS[:-1]:
        field = getattr(case, name)
        if field is not None:
            assert np.all(np.isnan(field[~valid]))
            assert np.all(np.isfinite(field[valid]))
    rdg, signedrho, eigen = nci(rho[valid], grad[valid], hess[valid])
    assert_allclose(case.rdg[valid], rdg, atol=1e-11, rtol=1e-9)
    assert_allclose(case.lambda2[valid], eigen, atol=1e-12, rtol=1e-10)
    stable = np.abs(eigen) > 1e-9
    assert_array_equal(case.signedrho[valid][stable], signedrho[stable])
    assert_array_equal(case.signedrho[valid], np.sign(case.lambda2[valid]) * rho[valid])
    if case.grad is not None:
        assert_allclose(case.grad[valid], grad[valid], atol=1e-12, rtol=1e-10)
        assert_allclose(case.hess[valid], pack_hessian(hess)[valid], atol=1e-12, rtol=1e-10)
    assert_stats(case)


def descriptor_bytes(case):
    return ct.string_at(ct.byref(case.tile), ct.sizeof(case.tile))
