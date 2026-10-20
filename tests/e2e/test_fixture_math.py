"""Fixture-only checks never claim an implemented CLI-to-native pipeline."""
import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from fixtures import (H, J, ORIGIN, SHAPE, cube_text, fourier_fixture,
                      overflow_fixture, quadratic_fixture, write_case)
from reference.fields import BOUNDARY, LOW, fd4


def test_quadratic_fixture_has_independent_derivatives_and_two_mask_classes():
    field = quadratic_fixture()
    assert field.rho.shape == SHAPE
    assert np.linalg.det(J) != 0
    assert not np.allclose(J, J.T)
    assert np.all(ORIGIN != 0)
    flags = field.expected_flags()
    assert np.count_nonzero(flags == 0) > 0
    assert np.count_nonzero(((flags & LOW) != 0) & ((flags & BOUNDARY) == 0)) > 0
    valid = (flags & 15) == 0
    grad, hess = fd4(field.rho, J)
    assert_allclose(grad[valid], field.gradient[valid], atol=1e-12, rtol=1e-10)
    assert_allclose(hess[valid], field.hessian[valid], atol=1e-12, rtol=1e-10)
    assert_allclose(field.hessian[3, 4, 5], H, atol=0, rtol=0)


def test_fourier_fixture_discrete_symbols_and_mixed_boundaries():
    field = fourier_fixture()
    valid = field.expected_flags() == 0
    assert np.count_nonzero(valid) == 7*5*11
    grad, hess = fd4(field.rho, field.jacobian)
    assert_allclose(grad[valid], field.gradient[valid], atol=1e-12, rtol=1e-10)
    assert_allclose(hess[valid], field.hessian[valid], atol=1e-12, rtol=1e-10)


def test_cube_writer_roundtrips_samples_and_lists_column_vectors():
    field = quadratic_fixture()
    lines = cube_text(field).splitlines()
    assert_allclose([float(x) for x in lines[2].split()[1:4]], ORIGIN, atol=0, rtol=0)
    for axis in range(3):
        tokens = lines[axis+3].split()
        assert int(tokens[0]) == SHAPE[axis]
        assert_array_equal([float(x) for x in tokens[1:]], J[:, axis])
    serialized = np.array([float(x) for line in lines[6:] for x in line.split()])
    assert_array_equal(serialized.reshape(SHAPE, order="C"), field.rho)


def test_card_source_binding_and_relative_path(tmp_path):
    from fixtures import sha256
    _, cube, path, card = write_case(tmp_path)
    assert path.parent / card["input"]["path"] == cube
    assert card["input"]["bytes"] == cube.stat().st_size
    assert card["input"]["sha256"] == sha256(cube)
    assert card["grid"]["step_vectors"] == J.T.tolist()


def test_overflow_fixture_is_not_a_preflight_density_rejection():
    field = overflow_fixture()
    assert field.rho[2, 2, 2] > field.rho_min > 0
    assert np.all(np.isfinite(field.rho))
    assert field.expected_flags()[2, 2, 2] == 0
