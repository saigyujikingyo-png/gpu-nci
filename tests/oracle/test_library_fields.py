"""Integration: actual CPU ABI, analytic/Fourier references, tiny grids only."""
from fractions import Fraction

import numpy as np
import pytest
from numpy.testing import assert_allclose, assert_array_equal

from reference.abi import (DIAGNOSTIC, FULL, INVALID_INPUT, NUMERIC_FAILURE,
                           OK, Evaluation, options)
from reference.fields import (INVALID, NUM_UNCERTAIN, SCI_UNCERTAIN, FAILURE,
    STENCIL, input_flags, fd4, nci, pack_hessian, periodic_fourier, quadratic)
from reference.extreme import (exact_center_derivatives, finite_large_rdg_fixture,
                               high_precision_rdg)

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
    # This identity uses the ACTUAL returned eigenvalue, even inside its
    # uncertainty band. A label must never silently zero the raw scalar.
    assert_array_equal(case.signedrho[valid],
                       np.sign(case.lambda2[valid]) * case.rho[valid])
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
    if case.grad is not None:
        assert_allclose(case.grad[valid], grad[valid], atol=1e-12, rtol=1e-10)
    if case.hess is not None:
        assert_allclose(case.hess[valid], pack_hessian(hess)[valid], atol=1e-12, rtol=1e-10)
    rdg, signedrho, lambda2 = nci(case.rho[valid], grad[valid], hess[valid])
    assert_allclose(case.rdg[valid], rdg, atol=1e-11, rtol=1e-9)
    assert_allclose(case.lambda2[valid], lambda2, atol=1e-12, rtol=1e-10)
    # Reference-versus-actual sign is a different question from the raw identity
    # above. This fixed 1e-9 band is a fixture comparison rule, not a production
    # confidence claim; no numerical error tolerance is enlarged.
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


@pytest.mark.parametrize("mode", [FULL, DIAGNOSTIC])
@pytest.mark.parametrize("periodic", [(True, True, True), (True, False, True)])
def test_periodic_trig_discrete_fourier_symbols(library, periodic, mode, record_property):
    rho, grad, hess = periodic_fourier((9, 11, 13), SKEW,
        [(0.1, (1, 2, 1), 0.2), (0.08, (2, -1, 0), -0.4)])
    case = Evaluation(rho, SKEW, periodic, mode=mode)
    with library.context(options(mode=mode)) as handle:
        status, error = library.run(handle, case)
    assert status == OK, error
    valid = check_flags_stats(case, input_flags(rho, periodic), record_property)
    check_numeric(case, grad, hess, valid)


@pytest.mark.parametrize("location", [(8, 8, 8), (0, 0, 0)])
def test_allowed_negative_exact_61_point_mask(library, location, record_property):
    rho = np.ones((17, 17, 17))
    rho[location] = -5e-12
    periodic = (True, True, True)
    case = Evaluation(rho, periodic=periodic)
    with library.context(options(negative_tolerance=1e-10)) as handle:
        status, error = library.run(handle, case)
    assert status == OK, error
    valid = check_flags_stats(case, input_flags(rho, periodic), record_property)
    assert np.count_nonzero(case.flags & STENCIL) == 61
    corner2 = tuple((np.array(location) - [2, 2, 0]) % 17)
    corner3 = tuple((np.array(location) - [2, 2, 2]) % 17)
    assert case.flags[corner2] & STENCIL
    assert not case.flags[corner3] & STENCIL
    grad, hess = fd4(rho, np.eye(3))
    check_numeric(case, grad, hess, valid)


@pytest.mark.parametrize("sign", [-1, 1])
def test_near_zero_lambda_keeps_nonzero_raw_signedrho(library, sign, record_property):
    # +/-1e-13 lies below the nominal 1e-12 uncertainty floor, but well above
    # density-rounding noise for this small exact polynomial. Neither eigenvalue
    # nor signedrho may be deliberately hard-zeroed inside an uncertainty band.
    h = np.diag([-1e-7, sign * 1e-13, 1e-7])
    rho, grad, hess = quadratic((9, 9, 9), np.eye(3), h,
                                origin=[-4, -4, -4], offset=1e-4)
    case = Evaluation(rho)
    with library.context() as handle:
        status, error = library.run(handle, case)
    assert status == OK, error
    valid = check_flags_stats(case, input_flags(rho), record_property)
    check_numeric(case, grad, hess, valid)
    assert np.all(np.sign(case.lambda2[valid]) == sign)
    assert np.all(np.abs(case.lambda2[valid]) < 1e-12)
    assert_array_equal(case.signedrho[valid], sign * rho[valid])


@pytest.mark.parametrize("spectrum", [(-0.2, -0.2, 0.5), (-0.5, 0.2, 0.2)])
def test_repeated_eigenvalues(library, spectrum, record_property):
    q, _ = np.linalg.qr(np.array([[1., 2, -1], [3, 1, 2], [2, -2, 3]]))
    h = q @ np.diag(spectrum) @ q.T
    rho, grad, hess = quadratic((7, 9, 11), SKEW, h)
    case = Evaluation(rho, SKEW)
    with library.context() as handle:
        status, error = library.run(handle, case)
    assert status == OK, error
    valid = check_flags_stats(case, input_flags(rho), record_property)
    check_numeric(case, grad, hess, valid)


@pytest.mark.parametrize("inverse", [np.diag([1., 1, 1/999]),
                                    np.array([[1., 31, 0], [0, 1, 0], [0, 0, 1]])],
                         ids=["spectral-condition-999", "spectral-963-infinity-1024"])
def test_spectral_condition_supported_cases(library, inverse, record_property):
    assert np.linalg.cond(inverse, 2) < 1000
    case = Evaluation(np.ones((5, 5, 5)))
    case.tile.j_inv[:] = inverse.ravel()
    with library.context() as handle:
        status, error = library.run(handle, case)
    assert status == OK, error
    check_flags_stats(case, input_flags(case.rho), record_property)


def test_openmp_threads_preserve_nontrivial_fields_flags_and_stats(library, record_property):
    # Correctness only: no clocks, scaling ratios or performance assertions.
    rho, grad, hess = periodic_fourier((9, 11, 13), SKEW,
        [(0.1, (1, 2, 1), 0.2), (0.08, (2, -1, 0), -0.4)])
    periodic = (True, True, True)
    expected_flags = input_flags(rho, periodic)
    baseline = None
    for threads in (1, 4, 16):
        case = Evaluation(rho, SKEW, periodic)
        with library.context(options(threads=threads)) as handle:
            status, error = library.run(handle, case)
        assert status == OK, (threads, error)
        valid = check_flags_stats(case, expected_flags, record_property)
        check_numeric(case, grad, hess, valid)
        record_property(f"omp_{threads}_valid_points", int(np.count_nonzero(valid)))
        if baseline is None:
            baseline = case
            continue
        assert_array_equal(case.flags, baseline.flags)
        assert bytes(case.stats) == bytes(baseline.stats)
        for field in ("grad", "hess", "lambda2"):
            assert_allclose(getattr(case, field), getattr(baseline, field),
                            atol=1e-12, rtol=1e-10)
        assert_allclose(case.rdg, baseline.rdg, atol=1e-11, rtol=1e-9)
        assert_array_equal(case.signedrho, baseline.signedrho)


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


def test_rdg_overflow_invalidates_all_diagnostic_outputs(library):
    # The only interior point passes density preflight and has finite g/H/eigen,
    # but its mathematically enormous RDG cannot be represented in binary64.
    rho = np.ones((5, 5, 5))
    rho[2, 2, 2], rho[3, 2, 2] = 1e-250, 2
    case = Evaluation(rho)
    with library.context(options(rho_min=1e-260)) as handle:
        status, error = library.run(handle, case)
    # A computed valid-path failure takes precedence over zero remaining valid
    # points; this is NUMERIC_FAILURE, not ordinary all-invalid INVALID_INPUT.
    assert status == NUMERIC_FAILURE, error
    expected_flags = input_flags(rho, rho_min=1e-260)
    expected_flags[2, 2, 2] |= FAILURE
    assert_array_equal(case.flags, expected_flags)
    for field in (case.rdg, case.signedrho, case.lambda2, case.grad, case.hess):
        assert np.all(np.isnan(field))
    assert case.stats.total_points == 125
    assert case.stats.valid_points == 0
    assert case.stats.invalid_points == 125
    assert case.stats.numeric_failures == 1
    for bit in range(7):
        assert case.stats.bit_counts[bit] == np.count_nonzero(expected_flags & (1 << bit))
    assert_array_equal(case.rho, rho)


def test_large_finite_rdg_avoids_intermediate_overflow(library, record_property):
    rho = finite_large_rdg_fixture()
    rational_grad, rational_hess = exact_center_derivatives(rho)
    expected_rdg = high_precision_rdg(float(rho[2, 2, 2]), rational_grad)
    record_property("rdg_reference_decimal_100_digits", str(expected_rdg))
    case = Evaluation(rho)
    with library.context(options(rho_min=1e-8)) as handle:
        status, error = library.run(handle, case)
    # The final result is representable: intermediate overflow is NOT a valid
    # reason to classify this finite positive-density interior point as failed.
    assert status == OK, error
    valid = check_flags_stats(case, input_flags(rho), record_property)
    assert np.count_nonzero(valid) == 1
    expected_grad = np.array([float(g) for g in rational_grad])
    expected_hess = np.array([[float(h) for h in row] for row in rational_hess])
    assert_allclose(case.grad[2, 2, 2], expected_grad, atol=1e-12, rtol=1e-10)
    assert_allclose(case.hess[2, 2, 2], pack_hessian(expected_hess),
                    atol=1e-12, rtol=1e-10)
    assert_allclose(case.lambda2[2, 2, 2], 0, atol=1e-12, rtol=1e-10)
    assert_allclose(case.rdg[2, 2, 2], float(expected_rdg), atol=1e-11, rtol=1e-9)
    assert_array_equal(case.rho, rho)


def test_subnormal_constant_with_large_isotropic_jinv_is_supported(library, record_property):
    # Construct binary64 subnormals by bit reinterpretation, never SCALE/scalbn.
    rho = np.full((5, 5, 5), np.uint64(0x10), dtype=np.uint64).view(np.float64)
    rho_min = np.array([0x1], dtype=np.uint64).view(np.float64)[0]
    zero = np.array([0x0], dtype=np.uint64).view(np.float64)[0]
    case = Evaluation(rho)
    case.tile.j_inv[:] = np.diag([1e308, 1e308, 1e308]).ravel()
    opts = options(rho_min=float(rho_min))
    assert int(case.rho.view(np.uint64)[2, 2, 2]) == 0x10
    assert int(np.array([opts.rho_min]).view(np.uint64)[0]) == 0x1
    record_property("rho_binary64_bits", "0x10")
    record_property("rho_min_binary64_bits", "0x1")
    with library.context(opts) as handle:
        status, error = library.run(handle, case)
    assert status == OK, error
    expected_inputs = np.ones((5, 5, 5), dtype=np.uint8)
    expected_inputs[2, 2, 2] = 0
    check_flags_stats(case, expected_inputs, record_property)
    expected_flags = expected_inputs.copy()
    expected_flags[2, 2, 2] = NUM_UNCERTAIN | SCI_UNCERTAIN
    assert_array_equal(case.flags, expected_flags)
    for field in (case.rdg, case.signedrho, case.lambda2, case.grad, case.hess):
        assert_array_equal(field[2, 2, 2], zero)
    assert_array_equal(case.rho.view(np.uint64), np.full((5, 5, 5), 0x10, dtype=np.uint64))


def test_subnormal_gradient_retains_positive_finite_rdg(library, record_property):
    rho_bits = np.full((5, 5, 5), np.uint64(0x10), dtype=np.uint64)
    rho_bits[0, 2, 2], rho_bits[4, 2, 2] = 0x16, 0x0A
    rho = rho_bits.view(np.float64)
    eta = np.array([0x1], dtype=np.uint64).view(np.float64)[0]
    rational_grad, rational_hess = exact_center_derivatives(rho)
    expected_rdg = high_precision_rdg(float(rho[2, 2, 2]), rational_grad)
    assert rational_grad == [Fraction.from_float(float(eta)), 0, 0]
    assert all(value == 0 for row in rational_hess for value in row)
    assert np.isfinite(float(expected_rdg)) and expected_rdg > 0
    record_property("rdg_reference_decimal_100_digits", str(expected_rdg))
    case = Evaluation(rho)
    with library.context(options(rho_min=float(eta))) as handle:
        status, error = library.run(handle, case)
    assert status == OK, error
    expected_inputs = np.ones((5, 5, 5), dtype=np.uint8)
    expected_inputs[2, 2, 2] = 0
    check_flags_stats(case, expected_inputs, record_property)
    assert int(case.grad[2, 2, 2, 0].view(np.uint64)) == 0x1
    assert_array_equal(case.grad[2, 2, 2, 1:], 0)
    assert_array_equal(case.hess[2, 2, 2], 0)
    assert case.lambda2[2, 2, 2] == case.signedrho[2, 2, 2] == 0
    assert case.flags[2, 2, 2] == NUM_UNCERTAIN | SCI_UNCERTAIN
    assert np.isfinite(case.rdg[2, 2, 2]) and case.rdg[2, 2, 2] > 0
    record_property("actual_rdg_binary64", repr(float(case.rdg[2, 2, 2])))
    # A normal absolute tolerance would let a spuriously zero result pass when
    # testing subnormal derivatives. Preserve the fixed relative RDG gate only.
    assert_allclose(case.rdg[2, 2, 2], float(expected_rdg), atol=0, rtol=1e-9)
    assert_array_equal(case.rho.view(np.uint64), rho_bits)


def test_optional_jacobi_nonconvergence_hook(library):
    # The public ABI deliberately has no test_max_rotations field. Do not guess
    # private symbol signatures or enable failure injection in production.
    pytest.skip("No standardized C test-only Jacobi hook in public v1 ABI; "
                "nonconvergence injection belongs to the core test-only CTest target")
