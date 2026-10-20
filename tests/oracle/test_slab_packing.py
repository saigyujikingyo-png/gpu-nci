"""Packing selfchecks run with no production library installed."""
import numpy as np
import pytest
from numpy.testing import assert_array_equal

from reference.abi import DIAGNOSTIC, FULL
from slab_cases import slab


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
