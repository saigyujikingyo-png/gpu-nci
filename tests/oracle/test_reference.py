"""Self-tests of the independent references; do not require libnci."""
import ctypes as ct
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from numpy.testing import assert_allclose
from scipy.linalg import eigvalsh

from reference.abi import Options, Tile, Stats
from reference.fields import (BOUNDARY, LOW, NONPOSITIVE, STENCIL, fd4,
                              gaussian, input_flags, pack_hessian,
                              periodic_fourier, quadratic, stencil_offsets,
                              RDG_DENOMINATOR)

ROOT = Path(__file__).resolve().parents[2]
SKEW = np.array([[0.3, 0.05, -0.02], [0.02, 0.24, 0.04], [0, -0.03, 0.2]])


def test_ctypes_layout():
    assert ct.sizeof(ct.c_void_p) == 8, "v1 tests require a 64-bit ABI"
    assert [ct.sizeof(x) for x in (Options, Tile, Stats)] == [40, 280, 88]
    assert Options.rho_min.offset == 24
    assert Tile.global_n.offset == 8
    assert Tile.j_inv.offset == 152
    assert Tile.periodic.offset == 224
    assert Tile.rho_capacity.offset == 240
    assert Tile.hess_capacity.offset == 272
    assert Stats.bit_counts.offset == 32


def test_ctypes_matches_public_c_header(tmp_path):
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("C compiler unavailable: public-header ABI probe NOT RUN")
    structs = {"options": ("nci_options_v1", Options),
               "tile": ("nci_tile_v1", Tile), "stats": ("nci_tile_stats_v1", Stats)}
    statements = []
    expected = {}
    for label, (c_name, py_type) in structs.items():
        expected[f"{label}.size"] = ct.sizeof(py_type)
        statements.append(f'printf("{label}.size %zu\\n", sizeof({c_name}));')
        for name, _ in py_type._fields_:
            expected[f"{label}.{name}"] = getattr(py_type, name).offset
            statements.append(f'printf("{label}.{name} %zu\\n", offsetof({c_name}, {name}));')
    source = '#include <stdio.h>\n#include "nci_api.h"\nint main(void) {\n'
    source += "\n".join(statements) + "\nreturn 0;\n}\n"
    c_file, executable = tmp_path / "layout.c", tmp_path / "layout"
    c_file.write_text(source, encoding="utf-8")
    subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-I", str(ROOT / "include"), str(c_file), "-o", str(executable)],
                   check=True, capture_output=True, text=True, timeout=20)
    result = subprocess.run([str(executable)], check=True, capture_output=True,
                            text=True, timeout=5)
    observed = {k: int(v) for k, v in (line.split() for line in result.stdout.splitlines())}
    assert observed == expected, json.dumps(observed)


@pytest.mark.parametrize("left_handed", [False, True])
def test_polynomial_fd_reference_is_analytic(left_handed):
    j = SKEW.copy()
    if left_handed:
        j[:, 0] *= -1
    h = np.array([[-0.4, 0.08, 0.03], [0.08, 0.2, -0.04], [0.03, -0.04, 0.5]])
    rho, grad, hess = quadratic((7, 9, 11), j, h, linear=[0.1, -0.2, 0.3],
                                origin=[-0.4, 0.3, -0.2])
    actual_g, actual_h = fd4(rho, j)
    interior = np.s_[2:-2, 2:-2, 2:-2]
    assert_allclose(actual_g[interior], grad[interior], atol=1e-12, rtol=1e-10)
    assert_allclose(actual_h[interior], hess[interior], atol=1e-12, rtol=1e-10)
    assert pack_hessian(hess).shape == (*rho.shape, 6)


def test_periodic_symbols_match_independent_rolled_stencil():
    rho, grad, hess = periodic_fourier((9, 11, 13), SKEW,
        [(0.1, (1, 2, 1), 0.2), (0.08, (2, -1, 0), -0.4)])
    actual_g, actual_h = fd4(rho, SKEW)
    assert_allclose(actual_g, grad, atol=1e-12, rtol=1e-10)
    assert_allclose(actual_h, hess, atol=1e-12, rtol=1e-10)


@pytest.mark.parametrize("location", [(8, 8, 8), (0, 0, 0)])
def test_exact_stencil_and_negative_mask(location):
    offsets = stencil_offsets()
    assert len(offsets) == 61
    assert (2, 2, 0) in offsets
    assert (2, 2, 2) not in offsets
    rho = np.ones((17, 17, 17))
    rho[location] = -1e-12
    flags = input_flags(rho, periodic=(True, True, True))
    assert np.count_nonzero(flags & STENCIL) == 61
    assert flags[location] == NONPOSITIVE | STENCIL
    corner2 = tuple((np.array(location) - [2, 2, 0]) % 17)
    corner3 = tuple((np.array(location) - [2, 2, 2]) % 17)
    assert flags[corner2] == STENCIL
    assert flags[corner3] == 0


@pytest.mark.parametrize("sign", [-1, 1])
def test_near_zero_polynomial_fixture_resolves_both_signs(sign):
    h = np.diag([-1e-7, sign * 1e-13, 1e-7])
    rho, _, _ = quadratic((9, 9, 9), np.eye(3), h,
                          origin=[-4, -4, -4], offset=1e-4)
    _, discrete_hess = fd4(rho, np.eye(3))
    center = discrete_hess[2:-2, 2:-2, 2:-2].reshape(-1, 3, 3)
    middle = np.array([eigvalsh(matrix, driver="evr")[1] for matrix in center])
    assert np.all(np.sign(middle) == sign)
    assert_allclose(middle, sign * 1e-13, atol=5e-19, rtol=0)


def test_condition_fixtures_discriminate_spectral_from_infinity_norm():
    assert_allclose(np.linalg.cond(np.diag([1., 1, 1/999]), 2), 999)
    assert_allclose(np.linalg.cond(np.diag([1., 1, 1/1001]), 2), 1001)
    shear = np.array([[1., 31, 0], [0, 1, 0], [0, 0, 1]])
    assert 960 < np.linalg.cond(shear, 2) < 965
    assert np.linalg.cond(shear, np.inf) == 1024


def test_overflow_fixture_would_evade_a_wrapped_capacity_check():
    product = (2**62 + 1) * 8 * 5
    assert product > 2**63 - 1
    assert product % 2**64 == 40
    assert 40 < 125 and 3 * 40 < 375 and 6 * 40 < 750


def test_rdg_overflow_fixture_has_finite_derivatives_and_nonfinite_rdg():
    rho = np.ones((5, 5, 5))
    rho[2, 2, 2], rho[3, 2, 2] = 1e-250, 2
    grad, hess = fd4(rho, np.eye(3))
    center = (2, 2, 2)
    assert input_flags(rho, rho_min=1e-260)[center] == 0
    assert_allclose(grad[center], [2/3, 0, 0], atol=1e-15, rtol=0)
    assert_allclose(hess[center], np.diag([23/6, 2.5, 2.5]), atol=1e-14, rtol=0)
    assert np.all(np.isfinite(eigvalsh(hess[center], driver="evr")))
    with np.errstate(over="ignore", under="ignore", divide="ignore"):
        rdg = np.linalg.norm(grad[center]) / (RDG_DENOMINATOR * rho[center]**(4/3))
    assert np.isinf(rdg)


def test_zero_and_low_are_not_invalid_stencil_samples():
    rho = np.ones((9, 9, 9))
    rho[3, 4, 4], rho[5, 4, 4] = 0, 0.1
    flags = input_flags(rho, (True, True, True), rho_min=0.2)
    assert flags[3, 4, 4] == NONPOSITIVE
    assert flags[5, 4, 4] == LOW
    assert not np.any(flags & STENCIL)
    assert not np.any(flags & BOUNDARY)


def test_gaussian_analytic_gradient_and_hessian():
    # Analytic identity checked against complex-step differentiation, not FD4.
    b = np.array([[0.7, 0.1, 0.04], [0.1, 0.5, -0.03], [0.04, -0.03, 0.9]])
    r = np.array([0.2, -0.3, 0.4])
    _, grad, hess = gaussian((1, 1, 1), np.eye(3), b, origin=r)
    complex_grad = np.empty(3)
    complex_hess = np.empty((3, 3))
    for axis in range(3):
        z = r.astype(complex)
        z[axis] += 1e-25j
        value = np.exp(-z @ b @ z)
        complex_grad[axis] = value.imag / 1e-25
        complex_hess[:, axis] = (-2 * value * (b @ z)).imag / 1e-25
    assert_allclose(grad[0, 0, 0], complex_grad, rtol=2e-15, atol=1e-15)
    assert_allclose(hess[0, 0, 0], complex_hess, rtol=2e-15, atol=1e-15)


@pytest.mark.parametrize("spectrum", [(-2, -1, 3), (-3, 1, 2), (-1, 0, 2),
                                        (0, 0, 0), (1, 1, 1), (-1, 1e-14, 1)])
def test_lapack_against_rotated_known_spectra(spectrum):
    q, _ = np.linalg.qr(np.array([[1., 2, -1], [3, 1, 2], [2, -2, 3]]))
    h = q @ np.diag(spectrum) @ q.T
    assert_allclose(eigvalsh(h, driver="evr"), spectrum, atol=3e-15, rtol=2e-15)
    assert_allclose(np.linalg.eigvalsh(h), spectrum, atol=3e-15, rtol=2e-15)
