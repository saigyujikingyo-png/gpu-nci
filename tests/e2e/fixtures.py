"""Pinned public synthetic CUBE/card authoring, independent of reader/adapter.

The merged reference.fields module is the independent oracle, not production.
All fields are <= 11^3 samples; no electronic structure or benchmarks.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import numpy as np

from reference.fields import input_flags, nci, periodic_fourier, quadratic

SHAPE = (7, 9, 11)
ORIGIN = np.array([0.375, -0.5, 0.625])
J = np.array([[0.25, 0.0625, -0.03125],
              [0.015625, 0.1875, 0.046875],
              [0.0, -0.03125, 0.21875]])
H = np.array([[-0.25, 0.0625, -0.03125],
              [0.0625, 0.125, 0.046875],
              [-0.03125, 0.046875, 0.375]])
LINEAR = np.array([0.125, -0.0625, 0.1875])
RHO_MIN_QUADRATIC = 4.5
MODES = [(0.05, (1, 2, 1), 0.2), (0.03, (2, -1, 0), -0.4)]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass
class Fixture:
    rho: np.ndarray
    gradient: np.ndarray | None
    hessian: np.ndarray | None
    origin: np.ndarray
    jacobian: np.ndarray
    periodic: tuple
    rho_min: float
    label: str

    def expected_flags(self):
        return input_flags(self.rho, self.periodic, self.rho_min)

    def numerical_reference(self):
        valid = (self.expected_flags() & 15) == 0
        return valid, nci(self.rho[valid], self.gradient[valid], self.hessian[valid])


def quadratic_fixture():
    rho, grad, hess = quadratic(SHAPE, J, H, linear=LINEAR, origin=ORIGIN, offset=4)
    return Fixture(rho, grad, hess, ORIGIN.copy(), J.copy(), (0, 0, 0),
                   RHO_MIN_QUADRATIC, "pinned mixed quadratic v1")


def fourier_fixture():
    rho, grad, hess = periodic_fourier(SHAPE, J, MODES)
    return Fixture(rho, grad, hess, ORIGIN.copy(), J.copy(), (1, 0, 1),
                   1e-8, "pinned mixed-periodic discrete Fourier v1")


def overflow_fixture():
    rho = np.ones((5, 5, 5))
    rho[2, 2, 2], rho[3, 2, 2] = 1e-250, 2
    return Fixture(rho, None, None, np.zeros(3), np.eye(3), (0, 0, 0),
                   1e-260, "binary64 RDG overflow v1")


def cube_text(fixture):
    # N_atoms=0 is the explicitly permitted synthetic format. No production
    # writer or parser is imported; .17g round-trips the binary64 input samples.
    vector = lambda v: " ".join(format(float(x), ".17g") for x in v)
    lines = ["GPU-NCI independent public synthetic fixture", fixture.label,
             "0 " + vector(fixture.origin) + " 1"]
    for axis, count in enumerate(fixture.rho.shape):
        lines.append(str(count) + " " + vector(fixture.jacobian[:, axis]))
    values = fixture.rho.ravel(order="C")
    for start in range(0, len(values), 6):
        lines.append(vector(values[start:start+6]))
    return "\n".join(lines) + "\n"


def write_case(parent, fixture=None, mode="diagnostic"):
    fixture = quadratic_fixture() if fixture is None else fixture
    folder = parent / "card and source"
    folder.mkdir()
    cube = folder / "density input.cube"
    cube.write_text(cube_text(fixture), encoding="ascii", newline="\n")
    card = {
        "schema_version": 1,
        "input": {"path": cube.name, "sha256": sha256(cube), "bytes": cube.stat().st_size,
                  "source": {"kind": "synthetic", "reference": fixture.label,
                      "permission": "generated for this public unit test",
                      "producer": "independent-e2e-fixtures", "producer_version": "1",
                      "settings": "pinned tests/e2e/fixtures.py; no solver",
                      "density_precision": "17 significant digits, binary64 round-trip"}},
        "grid": {"shape": list(fixture.rho.shape), "origin": fixture.origin.tolist(),
                 "step_vectors": fixture.jacobian.T.tolist(), "axis_order": "z_fastest"},
        "metadata": {"quantity": "electron_density", "spin_convention": "spin_summed",
                     "density_representation": "all_electron", "length_unit": "bohr",
                     "density_unit": "electron/bohr^3", "periodic": list(fixture.periodic),
                     "endpoint_convention": ["independent_samples" if p else "finite_nodes"
                                             for p in fixture.periodic]},
        "compute": {"backend": "cpu", "layout": "full_grid", "output_mode": mode,
                    "rho_min": fixture.rho_min, "negative_tolerance": 0.0, "omp_threads": 1},
        "limits": {"memory_budget_bytes": 16*1024*1024, "max_points": 100000,
                   "timeout_seconds": 20}}
    path = folder / "execution card.json"
    write_card(path, card)
    return fixture, cube, path, card


def write_card(path, card):
    path.write_text(json.dumps(card, indent=2, allow_nan=True) + "\n", encoding="utf-8")
