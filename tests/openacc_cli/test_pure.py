"""Source-independent bounded-plan and receipt-checker regressions; no drivers."""
import numpy as np
import pytest

from fixtures import Fixture, sha256, write_case
from openacc_support import (add_atoms, candidate_starts, check_plan, cpu_gpu_fields, field_fixture,
                             memory_plan, tile_terms)
from reference.fields import fd4


@pytest.mark.parametrize("mode", ["full", "diagnostic"])
@pytest.mark.parametrize("periodic_x", [False, True])
def test_four_candidate_max_matches_explicit_small_grid_enumeration(mode, periodic_x):
    # Fixed finite range exercises B1, short final slabs and all halo regimes.
    for nx in range(5, 42):
        for block in range(1, nx+1):
            starts = candidate_starts(nx, block)
            assert 1 <= len(starts) <= 4
            all_terms = [tile_terms((nx, 7, 9), mode, block, s, periodic_x) for s in range(0, nx, block)]
            chosen = [tile_terms((nx, 7, 9), mode, block, s, periodic_x) for s in starts]
            assert max(t[0] for t in chosen) == max(t[0] for t in all_terms)
            for index in range(9):
                assert max(t[1][index] for t in chosen) == max(t[1][index] for t in all_terms)


@pytest.mark.parametrize("mode,q,k", [("full", 25, 37), ("diagnostic", 97, 109)])
def test_explicit_host_terms_no_double_count(mode, q, k):
    # Nx7 Ny9 Nz11 B3: middle tile s3 has two left/one right finite halos.
    w = 8*6*99 + 40*(3+9+11) + k*3*99
    expected = 8*693 + 96 + 8192 + q*297 + 8*7*99 + w + 65536+8192 + 65536
    plan = memory_plan((7,9,11), mode, False, 3, threads=2, atom_bytes=96)
    assert plan["host_bytes"] == expected
    assert plan["device_array_bytes"] == w
    assert plan["reader_atom_bytes"] == 96
    assert plan["host_fixed_openacc_bytes"] == 65536


def test_full_periodic_has_no_caller_halo_and_no_slab_retention():
    plan = memory_plan((7,9,11), "diagnostic", True)
    w = 8*693 + 40*27 + 109*693
    assert plan["device_array_bytes"] == w
    assert plan["host_bytes"] == 8*693+8192+97*693+w+65536+4096+65536


@pytest.mark.parametrize("mutation", ["missing", "extra", "bool", "float", "negative", "overflow", "undercharge"])
def test_memory_receipt_checker_rejects_malformed_or_underreported(mutation):
    expected = memory_plan((7,9,11), "diagnostic", True, 3)
    actual = dict(expected)
    if mutation == "missing":
        actual.pop("reader_atom_bytes")
    elif mutation == "extra":
        actual["not_in_contract"] = 0
    else:
        actual["host_bytes"] = dict(bool=True, float=float(expected["host_bytes"]), negative=-1,
            overflow=2**63, undercharge=expected["host_bytes"]-1)[mutation]
    with pytest.raises(AssertionError):
        check_plan(actual, expected)


def test_large_contract_oracle_does_not_wrap_or_enumerate_tiles():
    assert len(candidate_starts(2**62, 1)) <= 4
    assert memory_plan((2**62,5,5), "diagnostic", True, 1)["host_bytes"] > 2**63-1
    _, objects = tile_terms((5,5,894785), "diagnostic", 5, 0, False, False)
    assert objects[4] > 2**31-1


@pytest.mark.parametrize("key", list(memory_plan((7,9,11), "full", False)))
def test_every_memory_term_is_checked_exactly(key):
    expected = memory_plan((7,9,11), "full", False)
    actual = dict(expected)
    actual[key] += 1
    with pytest.raises(AssertionError):
        check_plan(actual, expected)


def test_atom_writer_preserves_density_and_updates_original_binding(tmp_path):
    field, cube, path, card = write_case(tmp_path)
    density = cube.read_text().splitlines()[6:]
    add_atoms(cube, path, card)
    lines = cube.read_text().splitlines()
    assert lines[2].split()[0] == "2"
    assert len(lines[6:8]) == 2 and all(line.startswith("1 1.0 ") for line in lines[6:8])
    assert lines[8:] == density
    assert card["input"]["sha256"] == sha256(cube)
    assert card["input"]["bytes"] == cube.stat().st_size


@pytest.mark.parametrize("boundary", ["finite", "periodic", "mixed"])
def test_all_boundary_oracles_have_valid_samples_and_independent_fd4(boundary):
    field = field_fixture(boundary)
    valid = (field.expected_flags() & 15) == 0
    assert np.any(valid)
    grad, hess = fd4(field.rho, field.jacobian)
    np.testing.assert_allclose(grad[valid], field.gradient[valid], atol=1e-12, rtol=1e-10)
    np.testing.assert_allclose(hess[valid], field.hessian[valid], atol=1e-12, rtol=1e-10)


def test_cross_backend_uncertainty_semantics_do_not_strengthen_original_contract(tmp_path):
    field = Fixture(np.ones((5,5,5)), np.zeros((5,5,5,3)), np.zeros((5,5,5,3,3)),
                    np.zeros(3), np.eye(3), (1,1,1), 1e-8, "invented flat comparison")
    cpu, gpu = tmp_path/"cpu", tmp_path/"gpu"
    cpu.mkdir(); gpu.mkdir()
    for folder, bit5, sign in ((cpu, 32, -1), (gpu, 0, 1)):
        np.full(125, 64|bit5, dtype="u1").tofile(folder/"flags.u8")
        np.full(125, sign*1e-13, dtype="<f8").tofile(folder/"lambda2.f64")
        np.full(125, sign, dtype="<f8").tofile(folder/"signedrho.f64")
    names = ("flags.u8", "lambda2.f64", "signedrho.f64")
    cpu_gpu_fields(cpu, gpu, names, field)
    flags = np.fromfile(gpu/"flags.u8", dtype="u1")
    flags[0] |= 4
    flags.tofile(gpu/"flags.u8")
    with pytest.raises(AssertionError):
        cpu_gpu_fields(cpu, gpu, names, field)


def test_cross_backend_stable_reference_sign_remains_exact(tmp_path):
    field = field_fixture("finite")
    cpu, gpu = tmp_path/"cpu", tmp_path/"gpu"
    cpu.mkdir(); gpu.mkdir()
    valid, (_, signedrho, eigen) = field.numerical_reference()
    assert np.all(np.abs(eigen) > 1e-9)
    raw = np.full(field.rho.shape, np.nan)
    raw[valid] = signedrho
    raw.astype("<f8").tofile(cpu/"signedrho.f64")
    raw.astype("<f8").tofile(gpu/"signedrho.f64")
    cpu_gpu_fields(cpu, gpu, ("signedrho.f64",), field)
    raw[valid] *= -1
    raw.astype("<f8").tofile(gpu/"signedrho.f64")
    with pytest.raises(AssertionError):
        cpu_gpu_fields(cpu, gpu, ("signedrho.f64",), field)


@pytest.mark.parametrize("binaries", [None, {}, {"driver": {"path": "/fixture/gpu-worker"}}])
def test_run_preserves_early_failure_with_nullable_binaries(monkeypatch, tmp_path, binaries):
    import json
    from pathlib import Path
    from types import SimpleNamespace
    import openacc_support
    from checks import failed
    output = tmp_path/"early-failure"
    output.mkdir()
    manifest = dict(schema_version=1, state="failed", stage="card", message="invented refusal",
                    outputs={}, binaries=binaries, native=None)
    (output/"manifest.json").write_text(json.dumps(manifest))
    result = SimpleNamespace(returncode=1, stdout="", stderr="")
    monkeypatch.setattr(openacc_support, "invoke", lambda *a, **k: (result, output))
    exes = {"NCI_DRIVER": Path("/fixture/cpu-worker"), "NCI_OPENACC_DRIVER": Path("/fixture/gpu-worker")}
    actual, folder = openacc_support.run(exes, tmp_path, tmp_path/"cube", tmp_path/"card", {}, "failed")
    assert failed(actual, folder) == manifest
    evidence = json.loads((tmp_path/"failed.evidence.json").read_text())
    assert evidence["returncode"] == 1
    assert evidence["artifacts"]["manifest.json"]["sha256"] == sha256(output/"manifest.json")


def test_native_option_guard_precedes_dependency_and_input_actions(monkeypatch):
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace
    path = Path(__file__).with_name("conftest.py")
    spec = importlib.util.spec_from_file_location("independent_native_option_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    actions = []
    def forbidden_dependency(name):
        actions.append(name)
        raise AssertionError("native dependency requested without opt-in")
    for name in ("NCI_DRIVER", "NCI_OPENACC_DRIVER", "NCI_CLI", "NCI_CUBE_ATOM_BYTES"):
        monkeypatch.setenv(name, "configured-but-must-not-be-inspected")
    request = SimpleNamespace(config=SimpleNamespace(getoption=lambda name: False),
                              getfixturevalue=forbidden_dependency)
    with pytest.raises(pytest.fail.Exception, match="require --openacc-cli-native"):
        module.executables.__wrapped__(request)
    assert actions == []
