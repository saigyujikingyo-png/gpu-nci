"""Independent subprocess/file assertions for the frozen public CLI protocol."""
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from fixtures import sha256
from reference.fields import pack_hessian


BUILD_KEYS = {"protocol_version", "source_revision", "compiler_id", "compiler_version",
              "build_type", "fp_policy", "backend_library"}


def check_build_info(build, capabilities=None):
    """Seven-field legacy CPU metadata remains valid; new arrays are typed."""
    assert set(build) in (BUILD_KEYS, BUILD_KEYS | {"supported_backends"})
    assert type(build["protocol_version"]) is int and build["protocol_version"] == 1
    for key in BUILD_KEYS - {"protocol_version"}:
        assert isinstance(build[key], str)
    declared = build.get("supported_backends", ["cpu"])
    assert type(declared) is list
    assert declared in (["cpu"], ["cpu", "openacc"])
    assert all(type(item) is str for item in declared)
    if capabilities is not None:
        assert declared == capabilities
    return declared


def invoke(executables, parent, cube, card, output=None):
    cwd = parent / "invocation cwd"
    cwd.mkdir(exist_ok=True)
    output = cwd / "new results" if output is None else output
    originals = {p: p.read_bytes() for p in (cube, card)}
    command = [sys.executable, str(executables["NCI_CLI"]), "run", "--card",
               os.path.relpath(card, cwd), "--driver", str(executables["NCI_DRIVER"]),
               "--output-dir", os.path.relpath(output, cwd)]
    try:
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                                   timeout=40, check=False)
    finally:
        for path, content in originals.items():
            assert path.read_bytes() == content, f"CLI modified original {path.name}"
    return completed, output


def json_object(path):
    # Duplicate keys/nonfinite JSON in receipts must not silently disappear.
    def pairs(items):
        result = {}
        for name, value in items:
            assert name not in result, f"duplicate receipt key {name}"
            result[name] = value
        return result

    def reject_constant(value):
        raise AssertionError(f"nonfinite JSON receipt token {value}")

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs,
                       parse_constant=reject_constant)
    assert isinstance(value, dict)
    return value


def failed(completed, output):
    assert completed.returncode != 0, completed.stdout + completed.stderr
    assert not (output / "SUCCESS").exists()
    manifest = json_object(output / "manifest.json")
    assert type(manifest["schema_version"]) is int
    assert manifest["schema_version"] == 1
    assert manifest["state"] == "failed"
    assert manifest["outputs"] == {}
    assert isinstance(manifest["stage"], str) and manifest["stage"]
    assert isinstance(manifest["message"], str) and manifest["message"]
    if (output / "native.json").exists():
        native = json_object(output / "native.json")
        assert manifest["native"] == native
        assert native["state"] == "failed"
    return manifest


def check_native_stats(native, flags, n):
    valid = (flags & 31) == 0
    stats = native["stats"]
    assert type(native["protocol_version"]) is int
    assert type(native["npoints"]) is int
    assert type(native["abi_status"]) is int
    assert set(stats) == {"total", "valid", "invalid", "numeric_failures", "bit_counts"}
    for name in ("total", "valid", "invalid", "numeric_failures"):
        assert type(stats[name]) is int and 0 <= stats[name] <= n
    assert len(stats["bit_counts"]) == 7
    assert all(type(count) is int and 0 <= count <= n for count in stats["bit_counts"])
    assert native["protocol_version"] == 1
    assert native["npoints"] == n
    assert stats["total"] == n
    assert stats["valid"] == np.count_nonzero(valid)
    assert stats["invalid"] == np.count_nonzero(~valid)
    assert stats["numeric_failures"] == np.count_nonzero(flags & 16)
    assert stats["bit_counts"] == [int(np.count_nonzero(flags & (1 << bit)))
                                    for bit in range(7)]
    return valid


def load_and_check_fields(output, fixture, mode, native):
    n, shape = fixture.rho.size, fixture.rho.shape
    flags = np.fromfile(output / "flags.u8", dtype=np.uint8)
    assert flags.size == n
    flags = flags.reshape(shape, order="C")
    assert_array_equal(flags & 15, fixture.expected_flags())
    assert not np.any(flags & (16 | 128))
    valid = check_native_stats(native, flags, n)
    assert np.all((flags[~valid] & 96) == 0)
    assert np.all(flags[valid] & 64)
    specs = {"rdg.f64": (), "lambda2.f64": (), "signedrho.f64": ()}
    if mode == "diagnostic":
        specs.update({"grad.f64": (3,), "hess.f64": (6,)})
    else:
        assert not (output / "grad.f64").exists()
        assert not (output / "hess.f64").exists()
    fields = {}
    for name, extra in specs.items():
        count = n * (extra[0] if extra else 1)
        path = output / name
        assert path.stat().st_size == 8 * count
        fields[name] = np.fromfile(path, dtype="<f8").reshape((*shape, *extra), order="C")
        assert np.all(np.isnan(fields[name][~valid]))
        assert np.all(np.isfinite(fields[name][valid]))
    _, (rdg, signedrho, lambda2) = fixture.numerical_reference()
    assert_allclose(fields["rdg.f64"][valid], rdg, atol=1e-11, rtol=1e-9)
    assert_allclose(fields["lambda2.f64"][valid], lambda2, atol=1e-12, rtol=1e-10)
    assert_array_equal(fields["signedrho.f64"][valid],
                       np.sign(fields["lambda2.f64"][valid]) * fixture.rho[valid])
    stable_reference = np.abs(lambda2) > 1e-9
    assert_array_equal(fields["signedrho.f64"][valid][stable_reference],
                       signedrho[stable_reference])
    if mode == "diagnostic":
        assert_allclose(fields["grad.f64"][valid], fixture.gradient[valid],
                        atol=1e-12, rtol=1e-10)
        assert_allclose(fields["hess.f64"][valid], pack_hessian(fixture.hessian)[valid],
                        atol=1e-12, rtol=1e-10)
    return flags, specs
