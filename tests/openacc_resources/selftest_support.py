"""Invented evidence for pure verifier tests; no executable is ever run."""
import importlib.util
import json
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("m3b_resource_verifier", Path(__file__).with_name("verify.py"))
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


def stdout_bytes(manifest):
    lines = ["M3B0 1"]
    for k in range(1, 7):
        lines += [f"FAIL {k} 5 0 0 0", f"RECOVER {k} 0 0 0 0"]
    for tag in ("A", "B", "B_AFTER_A_FREE"):
        for row in manifest["values"]:
            if row[0] == tag:
                lines.append("VALUE " + " ".join(str(x) for x in row))
        lines.append(f"DONE {tag} 0")
    lines.append("END 6 6 79 3 0 0 0")
    return ("\n".join(lines) + "\n").encode("ascii")


def notification(kind, size=0):
    text = kind + (" CUDA kernel" if kind == "launch" else " CUDA data")
    text += " file=SELFTEST function=SELFTEST line=1 device=0 threadid=1"
    if kind != "launch":
        text += f" variable=SELFTEST bytes={size}"
    return text


def execution_notifications(n):
    return [notification("upload", 8*n), notification("upload", 4*n),
            notification("launch"), notification("download", 8*n), notification("download", 4*n)]


def stderr_bytes(manifest):
    lines = ["SELFTEST invented runtime and resource records; NOT device evidence"]
    for i, event in enumerate(manifest["resource_events"], 1):
        lines.append("M3B0_RESOURCE " + " ".join(str(x) for x in event))
        if i == 204:
            lines.append(notification("upload", 136))
        elif i == 216:
            lines.append(notification("upload", 248))
            lines += execution_notifications(17) + execution_notifications(31)
        elif i == 228:
            lines += execution_notifications(31)
    return ("\n".join(lines) + "\n").encode("ascii")


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def make_evidence(directory):
    manifest = verify.load_manifest(verify.FROZEN)
    root = Path(__file__).resolve().parents[2]
    binary, runner = directory / "not-an-executable", directory / "not-a-runner.txt"
    stdout, stderr = directory / "invented.stdout", directory / "invented.stderr"
    compiler = directory / "invented-build.txt"
    binary.write_bytes(b"SELFTEST placeholder, not an executable\n")
    runner.write_bytes(b"SELFTEST placeholder, never executed\n")
    compiler.write_bytes(b"SELFTEST invented build report, not compiler acceptance\n")
    stdout.write_bytes(stdout_bytes(manifest))
    stderr.write_bytes(stderr_bytes(manifest))
    source = {"schema_version": 1, "root": str(root), "commit": "a"*40, "tree": "b"*40,
              "files": [verify.fingerprint(p) for p in
                        (root / "docs/openacc-resource-contract.md", verify.FROZEN, Path(verify.__file__))]}
    source_path = directory / "invented-source.json"
    write_json(source_path, source)
    snapshot = {"role": "integrated", "path": str(root), "commit": source["commit"], "tree": source["tree"],
                "clean_before": True, "clean_after": True}
    for phase in ("before", "after"):
        snapshot[phase] = {}
        for key, text in (("head", source["commit"]+"\n"), ("tree", source["tree"]+"\n"), ("status", "")):
            path = directory / f"invented-{phase}-{key}.txt"
            path.write_text(text, encoding="ascii")
            snapshot[phase][key] = verify.fingerprint(path)
    evidence = {
        "schema_version": 1, "state": "executed", "manifest": verify.fingerprint(verify.FROZEN),
        "contract": verify.fingerprint(root / "docs/openacc-resource-contract.md"),
        "runner": verify.fingerprint(runner), "source_manifest": verify.fingerprint(source_path),
        "compiler_report": verify.fingerprint(compiler), "source_snapshots": [snapshot],
        "run": {"binary": verify.fingerprint(binary), "stdout": verify.fingerprint(stdout),
                "stderr": verify.fingerprint(stderr), "command": [str(binary)], "input_mode": "none",
                "stdin_mode": "devnull", "returncode": 0, "timed_out": False, "timeout_seconds": 30,
                "environment": dict(verify.ENVIRONMENT)},
        "device_count": 1, "selected_device": 0, "device_identity": "SELFTEST invented NVIDIA identity",
        "runtime_evidence": verify.fingerprint(stderr),
    }
    return manifest, evidence
