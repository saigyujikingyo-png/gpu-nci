#!/usr/bin/env python3
"""Offline numerical-run receipts. Runtime dependencies: Python standard library."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

MAX_JSON = 1024 * 1024
INT64_MAX = (1 << 63) - 1
SOURCE_KEYS = {"kind", "reference", "permission", "producer", "producer_version",
               "settings", "density_precision"}


class CliError(Exception):
    def __init__(self, stage, message):
        super().__init__(message)
        self.stage = stage


def fail(stage, message):
    raise CliError(stage, message)


def strict_json(data, stage):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail(stage, f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def constant(value):
        fail(stage, f"Nonfinite JSON constant: {value}")

    def floating(value):
        result = float(value)
        if not math.isfinite(result):
            fail(stage, "Nonfinite JSON number")
        return result

    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=constant, parse_float=floating)
    except (ValueError, UnicodeError, RecursionError) as exc:
        fail(stage, f"Invalid UTF-8 JSON: {exc}")


def exact_object(value, keys, name):
    if type(value) is not dict or set(value) != set(keys):
        fail("card", f"{name} must have exactly these keys: {', '.join(sorted(keys))}")


def integer(value, name, low=0, high=INT64_MAX, stage="card"):
    if type(value) is not int or not low <= value <= high:
        fail(stage, f"{name} must be an integer in [{low}, {high}]")
    return value


def real(value, name, positive=False, nonnegative=False):
    if type(value) not in (int, float):
        fail("card", f"{name} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        fail("card", f"{name} must fit binary64")
    if not math.isfinite(result) or (positive and result <= 0) or (nonnegative and result < 0):
        fail("card", f"{name} has an invalid finite range")
    return result


def text_enum(value, choices, name):
    if type(value) is not str or value not in choices:
        fail("card", f"{name} must be one of {', '.join(choices)}")


def array(value, length, name):
    if type(value) is not list or len(value) != length:
        fail("card", f"{name} must contain {length} values")
    return value


def checked(value, name):
    if not 0 <= value <= INT64_MAX:
        fail("card", f"{name} exceeds signed int64")
    return value


def validate_card(card):
    exact_object(card, {"schema_version", "input", "grid", "metadata", "compute", "limits"}, "card")
    integer(card["schema_version"], "schema_version", 1, 1)
    inp, grid, meta, comp, limits = (card[k] for k in ("input", "grid", "metadata", "compute", "limits"))
    exact_object(inp, {"path", "sha256", "bytes", "source"}, "input")
    if type(inp["path"]) is not str or not inp["path"] or "\0" in inp["path"]:
        fail("card", "input.path must be a nonempty path without NUL")
    if type(inp["sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", inp["sha256"]):
        fail("card", "input.sha256 must be 64 lowercase hexadecimal characters")
    integer(inp["bytes"], "input.bytes", 1)
    exact_object(inp["source"], SOURCE_KEYS, "input.source")
    for key, value in inp["source"].items():
        if type(value) is not str or not 1 <= len(value) <= 4096:
            fail("card", f"input.source.{key} must contain 1..4096 characters")
    text_enum(inp["source"]["kind"], ("synthetic", "public", "user_authorized"), "source.kind")
    exact_object(grid, {"shape", "origin", "step_vectors", "axis_order"}, "grid")
    npoints = 1
    for value in array(grid["shape"], 3, "grid.shape"):
        npoints = checked(npoints * integer(value, "grid.shape entry", 5), "grid point count")
    for value in array(grid["origin"], 3, "grid.origin"):
        real(value, "grid.origin entry")
    for vector in array(grid["step_vectors"], 3, "grid.step_vectors"):
        for value in array(vector, 3, "grid.step_vectors column"):
            real(value, "grid.step_vectors entry")
    text_enum(grid["axis_order"], ("z_fastest",), "grid.axis_order")
    exact_object(meta, {"quantity", "spin_convention", "density_representation", "length_unit",
                        "density_unit", "periodic", "endpoint_convention"}, "metadata")
    for key, choices in {"quantity": ("electron_density",), "spin_convention": ("spin_summed",),
                         "density_representation": ("all_electron", "valence", "core_augmented", "promolecular"),
                         "length_unit": ("bohr",), "density_unit": ("electron/bohr^3",)}.items():
        text_enum(meta[key], choices, f"metadata.{key}")
    periodic = array(meta["periodic"], 3, "metadata.periodic")
    endpoints = array(meta["endpoint_convention"], 3, "metadata.endpoint_convention")
    for p, endpoint in zip(periodic, endpoints):
        integer(p, "metadata.periodic entry", 0, 1)
        text_enum(endpoint, ("independent_samples" if p else "finite_nodes",), "endpoint_convention")
    exact_object(comp, {"backend", "layout", "output_mode", "rho_min", "negative_tolerance", "omp_threads"}, "compute")
    text_enum(comp["backend"], ("cpu",), "compute.backend")
    text_enum(comp["layout"], ("full_grid",), "compute.layout")
    text_enum(comp["output_mode"], ("full", "diagnostic"), "compute.output_mode")
    real(comp["rho_min"], "compute.rho_min", positive=True)
    real(comp["negative_tolerance"], "compute.negative_tolerance", nonnegative=True)
    integer(comp["omp_threads"], "compute.omp_threads", 1, 16)
    exact_object(limits, {"memory_budget_bytes", "max_points", "timeout_seconds"}, "limits")
    integer(limits["memory_budget_bytes"], "limits.memory_budget_bytes", 1)
    integer(limits["max_points"], "limits.max_points", 1)
    integer(limits["timeout_seconds"], "limits.timeout_seconds", 1, 3600)
    if npoints > limits["max_points"]:
        fail("card", "grid exceeds max_points")
    # This lower bound deliberately excludes atoms: only the native reader can
    # account for them before allocation. This is not a process RSS limit.
    per_point = 105 if comp["output_mode"] == "diagnostic" else 33
    reservation = checked(npoints * per_point, "tracked point allocation")
    reservation = checked(reservation + checked(sum(grid["shape"]) * 40, "axis allocation"), "allocation")
    reservation = checked(reservation + 8192 + 65536 + 4096 * comp["omp_threads"], "allocation")
    if reservation > limits["memory_budget_bytes"]:
        fail("card", "memory budget is below the tracked reservation before atoms")
    return npoints


def read_small(path, stage):
    with open(path, "rb") as stream:
        data = stream.read(MAX_JSON + 1)
    if len(data) > MAX_JSON:
        fail(stage, "JSON exceeds 1 MiB")
    return data


def fingerprint(path, stage="integrity", regular=True):
    if regular:
        info = Path(path).lstat()
        if not stat.S_ISREG(info.st_mode):
            fail(stage, f"Expected a regular, non-symlink file: {path}")
    digest, size = hashlib.sha256(), 0
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return {"sha256": digest.hexdigest(), "bytes": size}


def write_new(path, data):
    with open(path, "xb") as stream:
        stream.write(data)


def publish_manifest(directory, manifest):
    data = (json.dumps(manifest, ensure_ascii=True, allow_nan=False, indent=2) + "\n").encode("utf-8")
    # This name belongs only to our freshly created output directory.
    temporary = directory / ".manifest.tmp"
    write_new(temporary, data)
    os.replace(temporary, directory / "manifest.json")
    return hashlib.sha256(data).hexdigest()


def namelist(card):
    grid, meta, comp, limits = (card[k] for k in ("grid", "metadata", "compute", "limits"))
    def nums(values):
        return ", ".join(format(float(v), ".17g") for v in values)
    lines = ["&nci_run", " protocol_version = 1,",
             " shape = " + ", ".join(str(v) for v in grid["shape"]) + ",",
             " origin = " + nums(grid["origin"]) + ",",
             " step_vectors = " + nums(v for axis in grid["step_vectors"] for v in axis) + ",",
             " periodic = " + ", ".join(str(v) for v in meta["periodic"]) + ",",
             " endpoint_convention = " + ", ".join("'" + v + "'" for v in meta["endpoint_convention"]) + ","]
    for key in ("quantity", "spin_convention", "density_representation", "length_unit", "density_unit"):
        lines.append(f" {key} = '{meta[key]}',")
    lines += [f" output_mode = {int(comp['output_mode'] == 'diagnostic')},",
              f" rho_min = {nums([comp['rho_min']])},",
              f" negative_tolerance = {nums([comp['negative_tolerance']])},",
              f" omp_threads = {comp['omp_threads']},",
              f" memory_budget_bytes = {limits['memory_budget_bytes']},",
              f" max_points = {limits['max_points']}", "/", ""]
    return "\n".join(lines).encode("ascii")


def child_process(argv, directory, prefix, timeout):
    env = os.environ.copy()
    for name in ("LD_PRELOAD", "LD_LIBRARY_PATH"):
        env.pop(name, None)
    result = {"returncode": None, "timed_out": False, "timeout_seconds": timeout}
    with open(directory / (prefix + "stdout.log"), "xb") as stdout, open(directory / (prefix + "stderr.log"), "xb") as stderr:
        process = subprocess.Popen(argv, stdout=stdout, stderr=stderr, env=env)
        try:
            result["returncode"] = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            result["returncode"] = process.wait()
            result["timed_out"] = True
        except BaseException:
            # We own this direct child, but never kill unrelated applications.
            process.kill()
            process.wait()
            raise
    return result


def validate_build(build):
    required = {"protocol_version", "source_revision", "compiler_id", "compiler_version", "build_type", "fp_policy", "backend_library"}
    if type(build) is not dict or not required <= set(build):
        fail("build_info", "Missing required build-info keys")
    integer(build["protocol_version"], "build protocol_version", 1, 1, "build_info")
    for key in required - {"protocol_version"}:
        if type(build[key]) is not str or "\0" in build[key]:
            fail("build_info", f"Invalid build-info {key}")
    if not Path(build["backend_library"]).is_absolute():
        fail("build_info", "backend_library must be absolute")


def validate_native(receipt, npoints):
    required = {"protocol_version", "state", "stage", "message", "abi_status", "npoints", "stats"}
    if type(receipt) is not dict or not required <= set(receipt):
        fail("native_receipt", "Missing native receipt keys")
    integer(receipt["protocol_version"], "native protocol_version", 1, 1, "native_receipt")
    if receipt["state"] not in ("completed", "failed") or type(receipt["stage"]) is not str or type(receipt["message"]) is not str:
        fail("native_receipt", "Invalid native state/stage/message")
    integer(receipt["npoints"], "native npoints", 0, npoints, "native_receipt")
    if receipt["abi_status"] is not None:
        integer(receipt["abi_status"], "abi_status", 0, INT64_MAX, "native_receipt")
    stats = receipt["stats"]
    if stats is not None:
        keys = {"total", "valid", "invalid", "numeric_failures", "bit_counts"}
        if type(stats) is not dict or not keys <= set(stats):
            fail("native_receipt", "Invalid native statistics keys")
        for key in keys - {"bit_counts"}:
            integer(stats[key], f"stats.{key}", 0, npoints, "native_receipt")
        bits = stats["bit_counts"]
        if type(bits) is not list or len(bits) != 7:
            fail("native_receipt", "bit_counts must contain seven integers")
        for value in bits:
            integer(value, "bit count", 0, npoints, "native_receipt")
        if (stats["valid"] + stats["invalid"] != stats["total"] or
                stats["total"] != receipt["npoints"] or
                stats["numeric_failures"] != bits[4] or bits[4] > stats["invalid"] or
                not max(bits[:5]) <= stats["invalid"] <= sum(bits[:5]) or
                bits[5] > stats["valid"] or bits[6] != stats["valid"]):
            fail("native_receipt", "Inconsistent native statistics")
    if (receipt["state"] != "completed" or receipt["abi_status"] != 0 or
            receipt["npoints"] != npoints or stats is None or
            stats["total"] != npoints or stats["valid"] == 0 or stats["numeric_failures"] != 0):
        fail("native_receipt", "Native receipt does not certify numerical completion")


def output_specs(card):
    shape = card["grid"]["shape"]
    specs = {"rdg.f64": (8, ["rdg"], "dimensionless"),
             "lambda2.f64": (8, ["lambda2"], "electron/bohr^5"),
             "signedrho.f64": (8, ["signedrho"], "electron/bohr^3"),
             "flags.u8": (1, ["flag_byte"], "dimensionless")}
    if card["compute"]["output_mode"] == "diagnostic":
        specs.update({"grad.f64": (24, ["gx", "gy", "gz"], "electron/bohr^4"),
                      "hess.f64": (48, ["xx", "yy", "zz", "xy", "xz", "yz"], "electron/bohr^5")})
    for name, (width, components, unit) in specs.items():
        yield name, width, {"dtype": "uint8" if width == 1 else "float64", "byte_order": "little",
                            "shape": shape + ([len(components)] if len(components) > 1 else []),
                            "component_order": components, "unit": unit, "point_order": "z_fastest",
                            "storage_order": "point_major"}


def run(args):
    directory = Path(os.path.abspath(args.output_dir))
    # No receipt or log is written until exclusive ownership is established.
    try:
        directory.mkdir()
    except OSError as exc:
        print(f"output: cannot create new output directory: {exc}", file=sys.stderr)
        return 1
    manifest = {"schema_version": 1, "state": "running", "stage": "card", "message": "Preparing numerical input",
                "card": None, "input": None, "grid": None, "metadata": None, "compute": None,
                "limits": None, "source": None, "build": None, "binaries": None, "worker": None,
                "build_probe": None, "native": None, "settings": None, "outputs": {},
                "scientific": {"certified": False, "uncertainty": "unknown", "completion": "numerical_only"}}
    stage = "card"
    try:
        publish_manifest(directory, manifest)
        card_path = Path(os.path.abspath(args.card))
        card_bytes = read_small(card_path, stage)
        write_new(directory / "card.json", card_bytes)
        card_hash = {"sha256": hashlib.sha256(card_bytes).hexdigest(), "bytes": len(card_bytes)}
        manifest["card"] = {"path": str(card_path), **card_hash}
        card = strict_json(card_bytes, stage)
        npoints = validate_card(card)
        for key in ("grid", "metadata", "compute", "limits"):
            manifest[key] = card[key]
        manifest["source"] = card["input"]["source"]
        stage = "snapshot"
        source = Path(card["input"]["path"])
        if not source.is_absolute():
            source = card_path.parent / source
        source = Path(os.path.abspath(source))
        expected = {k: card["input"][k] for k in ("sha256", "bytes")}
        manifest["input"] = {"path": str(source), **expected, "snapshot": "input.cube"}
        digest, count = hashlib.sha256(), 0
        if not source.is_file():
            fail(stage, "Input is not a regular file")
        with open(source, "rb") as original, open(directory / "input.cube", "xb") as snapshot:
            while True:
                chunk = original.read(min(1024 * 1024, expected["bytes"] - count + 1))
                if not chunk:
                    break
                snapshot.write(chunk)
                digest.update(chunk)
                count += len(chunk)
                if count > expected["bytes"]:
                    fail(stage, "Input exceeds declared byte count")
        if {"sha256": digest.hexdigest(), "bytes": count} != expected:
            fail(stage, "Input byte count/SHA-256 does not match the card")
        write_new(directory / "settings.nml", namelist(card))
        manifest["settings"] = {"path": "settings.nml", **fingerprint(directory / "settings.nml")}
        stage = "build_info"
        driver = Path(os.path.abspath(args.driver)).resolve(strict=True)
        driver_print = {"path": str(driver), **fingerprint(driver, stage)}
        probe = child_process([str(driver), "--build-info"], directory, "build-info.", 10)
        manifest["build_probe"] = probe
        if probe["timed_out"] or probe["returncode"] != 0:
            fail(stage, "Build-info probe failed or timed out")
        build = strict_json(read_small(directory / "build-info.stdout.log", stage), stage)
        manifest["build"] = build
        validate_build(build)
        backend = Path(build["backend_library"]).resolve(strict=True)
        manifest["binaries"] = {"driver": driver_print, "backend_library": {"path": str(backend), **fingerprint(backend, stage)}}
        stage = "worker"
        manifest.update(stage=stage, message="Running frozen numerical input")
        publish_manifest(directory, manifest)
        manifest["worker"] = child_process([str(driver), str(directory / "input.cube"),
                                            str(directory / "settings.nml"), str(directory)],
                                           directory, "", card["limits"]["timeout_seconds"])
        native_path = directory / "native.json"
        if native_path.exists():
            fingerprint(native_path, "native_receipt")
            manifest["native"] = strict_json(read_small(native_path, "native_receipt"), "native_receipt")
        if manifest["worker"]["timed_out"]:
            fail(stage, "Worker timed out")
        if manifest["worker"]["returncode"] != 0:
            fail(stage, "Worker exited nonzero; inspect native receipt and logs")
        stage = "native_receipt"
        validate_native(manifest["native"], npoints)
        stage = "outputs"
        for name, width, metadata in output_specs(card):
            info = fingerprint(directory / name, stage)
            if info["bytes"] != npoints * width:
                fail(stage, f"Incorrect byte count for {name}")
            manifest["outputs"][name] = {**info, **metadata}
        stage = "integrity"
        for path, expected_print in [(directory / "input.cube", expected), (directory / "card.json", card_hash),
                                     (directory / "settings.nml", manifest["settings"])]:
            if fingerprint(path) != {k: expected_print[k] for k in ("sha256", "bytes")}:
                fail(stage, f"Frozen file changed: {path.name}")
        for info in manifest["binaries"].values():
            if fingerprint(info["path"]) != {k: info[k] for k in ("sha256", "bytes")}:
                fail(stage, "Driver/backend changed during execution")
        # A worker may not pre-create our final receipt marker.
        if (directory / "SUCCESS").exists():
            fail(stage, "Worker unexpectedly created SUCCESS")
        manifest.update(state="completed_numerical", stage="complete",
                        message="Numerical completion; scientific uncertainty remains unknown.")
        manifest_hash = publish_manifest(directory, manifest)
        write_new(directory / "SUCCESS", (manifest_hash + "\n").encode("ascii"))
        return 0
    except (CliError, OSError, ValueError, OverflowError, RecursionError, KeyboardInterrupt) as exc:
        stage = exc.stage if isinstance(exc, CliError) else stage
        manifest.update(state="failed", stage=stage, message=str(exc) or "Interrupted")
        try:
            # Preserve, but disarm, a worker-created or partially written marker.
            marker = directory / "SUCCESS"
            if marker.exists() or marker.is_symlink():
                index = 0
                while True:
                    rejected = directory / f"SUCCESS.rejected.{index}"
                    if not rejected.exists() and not rejected.is_symlink():
                        marker.rename(rejected)
                        break
                    index += 1
            publish_manifest(directory, manifest)
        except OSError as receipt_error:
            print(f"receipt: {receipt_error}", file=sys.stderr)
        print(f"{stage}: {manifest['message']}", file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("run", help="Run a frozen CPU numerical card")
    command.add_argument("--card", required=True)
    command.add_argument("--driver", required=True)
    command.add_argument("--output-dir", required=True)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
