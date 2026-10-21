"""Actual command -> snapshot -> native C ABI -> raw output acceptance."""
import os
from pathlib import Path
import subprocess

import numpy as np
import pytest

from checks import check_build_info, invoke, json_object, load_and_check_fields
from fixtures import fourier_fixture, quadratic_fixture, sha256, write_case

BUILD_KEYS = {"protocol_version", "source_revision", "compiler_id", "compiler_version",
              "build_type", "fp_policy", "backend_library"}
UNITS = {"rdg.f64": "dimensionless", "flags.u8": "dimensionless",
         "lambda2.f64": "electron/bohr^5", "hess.f64": "electron/bohr^5",
         "signedrho.f64": "electron/bohr^3", "grad.f64": "electron/bohr^4"}
COMPONENTS = {"rdg.f64": ["rdg"], "flags.u8": ["flag_byte"],
              "lambda2.f64": ["lambda2"], "signedrho.f64": ["signedrho"],
              "grad.f64": ["gx", "gy", "gz"],
              "hess.f64": ["xx", "yy", "zz", "xy", "xz", "yz"]}


def assert_file_record(record, path):
    assert type(record["bytes"]) is int
    assert record["bytes"] == path.stat().st_size
    assert record["sha256"] == sha256(path)


@pytest.mark.parametrize("make_field", [quadratic_fixture, fourier_fixture],
                         ids=["skew-quadratic", "mixed-periodic-fourier"])
@pytest.mark.parametrize("mode", ["full", "diagnostic"])
def test_real_cli_fields_and_final_receipt(executables, tmp_path, make_field, mode, record_property):
    field, cube, card_path, card = write_case(tmp_path, make_field(), mode)
    completed, output = invoke(executables, tmp_path, cube, card_path)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    manifest_path = output / "manifest.json"
    manifest = json_object(manifest_path)
    assert type(manifest["schema_version"]) is int
    assert manifest["schema_version"] == 1
    assert manifest["state"] == "completed_numerical"
    assert manifest["stage"] == "complete"
    assert isinstance(manifest["message"], str) and manifest["message"]
    assert (output / "SUCCESS").read_bytes() == (sha256(manifest_path) + "\n").encode("ascii")
    assert (output / "card.json").read_bytes() == card_path.read_bytes()
    assert (output / "input.cube").read_bytes() == cube.read_bytes()
    assert manifest["card"]["path"] == str(card_path.resolve())
    assert_file_record(manifest["card"], card_path)
    assert manifest["input"]["path"] == str(cube.resolve())
    assert manifest["input"]["snapshot"] == "input.cube"
    assert_file_record(manifest["input"], cube)
    assert_file_record(manifest["input"], output / "input.cube")
    for key in ("grid", "metadata", "compute", "limits"):
        assert manifest[key] == card[key]
    assert manifest["source"] == card["input"]["source"]
    assert manifest["scientific"] == {"certified": False, "uncertainty": "unknown",
                                       "completion": "numerical_only"}
    assert manifest["scientific"]["certified"] is False
    assert manifest["worker"] == {"returncode": 0, "timed_out": False,
                                  "timeout_seconds": card["limits"]["timeout_seconds"]}
    assert type(manifest["worker"]["returncode"]) is int
    assert manifest["worker"]["timed_out"] is False
    assert type(manifest["worker"]["timeout_seconds"]) is int
    assert manifest["build_probe"] == {"returncode": 0, "timed_out": False,
                                       "timeout_seconds": 10}
    assert type(manifest["build_probe"]["returncode"]) is int
    assert manifest["build_probe"]["timed_out"] is False
    assert type(manifest["build_probe"]["timeout_seconds"]) is int
    assert manifest["settings"]["path"] == "settings.nml"
    assert_file_record(manifest["settings"], output / "settings.nml")
    native = json_object(output / "native.json")
    assert manifest["native"] == native
    assert native["state"] == "completed"
    assert native["abi_status"] == 0
    assert isinstance(native["stage"], str) and isinstance(native["message"], str)
    assert (output / "stdout.log").is_file() and (output / "stderr.log").is_file()
    flags, field_specs = load_and_check_fields(output, field, mode, native)
    expected_names = set(field_specs) | {"flags.u8"}
    assert set(manifest["outputs"]) == expected_names
    for name in expected_names:
        record = manifest["outputs"][name]
        assert set(record) == {"sha256", "bytes", "dtype", "byte_order", "shape",
                               "component_order", "unit", "point_order", "storage_order"}
        assert_file_record(record, output / name)
        assert record["dtype"] == ("uint8" if name == "flags.u8" else "float64")
        assert record["byte_order"] == "little"
        assert record["point_order"] == "z_fastest"
        assert record["storage_order"] == "point_major"
        assert record["unit"] == UNITS[name]
        assert record["component_order"] == COMPONENTS[name]
        shape = list(field.rho.shape)
        if name in ("grad.f64", "hess.f64"):
            shape.append(3 if name == "grad.f64" else 6)
        assert record["shape"] == shape
    env = os.environ.copy()
    for name in ("LD_PRELOAD", "LD_LIBRARY_PATH"):
        env.pop(name, None)
    info = subprocess.run([str(executables["NCI_DRIVER"]), "--build-info"], env=env,
                          capture_output=True, text=True, check=True, timeout=10)
    import json
    build = json.loads(info.stdout)
    check_build_info(build, ["cpu"])
    assert manifest["build"] == build
    backend = Path(build["backend_library"])
    assert backend.is_absolute() and backend.is_file()
    assert set(manifest["binaries"]) == {"driver", "backend_library"}
    for label, binary in (("driver", executables["NCI_DRIVER"]), ("backend_library", backend)):
        record = manifest["binaries"][label]
        assert set(record) == {"path", "sha256", "bytes"}
        assert Path(record["path"]).resolve() == binary.resolve()
        assert_file_record(record, binary)
    assert np.any((flags & 31) == 0)
    record_property("numerically_valid_points", int(np.count_nonzero((flags & 31) == 0)))
    record_property("numeric_sign_stable_points", int(np.count_nonzero((flags & 63) == 0)))
    record_property("scientific_sign_certified_points", 0)
