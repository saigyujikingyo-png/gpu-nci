"""Independent reservation arithmetic selfchecks; no driver or CLI import."""
import pytest
import numpy as np

from test_x_slabs_cli import remote_bad_fixture, slab_budget


@pytest.mark.parametrize("mode,q", [("full", 25), ("diagnostic", 97)])
def test_pinned_slab_reservation_formula(mode, q):
    # Nx=7, Ny=9, Nz=11, B=3, T=2, no atoms. Each term is explicit.
    expected = 5544 + 5544 + q*297 + 920 + 8192 + 65536 + 8192
    assert slab_budget((7, 9, 11), 3, mode, 2) == expected
    assert slab_budget((7, 9, 11), 3, mode, 2, atom_bytes=96) == expected + 96


def test_reservation_large_values_are_not_wrapped_by_test_oracle():
    # Oracle intentionally uses Python integers; production must reject int64 overflow.
    assert slab_budget((2**55, 5, 5), 2**55, "diagnostic") > 2**63-1
    assert slab_budget((5, 2**28, 2**28), 1, "diagnostic") > 2**63-1


@pytest.mark.parametrize("bad", [float("nan"), -1e-3])
def test_remote_bad_sample_is_outside_entire_first_slab_input(bad):
    field, location = remote_bad_fixture(bad)
    assert field.rho.shape == (7, 9, 11)
    first_halo = np.arange(-2, 3) % 7
    np.testing.assert_array_equal(first_halo, [5, 6, 0, 1, 2])
    assert location == (3, 8, 10)
    assert location[0] not in first_halo
    first_input = field.rho[first_halo, :, :]
    assert np.all(np.isfinite(first_input))
    assert np.all(first_input > 0)
    if np.isnan(bad):
        assert np.isnan(field.rho[location])
    else:
        assert field.rho[location] == bad
