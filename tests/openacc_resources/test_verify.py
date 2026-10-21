"""Pure fixture/parser tests only. No GPU, compiler, native binary or subprocess."""
from collections import Counter
from fractions import Fraction
import json
from pathlib import Path
import struct
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from selftest_support import (execution_notifications, make_evidence, notification,
                              stderr_bytes, stdout_bytes, verify, write_json)


@pytest.fixture
def manifest():
    return verify.load_manifest(verify.FROZEN)


def bits(value):
    return struct.pack(">d", float(value)).hex()


def test_static_fixture_values_are_exact_dyadic_addition(manifest):
    assert manifest["protocol"] == "M3B0 1"
    assert len(manifest["values"]) == 79
    for tag, index, inp, out, device in manifest["values"]:
        exact = Fraction(index-9, 8) if tag == "A" else -Fraction(index+3, 16)
        assert inp == bits(exact) and out == bits(exact+1) and device == 1
    a = [row[2:4] for row in manifest["values"] if row[0] == "B"]
    b = [row[2:4] for row in manifest["values"] if row[0] == "B_AFTER_A_FREE"]
    assert a == b


def test_static_resource_prefixes_unwinds_and_totals(manifest):
    events = manifest["resource_events"]
    assert len(events) == 240
    counts = Counter(row[3] for row in events)
    assert counts == {"H_ALLOC": 36, "H_FREE": 36, "D_ALLOC": 27, "D_FREE": 27,
                      "MAP": 27, "UNMAP": 27, "PRESENT": 54, "H_FAIL": 3, "D_FAIL": 3}
    for k, count in enumerate((1, 3, 5, 7, 13, 19), 1):
        failed = [r for r in events if r[:2] == ["T", 2*k-1]]
        recovered = [r for r in events if r[:2] == ["T", 2*k]]
        assert len(failed) == count and len(recovered) == 24
        assert sum(r[3].endswith("_FAIL") for r in failed) == 1
        for group in (failed, recovered):
            for acquire, release in (("H_ALLOC", "H_FREE"), ("D_ALLOC", "D_FREE"), ("MAP", "UNMAP")):
                assert [r[2] for r in group if r[3] == acquire][::-1] == [r[2] for r in group if r[3] == release]
    assert all(row[4] == (20 if row[2] == "MARK" else 40) for row in events if row[0] == "T")


def test_valid_invented_protocol(manifest):
    assert len(stdout_bytes(manifest).splitlines()) == 96
    verify.parse_stdout(stdout_bytes(manifest), manifest)
    counts = verify.parse_stderr(stderr_bytes(manifest), manifest)
    assert counts["resource_events"] == 240
    assert counts["kernels"] == 3 and counts["upload_bytes"] == 1332 and counts["download_bytes"] == 948
    assert counts["peak_live_objects"] == [6, 6, 6]


def test_stderr_accepts_unicode_nvidia_file_metadata(manifest):
    raw = stderr_bytes(manifest).decode().replace("file=SELFTEST", "file=/mnt/d/科学计算/工程/gpu-nci/fixture.f90")
    result = verify.parse_stderr(raw.encode("utf-8"), manifest)
    assert result["kernels"] == 3 and result["resource_events"] == 240


@pytest.mark.parametrize("suffix", [b"\xff", b"\xc3\x28", b"\x00"])
def test_stderr_rejects_malformed_utf8_and_control(manifest, suffix):
    with pytest.raises(verify.Rejected):
        verify.parse_stderr(stderr_bytes(manifest)+suffix, manifest)


def test_runtime_allows_transfer_pair_order_and_later_a_input(manifest):
    lines = stderr_bytes(manifest).decode().splitlines()
    a_input = next(i for i, line in enumerate(lines) if line.startswith("upload"))
    upload = lines.pop(a_input)
    b_input = next(i for i, line in enumerate(lines) if line.startswith("upload"))
    lines.insert(b_input+1, upload)
    # Metadata and OUT/MARK transfer ordering are not extra protocol restrictions.
    for start in ("upload", "download"):
        indices = [i for i, line in enumerate(lines) if line.startswith(start)]
        if start == "upload": indices = indices[2:]
        for a, b in zip(indices[::2], indices[1::2]):
            lines[a], lines[b] = lines[b], lines[a]
    verify.parse_stderr(("\n".join(lines)+"\n").encode(), manifest)


@pytest.mark.parametrize("mutation", ["header", "truncated", "extra", "blank", "nonascii", "control",
    "fail_status", "recover_status", "live", "pair_order", "fail_duplicate", "value_duplicate",
    "value_order", "input", "output", "device", "hex_length", "nan", "done", "end", "extra_token", "plus_integer"])
def test_stdout_negative(manifest, mutation):
    lines = stdout_bytes(manifest).decode().splitlines()
    if mutation == "header": lines[0] = "M3B0 2"
    elif mutation == "truncated": lines.pop()
    elif mutation == "extra": lines.append("EXTRA")
    elif mutation == "blank": lines[1] = ""
    elif mutation == "nonascii": lines[1] += "é"
    elif mutation == "control": lines[1] += "\x00"
    elif mutation == "fail_status": lines[1] = "FAIL 1 0 0 0 0"
    elif mutation == "recover_status": lines[2] = "RECOVER 1 5 0 0 0"
    elif mutation == "live": lines[1] = "FAIL 1 5 0 1 0"
    elif mutation == "pair_order": lines[1], lines[2] = lines[2], lines[1]
    elif mutation == "fail_duplicate": lines[3] = lines[1]
    elif mutation == "value_duplicate": lines[14] = lines[13]
    elif mutation == "value_order": lines[13], lines[14] = lines[14], lines[13]
    elif mutation in ("input", "output", "device", "hex_length", "nan", "extra_token", "plus_integer"):
        row = lines[13].split()
        if mutation == "input": row[3] = "0000000000000000"
        elif mutation == "output": row[4] = "3ff0000000000000"
        elif mutation == "device": row[5] = "0"
        elif mutation == "hex_length": row[3] = "0"
        elif mutation == "nan": row[4] = "7ff8000000000000"
        elif mutation == "extra_token": row.append("EXTRA")
        elif mutation == "plus_integer": row[2] = "+1"
        lines[13] = " ".join(row)
    elif mutation == "done": lines[30] = "DONE B 0"
    elif mutation == "end": lines[-1] = "END 6 6 79 3 1 0 0"
    with pytest.raises(verify.Rejected):
        verify.parse_stdout(("\n".join(lines)+"\n").encode(), manifest)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "swap", "generation", "buffer", "action",
    "bytes", "present", "result", "host_early_free", "truncated_resource", "kernel_missing", "kernel_extra",
    "upload_missing", "download_missing", "wrong_device", "wrong_bytes", "missing_bytes", "missing_device",
    "duplicate_bytes", "malformed_runtime", "recovery_kernel", "b_release_early", "poison_order", "host_fallback"])
def test_stderr_negative(manifest, mutation):
    lines = stderr_bytes(manifest).decode().splitlines()
    resources = [i for i, s in enumerate(lines) if s.startswith("M3B0_RESOURCE")]
    launches = [i for i, s in enumerate(lines) if s.startswith("launch")]
    uploads = [i for i, s in enumerate(lines) if s.startswith("upload")]
    downloads = [i for i, s in enumerate(lines) if s.startswith("download")]
    target = resources[20]
    if mutation == "missing": lines.pop(target)
    elif mutation == "duplicate": lines.insert(target, lines[target])
    elif mutation == "swap": lines[resources[1]], lines[resources[2]] = lines[resources[2]], lines[resources[1]]
    elif mutation in ("generation", "buffer", "action", "bytes", "present", "result", "host_early_free"):
        if mutation == "present": target = next(i for i in resources if " PRESENT " in lines[i])
        row = lines[target].split()
        if mutation == "generation": row[2] = "99"
        elif mutation == "buffer": row[3] = "OUT" if row[3] == "IN" else "IN"
        elif mutation == "action": row[4] = "UNKNOWN"
        elif mutation == "bytes": row[5] = "41"
        elif mutation == "present": row[6] = "0"
        elif mutation == "result": row[6] = "5"
        elif mutation == "host_early_free": row[4] = "H_FREE"
        lines[target] = " ".join(row)
    elif mutation == "truncated_resource": lines[target] = "M3B0_RESOURCE T"
    elif mutation == "kernel_missing": lines.pop(launches[0])
    elif mutation == "kernel_extra": lines.insert(launches[0], notification("launch"))
    elif mutation == "upload_missing": lines.pop(uploads[0])
    elif mutation == "download_missing": lines.pop(downloads[0])
    elif mutation == "wrong_device": lines[launches[0]] = lines[launches[0]].replace("device=0", "device=1")
    elif mutation == "wrong_bytes": lines[uploads[0]] = lines[uploads[0]].replace("bytes=136", "bytes=137")
    elif mutation == "missing_bytes": lines[uploads[0]] = lines[uploads[0]].replace(" bytes=136", "")
    elif mutation == "missing_device": lines[launches[0]] = lines[launches[0]].replace(" device=0", "")
    elif mutation == "duplicate_bytes": lines[uploads[0]] += " bytes=136"
    elif mutation == "malformed_runtime": lines[uploads[0]] = "upload SELFTEST bytes=136 device=0"
    elif mutation == "recovery_kernel": lines.insert(1, notification("launch"))
    elif mutation == "b_release_early":
        third = lines[launches[2]]
        lines.pop(launches[2])
        lines.append(third)
    elif mutation == "poison_order": lines[uploads[2]], lines[launches[0]] = lines[launches[0]], lines[uploads[2]]
    elif mutation == "host_fallback": lines[launches[0]] = "launch host kernel device=0"
    with pytest.raises(verify.Rejected):
        verify.parse_stderr(("\n".join(lines)+"\n").encode(), manifest)


def verify_evidence(tmp_path, evidence):
    path = tmp_path / "evidence.json"
    write_json(path, evidence)
    run = evidence.get("run", {})
    return verify.verify_files(verify.FROZEN, run.get("stdout", {}).get("path"), run.get("stderr", {}).get("path"), path)


def test_positive_invented_evidence_is_explicitly_fixture_only(tmp_path):
    _, evidence = make_evidence(tmp_path)
    result = verify_evidence(tmp_path, evidence)
    assert result["status"] == "PASS" and result["source_files"] == 3
    assert "not device acceptance" in result["scope"]


@pytest.mark.parametrize("mutation", ["state", "schema_bool", "unknown_key", "device_bool", "device_zero",
    "selected_bool", "selected_wrong", "no_identity", "returncode_bool", "returncode_three", "timeout",
    "timeout_bool", "command_extra", "command_missing", "stdin", "input", "notify", "sync", "device_env",
    "absent_env", "bytes_bool", "hash", "empty_binary", "runtime_binding", "source_dirty", "source_commit",
    "source_capture", "source_index", "source_duplicate", "source_file_drift", "compiler_empty", "receipt_extra"])
def test_evidence_negative(tmp_path, mutation):
    _, e = make_evidence(tmp_path)
    run = e["run"]
    if mutation == "state": e["state"] = "no_candidate"
    elif mutation == "schema_bool": e["schema_version"] = True
    elif mutation == "unknown_key": e["unknown"] = 1
    elif mutation == "device_bool": e["device_count"] = True
    elif mutation == "device_zero": e["device_count"] = 0
    elif mutation == "selected_bool": e["selected_device"] = False
    elif mutation == "selected_wrong": e["selected_device"] = 1
    elif mutation == "no_identity": e["device_identity"] = ""
    elif mutation == "returncode_bool": run["returncode"] = False
    elif mutation == "returncode_three": run["returncode"] = 3
    elif mutation == "timeout": run["timed_out"] = True
    elif mutation == "timeout_bool": run["timeout_seconds"] = True
    elif mutation == "command_extra": run["command"].append("extra")
    elif mutation == "command_missing": del run["command"]
    elif mutation == "stdin": run["stdin_mode"] = "inherit"
    elif mutation == "input": run["input_mode"] = "stdin"
    elif mutation == "notify": run["environment"]["NVCOMPILER_ACC_NOTIFY"] = "3"
    elif mutation == "sync": run["environment"]["CUDA_LAUNCH_BLOCKING"] = "1"
    elif mutation == "device_env": run["environment"]["ACC_DEVICE_TYPE"] = "host"
    elif mutation == "absent_env": del run["environment"]["PGI_ACC_SYNCHRONOUS"]
    elif mutation == "bytes_bool": run["stdout"]["bytes"] = True
    elif mutation == "hash": run["stdout"]["sha256"] = "0"*64
    elif mutation == "empty_binary":
        Path(run["binary"]["path"]).write_bytes(b"")
        run["binary"] = verify.fingerprint(run["binary"]["path"])
    elif mutation == "runtime_binding":
        copy = tmp_path / "same-content.stderr"
        copy.write_bytes(Path(run["stderr"]["path"]).read_bytes())
        e["runtime_evidence"] = verify.fingerprint(copy)
    elif mutation == "source_dirty": e["source_snapshots"][0]["clean_after"] = False
    elif mutation == "source_commit": e["source_snapshots"][0]["commit"] = "c"*40
    elif mutation == "source_capture":
        capture = e["source_snapshots"][0]["after"]["status"]
        Path(capture["path"]).write_bytes(b" M changed\n")
        e["source_snapshots"][0]["after"]["status"] = verify.fingerprint(capture["path"])
    elif mutation in ("source_index", "source_duplicate", "source_file_drift"):
        path = Path(e["source_manifest"]["path"])
        source = json.loads(path.read_text())
        if mutation == "source_index": source["files"].pop()
        elif mutation == "source_duplicate": source["files"].append(source["files"][0])
        else: source["files"][0]["sha256"] = "0"*64
        write_json(path, source)
        e["source_manifest"] = verify.fingerprint(path)
    elif mutation == "compiler_empty":
        path = Path(e["compiler_report"]["path"])
        path.write_bytes(b"")
        e["compiler_report"] = verify.fingerprint(path)
    elif mutation == "receipt_extra": run["binary"]["extra"] = 1
    with pytest.raises((verify.Rejected, KeyError)):
        verify_evidence(tmp_path, e)


@pytest.mark.parametrize("payload", [b'{"schema_version":1,"schema_version":1}', b'{"n":NaN}', b'{"n":Infinity}'])
def test_strict_json(payload):
    with pytest.raises(verify.Rejected):
        verify.strict_json(payload)


def test_manifest_is_immutable(tmp_path):
    file = tmp_path / "manifest.json"
    file.write_bytes(verify.FROZEN.read_bytes()+b" ")
    with pytest.raises(verify.Rejected):
        verify.load_manifest(file)


def test_output_argument_cannot_substitute_same_content(tmp_path):
    _, e = make_evidence(tmp_path)
    path = tmp_path / "evidence.json"
    write_json(path, e)
    copy = tmp_path / "substituted.stdout"
    copy.write_bytes(Path(e["run"]["stdout"]["path"]).read_bytes())
    with pytest.raises(verify.Rejected):
        verify.verify_files(verify.FROZEN, copy, e["run"]["stderr"]["path"], path)


def test_b_after_a_free_is_compared_to_frozen_values(manifest):
    lines = stdout_bytes(manifest).decode().splitlines()
    position = next(i for i, line in enumerate(lines) if line.startswith("VALUE B_AFTER_A_FREE"))
    row = lines[position].split()
    row[4] = "0000000000000000"
    lines[position] = " ".join(row)
    with pytest.raises(verify.Rejected):
        verify.parse_stdout(("\n".join(lines)+"\n").encode(), manifest)


def test_artifacts_are_rehashed_after_comparison(tmp_path, monkeypatch):
    _, e = make_evidence(tmp_path)
    real_parse = verify.parse_stdout
    def changed_after_initial_receipt(data, manifest):
        real_parse(data, manifest)
        Path(e["run"]["binary"]["path"]).write_bytes(b"changed during comparison")
    monkeypatch.setattr(verify, "parse_stdout", changed_after_initial_receipt)
    with pytest.raises(verify.Rejected, match="artifact changed"):
        verify_evidence(tmp_path, e)


def test_cli_pass_failed_not_tested_and_exclusive_report(tmp_path):
    _, e = make_evidence(tmp_path)
    path, report = tmp_path / "evidence.json", tmp_path / "report.json"
    write_json(path, e)
    args = ["--verify", "--manifest", str(verify.FROZEN), "--evidence", str(path), "--report", str(report)]
    executed = args + ["--stdout", e["run"]["stdout"]["path"], "--stderr", e["run"]["stderr"]["path"]]
    assert verify.main(executed) == 0
    original = report.read_bytes()
    assert verify.main(executed) == 1 and report.read_bytes() == original
    failed = tmp_path / "failed.json"
    e["run"]["returncode"] = 3
    write_json(path, e)
    assert verify.main([str(failed) if x == str(report) else x for x in executed]) == 1
    no_device = {key: e[key] for key in ("schema_version", "manifest", "contract")}
    no_device.update(state="no_device", device_count=0, reason="SELFTEST invented missing inventory")
    write_json(path, no_device)
    nt = tmp_path / "not-tested.json"
    assert verify.main([str(nt) if x == str(report) else x for x in args]) == 2
    assert json.loads(nt.read_text())["status"] == "NOT_TESTED"
    no_device["run"] = e["run"]
    with pytest.raises(verify.Rejected):
        verify_evidence(tmp_path, no_device)
