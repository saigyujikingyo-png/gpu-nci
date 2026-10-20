"""Packing selfchecks run with no production library installed."""
import numpy as np
import pytest
from numpy.testing import assert_array_equal

from reference.abi import DIAGNOSTIC, FULL
from slab_cases import extreme_case, slab


@pytest.mark.parametrize("nx,block", [(5, 1), (5, 3), (5, 5), (7, 4)])
@pytest.mark.parametrize("periodic", [False, True])
@pytest.mark.parametrize("mode", [FULL, DIAGNOSTIC])
def test_independent_packer_plane_labels_and_capacities(nx, block, periodic, mode):
    rho = np.arange(nx * 7 * 9, dtype=np.float64).reshape(nx, 7, 9)
    before = rho.copy()
    starts = []
    for start in range(0, nx, block):
        count = min(block, nx - start)
        case = slab(rho, start, count, (periodic, True, False), mode)
        t = case.tile
        assert tuple(t.global_n) == rho.shape
        assert tuple(t.tile_start) == (start, 0, 0)
        assert tuple(t.tile_count) == (count, 7, 9)
        assert tuple(t.input_strides) == (63, 9, 1)
        expected = list(range(start - 2, start + count + 2)) if periodic else list(
            range(max(0, start - 2), min(nx, start + count + 2)))
        assert t.input_origin[0] == expected[0]
        assert t.input_shape[0] == len(expected)
        for local, global_x in enumerate(expected):
            assert_array_equal(case.rho[local], rho[global_x % nx])
        assert t.rho_capacity == len(expected) * 63
        assert t.field_capacity == t.flags_capacity == count * 63
        assert t.grad_capacity == (3 * count * 63 if mode == DIAGNOSTIC else 0)
        assert t.hess_capacity == (6 * count * 63 if mode == DIAGNOSTIC else 0)
        assert not np.shares_memory(case.rho, rho)
        starts += list(range(start, start + count))
    assert starts == list(range(nx))
    assert_array_equal(rho, before)


@pytest.mark.parametrize("kind,shape,field,x", [
    ("global_overflow", (7, 8, 5), "global_n", 2**62+1),
    ("global_byte_limit", (7, 5, 5), "global_n", 2**54),
    ("input_overflow", (7, 8, 5), "input_shape", 2**62+1)])
def test_overflow_fixture_changes_only_target_x_extent(kind, shape, field, x):
    baseline = slab(np.ones(shape), 3, 1, (True, True, True))
    case = extreme_case(kind)
    # Construct the expected legal descriptor first, changing just the intended X.
    getattr(baseline.tile, field)[0] = x
    assert bytes(case.tile) == bytes(baseline.tile)
    assert tuple(case.tile.tile_count[1:]) == tuple(case.tile.global_n[1:])
    assert tuple(case.tile.input_shape[1:]) == tuple(case.tile.global_n[1:])
    assert_array_equal(case.rho, baseline.rho)
    assert case.rho.size <= 200
    assert case.flags.size <= 40


@pytest.mark.parametrize("kind,field", [("global_overflow", "global_n"),
                                       ("input_overflow", "input_shape")])
def test_overflow_product_wraps_to_value_that_fits_real_capacity(kind, field):
    case = extreme_case(kind)
    x, y, z = getattr(case.tile, field)
    exact = x*y*z
    assert exact > 2**63-1
    wrapped = exact % 2**64
    assert wrapped == 40  # Positive signed int64, not a negative/zero-size shortcut.
    if field == "input_shape":
        assert case.tile.rho_capacity == case.rho.size == 200
        assert wrapped <= case.tile.rho_capacity
    else:
        assert wrapped == case.tile.field_capacity == case.tile.flags_capacity == 40


def test_global_byte_limit_fixture_is_safe_in_points_but_overflows_bytes():
    case = extreme_case("global_byte_limit")
    x, y, z = case.tile.global_n
    n = x*y*z
    assert 0 < n <= 2**63-1
    assert n*48 > 2**63-1
