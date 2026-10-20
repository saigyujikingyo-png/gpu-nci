"""Real CLI slab acceptance with independently authored cards and CUBE input."""
import subprocess

import numpy as np
import pytest
from numpy.testing import assert_array_equal

from checks import failed, invoke, json_object, load_and_check_fields
from fixtures import (Fixture, fourier_fixture, overflow_fixture, quadratic_fixture,
                      sha256, write_card, write_case)
from reference.fields import fd4, periodic_fourier


def slab_budget(shape, block, mode, threads=1, atom_bytes=0):
    """Frozen contract arithmetic, independent of production card validation."""
    nx, ny, nz = shape
    n, p, q = nx * ny * nz, ny * nz, 97 if mode == "diagnostic" else 25
    return (8*n + 8*(block+4)*p + q*block*p + 40*(block+ny+nz)
            + 8192 + atom_bytes + 65536 + 4096*threads)


def remote_bad_fixture(bad):
    field = fourier_fixture()
    location = (3, field.rho.shape[1]-1, field.rho.shape[2]-1)
    # Nx7, periodic X, first B1 slab: global planes [5,6,0,1,2].
    # The bad sample must not be visible to a buggy first-slab-only preflight.
    first_halo = [(x % field.rho.shape[0]) for x in range(-2, 3)]
    assert location[0] not in first_halo
    field.rho[location] = bad
    return field, location


def as_slabs(path, card, block):
    card["compute"].update(layout="x_slabs", slab_planes=block)
    write_card(path, card)


def check_success(completed, output, card, fixture, mode):
    assert completed.returncode == 0, completed.stdout + completed.stderr
    manifest = json_object(output / "manifest.json")
    native = json_object(output / "native.json")
    assert manifest["state"] == "completed_numerical"
    assert manifest["stage"] == "complete"
    assert manifest["native"] == native
    assert native["state"] == "completed" and native["abi_status"] == 0
    assert manifest["compute"] == card["compute"]
    assert (output / "SUCCESS").read_bytes() == (sha256(output / "manifest.json") + "\n").encode()
    _, specs = load_and_check_fields(output, fixture, mode, native)
    assert set(manifest["outputs"]) == set(specs) | {"flags.u8"}
    for name, record in manifest["outputs"].items():
        assert record["sha256"] == sha256(output / name)
        assert record["bytes"] == (output / name).stat().st_size
        shape = list(fixture.rho.shape)
        if name in ("grad.f64", "hess.f64"):
            shape += [3 if name == "grad.f64" else 6]
        assert record["shape"] == shape
    return manifest


@pytest.mark.parametrize("make_field", [quadratic_fixture, fourier_fixture])
@pytest.mark.parametrize("mode", ["full", "diagnostic"])
@pytest.mark.parametrize("block", [1, 3, 4, 7])
def test_real_slab_cli_matches_full_raw_receipts(executables, tmp_path, make_field, mode, block):
    fixture, cube, path, card = write_case(tmp_path, make_field(), mode)
    original_cube = cube.read_bytes()
    full_completed, full_output = invoke(executables, tmp_path, cube, path,
                                         output=tmp_path / "full results")
    full = check_success(full_completed, full_output, card, fixture, mode)
    as_slabs(path, card, block)
    completed, output = invoke(executables, tmp_path, cube, path,
                                output=tmp_path / "slab results")
    manifest = check_success(completed, output, card, fixture, mode)
    # Frozen same-build bitwise finite gate, with separate NaN masks.
    for name in full["outputs"]:
        if name == "flags.u8":
            assert (output / name).read_bytes() == (full_output / name).read_bytes()
        else:
            actual = np.fromfile(output / name, dtype="<f8")
            expected = np.fromfile(full_output / name, dtype="<f8")
            assert_array_equal(np.isnan(actual), np.isnan(expected))
            valid = np.isfinite(expected)
            assert_array_equal(actual[valid].view(np.uint64), expected[valid].view(np.uint64))
        # Equal hashes also check canonical NaN serialization and complete files.
        assert manifest["outputs"][name] == full["outputs"][name]
    for key in ("abi_status", "npoints", "stats", "state"):
        assert manifest["native"][key] == full["native"][key]
    assert manifest["build"] == full["build"]
    assert manifest["grid"] == full["grid"]
    assert cube.read_bytes() == original_cube


@pytest.mark.parametrize("threads", [1, 2, 4])
def test_real_slab_cli_exact_budget_boundary(executables, tmp_path, threads):
    field, cube, path, card = write_case(tmp_path, fourier_fixture())
    card["compute"]["omp_threads"] = threads
    card["limits"]["memory_budget_bytes"] = slab_budget(field.rho.shape, 3, "diagnostic", threads)
    as_slabs(path, card, 3)
    completed, output = invoke(executables, tmp_path, cube, path)
    check_success(completed, output, card, field, "diagnostic")


@pytest.mark.parametrize("block", [1, 3, 5])
def test_real_slab_cli_nx5_negative_periodic_corner(executables, tmp_path, block):
    field = fourier_fixture()
    field.rho, _, _ = periodic_fourier((5, 7, 9), field.jacobian,
                                       [(.1, (1, 2, 1), .2)])
    field.periodic = (1, 1, 1)
    field.rho[0, 0, 0] = -5e-12
    field.gradient, field.hessian = fd4(field.rho, field.jacobian)
    _, cube, path, card = write_case(tmp_path, field)
    card["compute"]["negative_tolerance"] = 1e-10
    write_card(path, card)
    completed_full, output_full = invoke(executables, tmp_path, cube, path,
                                         output=tmp_path / "full results")
    full = check_success(completed_full, output_full, card, field, "diagnostic")
    as_slabs(path, card, block)
    completed, output = invoke(executables, tmp_path, cube, path)
    manifest = check_success(completed, output, card, field, "diagnostic")
    assert manifest["outputs"] == full["outputs"]
    assert manifest["native"]["stats"] == full["native"]["stats"]


def test_native_slab_budget_lower_bound_cannot_be_bypassed(executables, tmp_path):
    field, cube, path, card = write_case(tmp_path, fourier_fixture())
    required = slab_budget(field.rho.shape, 3, "diagnostic")
    card["limits"]["memory_budget_bytes"] = required
    as_slabs(path, card, 3)
    completed, output = invoke(executables, tmp_path, cube, path)
    check_success(completed, output, card, field, "diagnostic")
    # Exercise the real native worker independently of the Python lower bound.
    settings = (output / "settings.nml").read_text(encoding="ascii")
    old = f"memory_budget_bytes = {required}"
    assert settings.count(old) == 1
    native_settings = tmp_path / "one byte below.nml"
    native_settings.write_text(settings.replace(old, f"memory_budget_bytes = {required-1}"),
                               encoding="ascii")
    destination = tmp_path / "native budget rejection"
    destination.mkdir()
    source = cube.read_bytes()
    completed = subprocess.run([str(executables["NCI_DRIVER"]), str(cube),
        str(native_settings), str(destination)], capture_output=True, text=True, timeout=30)
    assert completed.returncode != 0, completed.stdout + completed.stderr
    assert cube.read_bytes() == source
    assert not (destination / "SUCCESS").exists()
    native = json_object(destination / "native.json")
    assert native["state"] == "failed"
    assert any(word in (native["message"] + native["stage"]).lower()
               for word in ("memory", "budget", "alloc", "reserv"))
    assert not list(destination.glob("*.f64"))
    assert not (destination / "flags.u8").exists()


@pytest.mark.parametrize("mode", ["full", "diagnostic"])
def test_real_slab_cli_one_byte_below_budget_rejected_before_snapshot(executables, tmp_path, mode):
    field, cube, path, card = write_case(tmp_path, mode=mode)
    card["limits"]["memory_budget_bytes"] = slab_budget(field.rho.shape, 3, mode) - 1
    as_slabs(path, card, 3)
    completed, output = invoke(executables, tmp_path, cube, path)
    manifest = failed(completed, output)
    assert manifest["stage"] == "card"
    assert not (output / "input.cube").exists()
    assert manifest["worker"] is None


@pytest.mark.parametrize("mutation", ["missing", "bool", "float", "zero", "negative",
    "too_large", "null", "extra", "full_forbidden", "unknown_layout"])
def test_real_cli_slab_card_legality(executables, tmp_path, mutation):
    _, cube, path, card = write_case(tmp_path)
    card["compute"].update(layout="x_slabs", slab_planes=3)
    if mutation == "missing":
        del card["compute"]["slab_planes"]
    elif mutation == "extra":
        card["compute"]["unexpected"] = 1
    elif mutation == "full_forbidden":
        card["compute"]["layout"] = "full_grid"
    elif mutation == "unknown_layout":
        card["compute"]["layout"] = "y_slabs"
    else:
        card["compute"]["slab_planes"] = dict(bool=True, float=3.0, zero=0,
            negative=-1, too_large=8, null=None)[mutation]
    write_card(path, card)
    completed, output = invoke(executables, tmp_path, cube, path)
    manifest = failed(completed, output)
    assert manifest["stage"] == "card"
    assert manifest["worker"] is None


@pytest.mark.parametrize("shape,block", [([2**59, 5, 5], 1), ([2**55, 5, 5], 2**55),
                                         ([5, 2**28, 2**28], 1)])
def test_real_slab_cli_budget_overflow_is_card_failure(executables, tmp_path, shape, block):
    _, cube, path, card = write_case(tmp_path)
    card["grid"]["shape"] = shape
    card["limits"].update(max_points=2**63-1, memory_budget_bytes=2**63-1)
    as_slabs(path, card, block)
    completed, output = invoke(executables, tmp_path, cube, path)
    manifest = failed(completed, output)
    assert manifest["stage"] == "card"
    assert manifest["worker"] is None


@pytest.mark.parametrize("bad", [float("nan"), -1e-3])
def test_remote_bad_density_rejected_before_first_slab_output(executables, tmp_path, bad):
    field, _ = remote_bad_fixture(bad)
    _, cube, path, card = write_case(tmp_path, field)
    as_slabs(path, card, 1)
    completed, output = invoke(executables, tmp_path, cube, path)
    manifest = failed(completed, output)
    assert manifest["worker"] is not None
    assert manifest["native"]["state"] == "failed"
    for name in ("rdg.f64", "lambda2.f64", "signedrho.f64", "grad.f64", "hess.f64", "flags.u8"):
        assert not (output / name).exists(), name


def test_global_all_invalid_slab_run_has_no_success(executables, tmp_path):
    field = Fixture(np.full((5, 7, 9), 1e-10), None, None, np.zeros(3), np.eye(3),
                    (0, 0, 0), 1e-8, "all invalid slabs v1")
    _, cube, path, card = write_case(tmp_path, field)
    as_slabs(path, card, 1)
    completed, output = invoke(executables, tmp_path, cube, path)
    native = failed(completed, output)["native"]
    assert native["abi_status"] == 3
    assert native["npoints"] == field.rho.size
    assert native["stats"]["total"] == native["stats"]["invalid"] == field.rho.size
    assert native["stats"]["valid"] == native["stats"]["numeric_failures"] == 0
    assert native["stats"]["bit_counts"][:5] == [
        int(np.count_nonzero(field.expected_flags() & (1 << bit))) for bit in range(5)]


def test_numeric_failure_slab_run_stops_and_counts_evaluated_slab(executables, tmp_path):
    field, cube, path, card = write_case(tmp_path, overflow_fixture())
    as_slabs(path, card, 1)
    completed, output = invoke(executables, tmp_path, cube, path)
    native = failed(completed, output)["native"]
    assert native["abi_status"] == 4
    assert native["npoints"] == 125
    assert native["stats"]["total"] == native["stats"]["invalid"] == 75
    assert native["stats"]["numeric_failures"] == 1
    assert native["stats"]["valid"] == 0
    # ABI4 bytes are allowed to be absent; even if retained they cannot be global completion.
    for name, width in (("rdg.f64", 8), ("lambda2.f64", 8), ("signedrho.f64", 8),
                        ("flags.u8", 1), ("grad.f64", 24), ("hess.f64", 48)):
        if (output / name).exists():
            assert (output / name).stat().st_size <= 75 * width
