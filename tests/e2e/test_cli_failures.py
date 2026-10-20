"""Real CLI negative cases; no mocks, fake workers, or production imports."""
import numpy as np
import pytest

from checks import failed, invoke, json_object
from fixtures import Fixture, overflow_fixture, write_card, write_case


@pytest.mark.parametrize("level", [(), ("input",), ("input", "source"), ("grid",),
                                  ("metadata",), ("compute",), ("limits",)])
def test_unknown_card_keys_rejected_at_every_level(executables, tmp_path, level):
    _, cube, path, card = write_case(tmp_path)
    node = card
    for key in level:
        node = node[key]
    node["not_in_protocol_v1"] = 0
    write_card(path, card)
    completed, output = invoke(executables, tmp_path, cube, path)
    failed(completed, output)


@pytest.mark.parametrize("mutation", ["duplicate", "null", "boolean", "fractional_integer",
                                     "nonfinite", "missing", "oversize"])
def test_strict_json_and_card_types(executables, tmp_path, mutation):
    _, cube, path, card = write_case(tmp_path)
    if mutation == "duplicate":
        raw = path.read_text(encoding="utf-8")
        path.write_text(raw.replace('"schema_version": 1,',
                         '"schema_version": 1, "schema_version": 1,', 1), encoding="utf-8")
    else:
        if mutation == "null":
            card["metadata"]["quantity"] = None
        elif mutation == "boolean":
            card["compute"]["rho_min"] = True
        elif mutation == "fractional_integer":
            card["limits"]["timeout_seconds"] = 20.0
        elif mutation == "nonfinite":
            card["compute"]["rho_min"] = float("nan")
        elif mutation == "missing":
            del card["metadata"]["endpoint_convention"]
        else:
            card["input"]["source"]["settings"] = "x" * (1024*1024)
        write_card(path, card)
    completed, output = invoke(executables, tmp_path, cube, path)
    failed(completed, output)


@pytest.mark.parametrize("name,value", [("length_unit", "angstrom"),
                                       ("density_unit", "electron/angstrom^3")])
def test_unsupported_units_do_not_trigger_implicit_conversion(executables, tmp_path, name, value):
    _, cube, path, card = write_case(tmp_path)
    card["metadata"][name] = value
    write_card(path, card)
    completed, output = invoke(executables, tmp_path, cube, path)
    failed(completed, output)


@pytest.mark.parametrize("mutation", ["hash", "bytes", "shape", "origin", "step", "endpoint"])
def test_original_content_and_geometry_binding(executables, tmp_path, mutation):
    _, cube, path, card = write_case(tmp_path)
    if mutation == "hash":
        # Same bytes/count and identical numerical data, different comment.
        data = cube.read_bytes()
        cube.write_bytes(b"X" + data[1:])
    elif mutation == "bytes":
        card["input"]["bytes"] += 1
    elif mutation == "shape":
        card["grid"]["shape"] = [9, 7, 11]  # Same N must still be rejected.
    elif mutation == "origin":
        card["grid"]["origin"][1] += 0.125
    elif mutation == "step":
        card["grid"]["step_vectors"][0][1] += 0.03125
    else:
        card["metadata"]["periodic"][0] = 1  # finite_nodes is incompatible.
    write_card(path, card)
    completed, output = invoke(executables, tmp_path, cube, path)
    failed(completed, output)


def test_tiny_well_conditioned_geometry_factor_two_mismatch(executables, tmp_path):
    # Fixed absolute geometry tolerances would incorrectly accept this factor2
    # mismatch. Both actual and declared J are invertible with condition1.
    field = Fixture(np.ones((5, 5, 5)), None, None, np.zeros(3),
                    np.diag([2e-16]*3), (0, 0, 0), 1e-8, "tiny geometry binding v1")
    _, cube, path, card = write_case(tmp_path, field)
    card["grid"]["step_vectors"] = np.diag([1e-16]*3).tolist()
    write_card(path, card)
    completed, output = invoke(executables, tmp_path, cube, path)
    failed(completed, output)


def test_total_memory_reservation_exceeds_reader_only_budget(executables, tmp_path):
    field, cube, path, card = write_case(tmp_path)
    n = field.rho.size
    # N_atoms=0. This fits rho+8192-byte reader scanner+1024 slack, but not
    # diagnostic reservation97N + neighbor40*sum(shape) +65536+4096*threads.
    card["limits"]["memory_budget_bytes"] = 8*n + 8192 + 1024
    required = 105*n + 40*sum(field.rho.shape) + 65536 + 4096 + 8192
    assert card["limits"]["memory_budget_bytes"] < required
    write_card(path, card)
    completed, output = invoke(executables, tmp_path, cube, path)
    manifest = failed(completed, output)
    errors = [manifest["stage"], manifest["message"]]
    if isinstance(manifest.get("native"), dict):
        errors += [manifest["native"]["stage"], manifest["native"]["message"]]
    assert any(word in " ".join(errors).lower() for word in ("memory", "budget", "alloc", "reserv"))


def test_numeric_overflow_cannot_create_success(executables, tmp_path):
    field, cube, path, _ = write_case(tmp_path, overflow_fixture())
    completed, output = invoke(executables, tmp_path, cube, path)
    manifest = failed(completed, output)
    native = manifest["native"]
    assert native == json_object(output / "native.json")
    assert native["abi_status"] == 4
    assert native["stats"]["numeric_failures"] == 1
    assert native["stats"]["total"] == 125
    assert native["stats"]["valid"] == 0
    assert native["stats"]["invalid"] == 125
    for name, components in (("rdg.f64", 1), ("lambda2.f64", 1), ("signedrho.f64", 1),
                             ("grad.f64", 3), ("hess.f64", 6)):
        if (output / name).exists():
            assert (output / name).stat().st_size == field.rho.size*components*8
            assert np.all(np.isnan(np.fromfile(output / name, dtype="<f8")))


def test_all_low_positive_density_is_failed_not_empty_success(executables, tmp_path):
    field = Fixture(np.full((5, 5, 5), 0.5e-8), None, None, np.zeros(3),
                    np.eye(3), (0, 0, 0), 1e-8, "all low positive density v1")
    _, cube, path, _ = write_case(tmp_path, field)
    completed, output = invoke(executables, tmp_path, cube, path)
    manifest = failed(completed, output)
    native = manifest["native"]
    assert native["abi_status"] == 3
    assert native["stats"]["total"] == 125
    assert native["stats"]["valid"] == 0
    assert native["stats"]["invalid"] == 125
    assert native["stats"]["numeric_failures"] == 0
    assert native["stats"]["bit_counts"][2] == 125
    if (output / "flags.u8").exists():
        flags = np.fromfile(output / "flags.u8", dtype=np.uint8).reshape((5, 5, 5))
        np.testing.assert_array_equal(flags, field.expected_flags())


@pytest.mark.parametrize("collision", ["existing_output", "input_directory"])
def test_output_collision_is_untouched(executables, tmp_path, collision):
    _, cube, path, _ = write_case(tmp_path)
    output = tmp_path / "existing output" if collision == "existing_output" else path.parent
    if not output.exists():
        output.mkdir()
    (output / "sentinel.bin").write_bytes(b"KEEP\x00original\xff")
    # An already present marker cannot cause the CLI to claim a successful rerun.
    (output / "SUCCESS").write_bytes(b"existing marker\n")
    before = {p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()}
    completed, _ = invoke(executables, tmp_path, cube, path, output=output)
    assert completed.returncode != 0
    after = {p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()}
    assert after == before
