"""Integration: actual CPU ABI, analytic/Fourier references, tiny grids only."""
import numpy as np
import pytest
from numpy.testing import assert_allclose, assert_array_equal

from reference.abi import (DIAGNOSTIC, FULL, INVALID_INPUT, OK, Evaluation, options)
from reference.fields import (INVALID, NUM_UNCERTAIN, SCI_UNCERTAIN, FAILURE,
    STENCIL, input_flags, fd4, nci, pack_hessian, periodic_fourier, quadratic)

pytestmark = pytest.mark.integration
SKEW = np.array([[0.3, 0.05, -0.02], [0.02, 0.24, 0.04], [0, -0.03, 0.2]])


def check_flags_stats(case, expected, record_property):
    assert_array_equal(case.flags & 15, expected)
    assert not np.any(case.flags & FAILURE)
    assert not np.any(case.flags & 128)
    valid = (case.flags & INVALID) == 0
    assert np.all(case.flags[valid] & SCI_UNCERTAIN)
    assert np.all((case.flags[~valid] & (NUM_UNCERTAIN | SCI_UNCERTAIN)) == 0)
    for field in (case.rdg, case.signedrho, case.lambda2, case.grad, case.hess):
        if field is not None:
            assert np.all(np.isnan(field[~valid]))
            assert np.all(np.isfinite(field[valid]))
    stats = case.stats
    assert stats.total_points == case.rho.size
    assert stats.valid_points == np.count_nonzero(valid)
    assert stats.invalid_points == np.count_nonzero(~valid)
    assert stats.numeric_failures == 0
    for bit in range(7):
        assert stats.bit_counts[bit] == np.count_nonzero(case.flags & (1 << bit))
    stable = valid & ((case.flags & NUM_UNCERTAIN) == 0)
    record_property("numeric_sign_stable_points", int(np.count_nonzero(stable)))
    record_property("numeric_valid_points", int(np.count_nonzero(valid)))
    record_property("scientific_sign_certified_points", 0)
    return valid


def check_numeric(case, grad, hess, valid):
    assert_allclose(case.grad[valid], grad[valid], atol=1e-12, rtol=1e-10)
    assert_allclose(case.hess[valid], pack_hessian(hess)[valid], atol=1e-12, rtol=1e-10)
    rdg, signedrho, lambda2 = nci(case.rho[valid], grad[valid], hess[valid])
    assert_allclose(case.rdg[valid], rdg, atol=1e-11, rtol=1e-9)
    assert_allclose(case.lambda2[valid], lambda2, atol=1e-12, rtol=1e-10)
    # Mathematical raw sign is unstable near a zero eigenvalue; do not assert
    # raw signedrho there. No numerical error tolerance is enlarged.
    away_from_zero = np.abs(lambda2) > 1e-9
    assert_array_equal(case.signedrho[valid][away_from_zero], signedrho[away_from_zero])


@pytest.mark.parametrize("mode", [FULL, DIAGNOSTIC])
def test_constant_finite_and_full_mode(library, mode, record_property):
    rho = np.full((7, 9, 11), 0.125)
    case = Evaluation(rho, mode=mode)
    with library.context(options(mode=mode)) as handle:
        status, error = library.run(handle, case)
    assert status == OK, error
    valid = check_flags_stats(case, input_flags(rho), record_property)
    assert_allclose(case.rdg[valid], 0, atol=1e-11, rtol=0)
    assert_allclose(case.lambda2[valid], 0, atol=1e-12, rtol=0)
    assert np.all(case.flags[valid] & NUM_UNCERTAIN)
    if mode == DIAGNOSTIC:
        assert_allclose(case.grad[valid], 0, atol=1e-12, rtol=0)
        assert_allclose(case.hess[valid], 0, atol=1e-12, rtol=0)
    assert_array_equal(case.rho, rho)


@pytest.mark.parametrize("left_handed", [False, True])
@pytest.mark.parametrize("spectrum", [(-0.4, 0.2, 0.6), (-0.7, -0.2, 0.5)])
def test_skew_quadratic_cartesian_and_z_fastest(library, left_handed, spectrum,
                                               record_property):
    j = SKEW.copy()
    if left_handed:
        j[:, 0] *= -1
    q, _ = np.linalg.qr(np.array([[1., 2, -1], [3, 1, 2], [2, -2, 3]]))
    h = q @ np.diag(spectrum) @ q.T
    rho, grad, hess = quadratic((7, 9, 11), j, h, linear=[0.1, -0.2, 0.3],
                                origin=[-0.4, 0.3, -0.2])
    case = Evaluation(rho, j)
    with library.context() as handle:
        status, error = library.run(handle, case)
    assert status == OK, error
    valid = check_flags_stats(case, input_flags(rho), record_property)
    check_numeric(case, grad, hess, valid)
    # Noncubic grid and all components vary: transposing C/Fortran axes cannot pass.
    assert_array_equal(case.rho, rho)


@pytest.mark.parametrize("periodic", [(True, True, True), (True, False, True)])
def test_periodic_trig_discrete_fourier_symbols(library, periodic, record_property):
    rho, grad, hess = periodic_fourier((9, 11, 13), SKEW,
        [(0.1, (1, 2, 1), 0.2), (0.08, (2, -1, 0), -0.4)])
    case = Evaluation(rho, SKEW, periodic)
    with library.context() as handle:
        status, error = library.run(handle, case)
    assert status == OK, error
    valid = check_flags_stats(case, input_flags(rho, periodic), record_property)
    check_numeric(case, grad, hess, valid)


def test_allowed_negative_exact_61_point_mask(library, record_property):
    rho = np.ones((17, 17, 17))
    rho[8, 8, 8] = -5e-12
    periodic = (True, True, True)
    case = Evaluation(rho, periodic=periodic)
    with library.context(options(negative_tolerance=1e-10)) as handle:
        status, error = library.run(handle, case)
    assert status == OK, error
    valid = check_flags_stats(case, input_flags(rho, periodic), record_property)
    assert np.count_nonzero(case.flags & STENCIL) == 61
    assert case.flags[10, 10, 8] & STENCIL
    assert not case.flags[10, 10, 10] & STENCIL
    grad, hess = fd4(rho, np.eye(3))
    check_numeric(case, grad, hess, valid)


def test_zero_low_threshold_and_uncropped_neighbors(library, record_property):
    rho = np.ones((9, 9, 9))
    rho[3, 4, 4] = 0
    rho[5, 4, 4] = 0.1
    rho[4, 6, 4] = 0.2  # Inclusive LOW_RHO threshold.
    rho[4, 4, 6] = np.nextafter(0.2, np.inf)
    periodic = (True, True, True)
    case = Evaluation(rho, periodic=periodic)
    with library.context(options(rho_min=0.2)) as handle:
        status, error = library.run(handle, case)
    assert status == OK, error
    valid = check_flags_stats(case, input_flags(rho, periodic, 0.2), record_property)
    assert not np.any(case.flags & STENCIL)
    grad, hess = fd4(rho, np.eye(3))
    check_numeric(case, grad, hess, valid)
    clipped = rho.copy()
    clipped[clipped <= 0.2] = 0
    clipped_grad, _ = fd4(clipped, np.eye(3))
    assert np.max(np.abs(grad[valid] - clipped_grad[valid])) > 0.01
    assert_array_equal(case.rho, rho)


def test_all_invalid_returns_populated_flags_and_stats(library, record_property):
    rho = np.full((5, 5, 5), 1e-10)
    case = Evaluation(rho)
    with library.context() as handle:
        status, error = library.run(handle, case)
    assert status == INVALID_INPUT, error
    valid = check_flags_stats(case, input_flags(rho), record_property)
    assert not np.any(valid)


def test_optional_jacobi_nonconvergence_hook(library):
    # The public ABI deliberately has no test_max_rotations field. Do not guess
    # private symbol signatures or enable failure injection in production.
    pytest.skip("No standardized C test-only Jacobi hook in public v1 ABI; "
                "nonconvergence injection belongs to the core test-only CTest target")
