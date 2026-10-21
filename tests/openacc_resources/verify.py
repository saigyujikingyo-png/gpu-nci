"""Compare-only M3B0 verifier. Never starts a candidate or invokes git."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

FROZEN = Path(__file__).resolve().parent / "frozen" / "manifest.json"
FROZEN_SHA256 = "fc63b07d695ba4540eda8261dc2a4e6d3ac2c94fea18ff49697f8e76d6c1ce48"
CONTRACT_SHA256 = "d0cb92529e83837dcc604e1b34508af9bbc69976fd53ccac1143b55b914e7413"
CAP = 8 * 1024 * 1024
ENVIRONMENT = {
    "NVCOMPILER_ACC_NOTIFY": "31", "ACC_DEVICE_TYPE": "nvidia", "ACC_DEVICE_NUM": "0",
    "NVCOMPILER_ACC_SYNCHRONOUS": None, "PGI_ACC_SYNCHRONOUS": None,
    "CUDA_LAUNCH_BLOCKING": None,
}
SCOPE = ("Finite M3B0 synthetic resource/transport checks only. Pure selftests use "
         "invented logs and non-executable placeholder files; they are not device acceptance. "
         "No public backend, NCI fields, scientific acceptance or performance is established.")


class Rejected(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Rejected(message)


def exact_keys(obj, keys, label):
    require(type(obj) is dict and set(obj) == set(keys), f"{label}: wrong keys")


def integer(value, label):
    require(type(value) is int, f"{label}: integer required, not bool")
    return value


def small(path):
    with Path(path).open("rb") as stream:
        data = stream.read(CAP + 1)
    require(len(data) <= CAP, "parsed artifact exceeds 8 MiB")
    return data


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, f"duplicate JSON key: {key}")
            result[key] = value
        return result
    def constant(value):
        raise Rejected(f"nonfinite JSON constant: {value}")
    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


def fingerprint(path):
    path = Path(path).resolve(strict=True)
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return {"path": str(path), "sha256": digest.hexdigest(), "bytes": size}


def check_receipt(item, checked, label, nonempty=False):
    exact_keys(item, ("path", "sha256", "bytes"), label)
    require(type(item["path"]) is str and Path(item["path"]).is_absolute(), f"{label}: absolute path required")
    require(str(Path(item["path"]).resolve(strict=True)) == item["path"], f"{label}: canonical path required")
    require(type(item["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]), f"{label}: SHA256")
    size = integer(item["bytes"], label + ".bytes")
    require(size >= (1 if nonempty else 0), f"{label}: size")
    actual = fingerprint(item["path"])
    require(actual == item, f"{label}: artifact path/hash/size mismatch")
    checked.append(item)
    return Path(item["path"])


def uint(token):
    require(re.fullmatch(r"0|[1-9][0-9]*", token) is not None, "noncanonical unsigned decimal")
    return int(token)


def ascii_lines(data, label):
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise Rejected(f"{label}: non-ASCII") from exc
    require(not any(ord(c) < 32 and c not in "\t\r\n" for c in text), f"{label}: control character")
    return text.splitlines()


def stderr_lines(data):
    # NVIDIA metadata may contain the UTF-8 source path, including Chinese names.
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Rejected("stderr: malformed UTF-8") from exc
    require(not any(ord(c) < 32 and c not in "\t\r\n" for c in text), "stderr: control character")
    return text.splitlines()


def load_manifest(path):
    raw = small(path)
    require(hashlib.sha256(raw).hexdigest() == FROZEN_SHA256, "manifest differs from frozen fixture")
    require(raw == small(FROZEN), "manifest differs from committed fixture")
    return strict_json(raw)


def parse_stdout(data, manifest):
    lines = ascii_lines(data, "stdout")
    require(len(lines) == 96 and all(line.strip() for line in lines), "stdout: expected exactly 96 nonempty lines")
    rows = [line.split() for line in lines]
    require(rows[0] == ["M3B0", "1"], "stdout header")
    position = 1
    for k in range(1, 7):
        for tag, status in (("FAIL", 5), ("RECOVER", 0)):
            row = rows[position]
            require(len(row) == 6 and row[0] == tag, "FAIL/RECOVER shape/order")
            require([uint(t) for t in row[1:]] == [k, status, 0, 0, 0], "FAIL/RECOVER index/status/ownership")
            position += 1
    for tag, n in (("A", 17), ("B", 31), ("B_AFTER_A_FREE", 31)):
        expected = [row for row in manifest["values"] if row[0] == tag]
        require(len(expected) == n, "frozen VALUE count")
        for wanted in expected:
            row = rows[position]
            require(len(row) == 6 and row[:2] == ["VALUE", tag], "VALUE shape/tag/order")
            require(uint(row[2]) == wanted[1] and uint(row[5]) == 1, "VALUE index/device")
            require(all(re.fullmatch(r"[0-9a-fA-F]{16}", t) for t in row[3:5]), "VALUE IEEE hex")
            require([t.lower() for t in row[3:5]] == wanted[2:4], "VALUE frozen input/output bits")
            position += 1
        require(rows[position] == ["DONE", tag, "0"], "DONE tag/status")
        position += 1
    require(position == 95 and rows[position] == ["END", "6", "6", "79", "3", "0", "0", "0"], "END counts/ownership")


def runtime_row(line, resource_position):
    """Allow NVHPC metadata fields; require unambiguous kind/device/byte count."""
    kind = line.split()[0]
    prefix = "launch CUDA kernel" if kind == "launch" else kind + " CUDA data"
    require(line.startswith(prefix) and (len(line) == len(prefix) or line[len(prefix)].isspace()), "malformed runtime notification")
    devices = re.findall(r"\bdevice\s*=\s*([0-9]+)\b", line)
    require(devices == ["0"], "runtime device must be NVIDIA device 0")
    sizes = re.findall(r"\bbytes\s*=\s*([0-9]+)\b", line)
    if kind == "launch":
        require(not sizes, "unexpected kernel byte count")
        size = 0
    else:
        require(len(sizes) == 1, "runtime transfer needs one byte count")
        size = uint(sizes[0])
    return kind, size, resource_position


def check_runtime(rows):
    require(len(rows) == 17, "runtime: expected 3 kernels, 8 uploads, 6 downloads")
    first = rows[:2]
    require(all(r[0] == "upload" for r in first) and sorted(r[1] for r in first) == [136, 248], "runtime input uploads")
    for _, size, phase in first:
        require(phase in ((204, 216) if size == 136 else (216,)), "input upload outside prepared workspace phase")
    cursor = 2
    for n, phase in ((17, 216), (31, 216), (31, 228)):
        for kind in ("upload", "launch", "download"):
            width = 1 if kind == "launch" else 2
            group = rows[cursor:cursor + width]
            require(all(r[0] == kind and r[2] == phase for r in group), "runtime kernel/poison/download phase/order")
            require(sorted(r[1] for r in group) == ([0] if width == 1 else [4*n, 8*n]), "runtime transfer byte sizes")
            cursor += width
    require(sum(r[1] for r in rows if r[0] == "upload") == 1332, "runtime upload bytes")
    require(sum(r[1] for r in rows if r[0] == "download") == 948, "runtime download bytes")


def parse_stderr(data, manifest):
    expected = manifest["resource_events"]
    host, device, mappings = {}, {}, {}
    peaks = [0, 0, 0, 0, 0]
    events, runtime = [], []
    for raw in stderr_lines(data):
        line = raw.strip()
        if line.startswith("M3B0_RESOURCE"):
            row = line.split()
            require(len(row) == 7 and row[0] == "M3B0_RESOURCE", "resource record shape")
            ws, generation, buf, action, size, result = row[1:]
            item = [ws, uint(generation), buf, action, uint(size), uint(result)]
            require(len(events) < 240 and item == expected[len(events)], "resource acquisition/unwind sequence")
            events.append(item)
            key = (ws, item[1], buf)
            if action == "H_ALLOC":
                require(key not in host, "duplicate host allocation")
                host[key] = item[4]
            elif action == "D_ALLOC":
                require(key in host and key not in device, "device allocation without private host owner")
                device[key] = item[4]
            elif action == "MAP":
                require(key in host and key in device and key not in mappings, "invalid map ownership")
                mappings[key] = item[4]
            elif action == "UNMAP":
                require(key in host and key in mappings, "unmap after host release")
                del mappings[key]
            elif action == "PRESENT":
                require(key in host and item[5] == int(key in mappings), "presence query/host lifetime")
            elif action == "D_FREE":
                require(key in device and key not in mappings, "device free before unmap")
                del device[key]
            elif action == "H_FREE":
                require(key in host and key not in device and key not in mappings, "host free before device release")
                del host[key]
            elif action in ("H_FAIL", "D_FAIL"):
                require(item[5] == 5, "injected allocation failure status")
            current = [len(host), len(device), len(mappings), sum(host.values()), sum(device.values())]
            peaks = [max(a, b) for a, b in zip(peaks, current)]
        elif line and line.split()[0].lower() in ("launch", "upload", "download"):
            runtime.append(runtime_row(line, len(events)))
    require(len(events) == 240, "resource events missing/truncated")
    require(not host and not device and not mappings, "nonzero final ownership")
    require(peaks == [6, 6, 6, 960, 960], "resource peak ownership/bytes")
    check_runtime(runtime)
    return {"resource_events": len(events), "actions": dict(Counter(row[3] for row in events)),
            "peak_live_objects": peaks[:3], "peak_host_bytes": peaks[3], "peak_device_bytes": peaks[4],
            "kernels": 3, "uploads": 8, "upload_bytes": 1332, "downloads": 6, "download_bytes": 948}


def check_sources(evidence, checked):
    path = check_receipt(evidence["source_manifest"], checked, "source_manifest", True)
    source = strict_json(small(path))
    exact_keys(source, ("schema_version", "root", "commit", "tree", "files"), "source manifest")
    require(integer(source["schema_version"], "source schema") == 1, "source schema")
    require(type(source["root"]) is str and Path(source["root"]).is_absolute(), "source root")
    root = Path(source["root"]).resolve(strict=True)
    require(str(root) == source["root"], "source root must be canonical")
    for key in ("commit", "tree"):
        require(type(source[key]) is str and re.fullmatch(r"[0-9a-f]{40}", source[key]), "source " + key)
    require(type(source["files"]) is list and source["files"], "source file index required")
    seen = set()
    for record in source["files"]:
        require(type(record) is dict and type(record.get("path")) is str, "source file path")
        file = Path(record["path"])
        require(file.is_absolute() and file.is_relative_to(root), "source file outside root")
        require(file.resolve(strict=True) == file and file.resolve(strict=True).is_relative_to(root), "source file must be canonical and inside root")
        relative = file.relative_to(root)
        require(not any(p.lower() in (".git", ".agents", ".codex", ".aws", ".ssh") or p.lower().startswith(".env") for p in relative.parts), "private file forbidden in public source index")
        require(str(file) not in seen, "duplicate source file")
        check_receipt(record, checked, "source file")
        seen.add(str(file))
    required = [root / "docs/openacc-resource-contract.md", root / "tests/openacc_resources/frozen/manifest.json", Path(__file__).resolve()]
    require(all(str(p) in seen for p in required), "source index omits contract/fixture/actual verifier")
    require(evidence["contract"]["path"] == str(required[0]), "contract source binding")
    require(evidence["manifest"]["path"] == str(required[1]), "fixture source binding")
    snapshots = evidence["source_snapshots"]
    require(type(snapshots) is list and len(snapshots) == 1, "one integrated source snapshot required")
    snapshot = snapshots[0]
    exact_keys(snapshot, ("role", "path", "commit", "tree", "clean_before", "clean_after", "before", "after"), "source snapshot")
    require(snapshot["role"] == "integrated" and snapshot["path"] == str(root), "integrated source path")
    require(snapshot["commit"] == source["commit"] and snapshot["tree"] == source["tree"], "source HEAD/tree differs from freeze")
    require(snapshot["clean_before"] is True and snapshot["clean_after"] is True, "source not clean before/after")
    for phase in ("before", "after"):
        exact_keys(snapshot[phase], ("head", "tree", "status"), "source capture")
        for key in ("head", "tree", "status"):
            capture = check_receipt(snapshot[phase][key], checked, phase + "." + key)
            expected = b"" if key == "status" else (source["commit" if key == "head" else "tree"] + "\n").encode("ascii")
            require(small(capture) == expected, "source capture dirty/drifted")
    return len(seen)


def verify_files(manifest_path, stdout_path, stderr_path, evidence_path):
    manifest = load_manifest(manifest_path)
    evidence = strict_json(small(evidence_path))
    require(type(evidence) is dict, "evidence object required")
    require(integer(evidence.get("schema_version"), "evidence schema") == 1, "evidence schema")
    checked = [fingerprint(evidence_path)]
    base = {"schema_version", "state", "manifest", "contract", "device_count"}
    state = evidence.get("state")
    if state == "no_device":
        exact_keys(evidence, base | {"reason"}, "no_device evidence")
        require(integer(evidence["device_count"], "device_count") == 0, "no_device count")
        require(type(evidence["reason"]) is str and evidence["reason"].strip(), "no_device reason")
        require(stdout_path is None and stderr_path is None, "no_device must not supply candidate outputs")
    else:
        require(state == "executed", "candidate was not executed; cannot PASS")
        exact_keys(evidence, base | {"runner", "source_manifest", "compiler_report", "source_snapshots", "run", "selected_device", "device_identity", "runtime_evidence"}, "executed evidence")
    fixture = check_receipt(evidence["manifest"], checked, "manifest", True)
    require(str(Path(manifest_path).resolve(strict=True)) == str(fixture), "manifest argument binding")
    require(evidence["manifest"]["sha256"] == FROZEN_SHA256, "fixture hash")
    check_receipt(evidence["contract"], checked, "contract", True)
    require(evidence["contract"]["sha256"] == CONTRACT_SHA256, "contract changed")
    if state == "no_device":
        require(all(fingerprint(item["path"]) == item for item in checked), "artifact changed during comparison")
        return {"status": "NOT_TESTED", "reason": evidence["reason"], "artifacts": checked, "scope": SCOPE}
    require(integer(evidence["device_count"], "device_count") >= 1, "no NVIDIA device")
    require(integer(evidence["selected_device"], "selected_device") == 0, "wrong device selection")
    require(type(evidence["device_identity"]) is str and evidence["device_identity"].strip(), "device identity required")
    check_receipt(evidence["runner"], checked, "runner", True)
    check_receipt(evidence["compiler_report"], checked, "compiler report", True)
    run = evidence["run"]
    exact_keys(run, ("binary", "stdout", "stderr", "command", "input_mode", "stdin_mode", "returncode", "timed_out", "timeout_seconds", "environment"), "run")
    binary = check_receipt(run["binary"], checked, "binary", True)
    stdout = check_receipt(run["stdout"], checked, "stdout", True)
    stderr = check_receipt(run["stderr"], checked, "stderr", True)
    require(stdout_path is not None and stderr_path is not None, "executed run requires output arguments")
    require(str(Path(stdout_path).resolve(strict=True)) == str(stdout) and str(Path(stderr_path).resolve(strict=True)) == str(stderr), "output argument binding")
    require(run["command"] == [str(binary)], "candidate command must have no arguments")
    require(run["input_mode"] == "none" and run["stdin_mode"] == "devnull", "candidate must receive no input")
    require(integer(run["returncode"], "returncode") == 0, "attempted nonzero exit is FAILED, not NOT_TESTED")
    require(run["timed_out"] is False, "attempted timeout is FAILED")
    require(integer(run["timeout_seconds"], "timeout_seconds") == 30, "candidate timeout must be 30 seconds")
    require(type(run["environment"]) is dict and run["environment"] == ENVIRONMENT, "runtime environment/force-sync binding")
    check_receipt(evidence["runtime_evidence"], checked, "runtime evidence", True)
    require(evidence["runtime_evidence"] == run["stderr"], "runtime evidence must be original stderr")
    source_count = check_sources(evidence, checked)
    parse_stdout(small(stdout), manifest)
    counts = parse_stderr(small(stderr), manifest)
    # Re-read every validated artifact after comparison, including all source files.
    require(all(fingerprint(item["path"]) == item for item in checked), "artifact changed during comparison")
    return {"status": "PASS", "counts": counts, "source_files": source_count, "artifacts": checked, "scope": SCOPE}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--stdout")
    parser.add_argument("--stderr")
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    try:
        result = verify_files(args.manifest, args.stdout, args.stderr, args.evidence)
    except (Rejected, OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        result = {"status": "FAILED", "reason": str(exc), "scope": SCOPE}
        result["available_artifacts"] = []
        for path in (args.manifest, args.stdout, args.stderr, args.evidence):
            if path is not None:
                try:
                    result["available_artifacts"].append(fingerprint(path))
                except OSError:
                    pass
    result["schema_version"] = 1
    result["verifier"] = fingerprint(__file__)
    try:
        with Path(args.report).open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.write("\n")
    except OSError as exc:
        print(f"FAILED: cannot exclusively create report: {exc}", file=sys.stderr)
        return 1
    print(result["status"])
    return {"PASS": 0, "FAILED": 1, "NOT_TESTED": 2}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
