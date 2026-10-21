"""Real CLI/worker tests; collected only with --openacc-cli-native.

No driver/library is loaded at import or collection. No optional skip exists.
"""
import json
import subprocess

import numpy as np
import pytest

from checks import failed, json_object
from fixtures import Fixture, overflow_fixture, sha256, write_card, write_case
from openacc_support import (add_atoms, configure, cpu_gpu_fields, field_fixture, memory_plan,
                             run, same_build_fields, successful, worker_settings)


@pytest.mark.parametrize("boundary", ["finite", "periodic", "mixed"])
@pytest.mark.parametrize("mode", ["full", "diagnostic"])
def test_cpu_gpu_oracle_and_full_b1_tail(executables, tmp_path, boundary, mode):
    field, cube, path, card = write_case(tmp_path, field_fixture(boundary), mode)
    configure(path, card, "cpu")
    result, cpu = run(executables, tmp_path, cube, path, card, "cpu-full", gpu=False)
    baseline = successful(result, cpu, card, field, mode, gpu=False)
    full = None
    for label, block in (("gpu-full", None), ("gpu-b1", 1), ("gpu-tail", 3)):
        configure(path, card, block=block)
        result, output = run(executables, tmp_path, cube, path, card, label)
        manifest = successful(result, output, card, field, mode)
        cpu_gpu_fields(cpu, output, baseline["outputs"], field)
        for key in ("total", "valid", "invalid", "numeric_failures"):
            assert manifest["native"]["stats"][key] == baseline["native"]["stats"][key]
        assert [x for i,x in enumerate(manifest["native"]["stats"]["bit_counts"]) if i != 5] == [
            x for i,x in enumerate(baseline["native"]["stats"]["bit_counts"]) if i != 5]
        if full is None:
            full = output
        else:
            same_build_fields(full, output, manifest["outputs"])


@pytest.mark.parametrize("mode", ["full", "diagnostic"])
@pytest.mark.parametrize("block", [None, 1, 3], ids=["fullgrid", "b1", "tail"])
def test_nonzero_atom_exact_budget_and_one_below(executables, cube_atom_bytes, tmp_path, mode, block):
    field, cube, path, card = write_case(tmp_path, field_fixture("mixed"), mode)
    add_atoms(cube, path, card)
    expected = memory_plan(field.rho.shape, mode, True, block, atom_bytes=2*cube_atom_bytes)
    card["limits"]["memory_budget_bytes"] = expected["host_bytes"]
    configure(path, card, block=block)
    result, output = run(executables, tmp_path, cube, path, card, "exact-budget")
    successful(result, output, card, field, mode, atom_bytes=2*cube_atom_bytes)
    card["limits"]["memory_budget_bytes"] -= 1
    write_card(path, card)
    result, output = run(executables, tmp_path, cube, path, card, "atom-budget-minus-one")
    manifest = failed(result, output)
    # CLI lower bound cannot know atoms: the real worker must charge them.
    assert manifest["worker"] is not None
    assert manifest["native"]["npoints"] == 0
    assert manifest["native"]["stats"] is None
    assert not list(output.glob("*.f64"))
    assert not (output / "flags.u8").exists()


@pytest.mark.parametrize("selector", ["cuda", "OPENACC", 1])
def test_bad_card_backend_has_no_worker(executables, tmp_path, selector):
    _, cube, path, card = write_case(tmp_path)
    configure(path, card, selector)
    result, output = run(executables, tmp_path, cube, path, card, "bad-selector")
    assert failed(result, output)["worker"] is None


def test_cpu_worker_cannot_satisfy_openacc_card(executables, tmp_path):
    _, cube, path, card = write_case(tmp_path)
    configure(path, card)
    result, output = run(executables, tmp_path, cube, path, card, "worker-mismatch", gpu=False)
    assert failed(result, output)["worker"] is None
    assert not list(output.glob("*.f64"))


@pytest.mark.parametrize("mode", ["full", "diagnostic"])
def test_optional_worker_cpu_selector_preserves_cpu_receipt(executables, tmp_path, mode):
    field, cube, path, card = write_case(tmp_path, field_fixture("finite"), mode)
    configure(path, card, backend="cpu")
    result, output = run(executables, tmp_path, cube, path, card, "optional-worker-cpu")
    successful(result, output, card, field, mode)


@pytest.mark.parametrize("kind", ["remote-nan", "remote-negative", "all-invalid", "overflow"])
def test_complete_preflight_and_native_failures_never_publish_success(executables, tmp_path, kind):
    if kind == "overflow":
        field = overflow_fixture()
    elif kind == "all-invalid":
        field = Fixture(np.full((5, 7, 9), 1e-10), None, None, np.zeros(3),
                        np.eye(3), (0, 0, 0), 1e-8, "OpenACC all-invalid CLI fixture")
    else:
        field = field_fixture("mixed")
        field.rho[3, -1, -1] = float("nan") if kind == "remote-nan" else -1e-3
    _, cube, path, card = write_case(tmp_path, field)
    configure(path, card, block=1)
    result, output = run(executables, tmp_path, cube, path, card, "failed-density")
    native = failed(result, output)["native"]
    assert native["state"] == "failed"
    if kind.startswith("remote"):
        assert native["stats"] is None
        assert not list(output.glob("*.f64"))
        assert not (output / "flags.u8").exists()
    elif kind == "all-invalid":
        assert native["abi_status"] == 3
        assert native["stats"]["total"] == native["stats"]["invalid"] == field.rho.size
        assert native["stats"]["valid"] == native["stats"]["numeric_failures"] == 0
        if (output / "flags.u8").exists():
            np.testing.assert_array_equal(np.fromfile(output / "flags.u8", dtype="u1").reshape(field.rho.shape),
                                          field.expected_flags())
    else:
        assert native["abi_status"] == 4
        assert native["stats"]["numeric_failures"] == 1
        assert native["stats"]["total"] == 75


@pytest.mark.parametrize("shape,mode", [([2**59, 5, 5], "full"),
    ([5, 5, 894785], "diagnostic"), ([5, 53687092, 5], "full")],
    ids=["int64-overflow", "packed-object-limit", "axis-object-limit"])
def test_unsupported_plan_refused_before_cube_snapshot(executables, tmp_path, shape, mode):
    _, cube, path, card = write_case(tmp_path, mode=mode)
    card["grid"]["shape"] = shape
    card["limits"].update(max_points=2**63-1, memory_budget_bytes=2**63-1)
    configure(path, card)
    result, output = run(executables, tmp_path, cube, path, card, "unsupported-plan")
    manifest = failed(result, output)
    assert manifest["worker"] is None
    assert not (output / "input.cube").exists()


def test_native_selector_rejection_before_input_open(executables, tmp_path):
    field, cube, path, card = write_case(tmp_path)
    configure(path, card)
    result, output = run(executables, tmp_path, cube, path, card, "settings-template")
    successful(result, output, card, field, "diagnostic")
    settings = (output / "settings.nml").read_text(encoding="ascii")
    import re
    assert len(re.findall(r"(?m)^\s*backend\s*=\s*1\s*,?\s*$", settings)) == 1
    for selector in (-1, 2, 1):
        bad = re.sub(r"(?m)^(\s*backend\s*=\s*)1(\s*,?\s*)$", rf"\g<1>{selector}\2", settings)
        nml = tmp_path / f"bad-selector-{selector}.nml"
        nml.write_text(bad, encoding="ascii")
        destination = tmp_path / f"native-selector-{selector}"
        destination.mkdir()
        # Nonexistent CUBE proves selector validation precedes opening input.
        worker = "NCI_DRIVER" if selector == 1 else "NCI_OPENACC_DRIVER"
        command = [str(executables[worker]), str(tmp_path/"absent.cube"),
                   str(nml), str(destination)]
        with (destination/"stdout.log").open("wb") as out, (destination/"stderr.log").open("wb") as err:
            child = subprocess.run(command, stdout=out, stderr=err, timeout=20, check=False)
        native = json_object(destination / "native.json")
        evidence = dict(argv=command, returncode=child.returncode, artifacts={
            name: dict(path=str((destination/name).resolve()), sha256=sha256(destination/name),
                       bytes=(destination/name).stat().st_size)
            for name in ("stdout.log", "stderr.log", "native.json")})
        (tmp_path/f"native-selector-{selector}.evidence.json").write_text(json.dumps(evidence, indent=2)+"\n")
        assert child.returncode != 0 and native["state"] == "failed"
        assert any(word in (native["stage"]+" "+native["message"]).lower()
                   for word in ("backend", "selector"))
        assert native["npoints"] == 0 and native["stats"] is None
        assert not (destination / "SUCCESS").exists()
        assert not list(destination.glob("*.f64"))


@pytest.mark.parametrize("kind", ["int64-overflow", "packed-object-limit", "host-budget-minus-one"])
def test_direct_worker_plan_refusal_before_input_open(executables, tmp_path, kind):
    shape, mode, budget = (5,5,5), "diagnostic", 2**63-1
    if kind == "int64-overflow":
        shape = (2**62,5,5)
        keywords = ("overflow", "int64", "point count", "grid size", "grid dimensions")
    elif kind == "packed-object-limit":
        shape = (5,5,894785)
        keywords = ("object", "mapped", "int32", "unsupported", "limit")
    else:
        budget = memory_plan(shape, mode, False)["host_bytes"] - 1
        keywords = ("memory", "budget", "reserv")
    nml = tmp_path/"independent settings.nml"
    nml.write_text(worker_settings(shape, mode, budget), encoding="ascii")
    destination = tmp_path/"native rejected plan"
    destination.mkdir()
    command = [str(executables["NCI_OPENACC_DRIVER"]), str(tmp_path/"absent.cube"),
               str(nml), str(destination)]
    with (destination/"stdout.log").open("wb") as out, (destination/"stderr.log").open("wb") as err:
        child = subprocess.run(command, stdout=out, stderr=err, timeout=20, check=False)
    native = json_object(destination/"native.json")
    evidence = dict(argv=command, returncode=child.returncode, artifacts={
        name: dict(path=str((destination/name).resolve()), sha256=sha256(destination/name),
                   bytes=(destination/name).stat().st_size)
        for name in ("stdout.log", "stderr.log", "native.json")})
    evidence["settings"] = dict(path=str(nml.resolve()), sha256=sha256(nml), bytes=nml.stat().st_size)
    (tmp_path/"direct-plan.evidence.json").write_text(json.dumps(evidence, indent=2)+"\n")
    assert child.returncode != 0 and native["state"] == "failed"
    assert any(word in (native["stage"]+" "+native["message"]).lower() for word in keywords)
    assert native["npoints"] == 0 and native["stats"] is None
    assert not (destination/"SUCCESS").exists()
    assert not list(destination.glob("*.f64"))
    assert not (destination/"flags.u8").exists()
