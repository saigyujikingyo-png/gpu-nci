#!/usr/bin/env python3
"""Explicit fixed mode0..5 qualification, never CTest/native default execution.

Requires a separately frozen controller/card. Maximum 31 ABI calls, 24 field
launches and 12 contexts; all N9 synthetic. No formal performance samples.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys

from qualify_probe import Record, encode_record

EXPECTED = {0: (1, 0, 2), 1: (-1, 4, 0), 2: (-1, 4, 1),
            3: (-1, 6, 2), 4: (-1, 7, 2), 5: (-1, 5, 2)}
CALLS = ("baseline_a", "early_refusal_a", "sibling_b", "admitted_a", "recovered_a")
RESULTS = ("overall", "create_a", "create_b", "arm1_before_clear0", "set_mode", "baseline_a_status",
           "early_refusal_a_status", "sibling_b_status", "admitted_a_status", "recovered_a_status",
           "cleanup_a", "cleanup_b", "outputs_equal", "early_refusal_unmodified", "input_unmodified",
           "getters_valid", "sibling_record_isolated", "admitted_record_expected", "recovered_record_valid",
           "executed_abi_calls", "baderrbuf_status", "baderrbuf_historical_record_preserved",
           "baderrbuf_outputs_unmodified", "baderrbuf_sample_eligible", "baderrbuf_observe_rejected_stale")


def expected_results(mode):
    return [0, 0, 0, 0 if mode == 0 else -1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
            6 if mode == 0 else 5] + ([1, 0, 0, 0, 0] if mode == 0 else [-1] * 5)


def fault_receipt(mode, results, records, bits, flags, stats):
    observations, nonfinite = [], []
    for index, record in enumerate(records):
        encoded, anomalies = encode_record(record)
        raw = ctypes.string_at(ctypes.addressof(record), ctypes.sizeof(Record))
        encoded["raw_record_bytes_hex"] = raw.hex()
        encoded["timing_ieee754_binary64_bits_hex"] = {
            name: f"0x{int.from_bytes(raw[getattr(Record, name).offset:getattr(Record, name).offset+8], sys.byteorder):016x}"
            for name in ("kernel_seconds", "device_seconds")}
        observations.append(encoded)
        nonfinite.extend({"record_index": index, **item} for item in anomalies)
    snapshots = []
    for index, label in enumerate(CALLS + ("baderrbuf_early_guard_a",)):
        values = [f"0x{int(bits[index*972+j]) & ((1 << 64)-1):016x}" for j in range(972)]
        snapshots.append({"call": label, "executed": results[5+index if index < 5 else 20] >= 0,
                          "fields_ieee64_hex": {name: values[j*324:(j+1)*324]
                                                for j, name in enumerate(("rdg", "lambda2", "signedrho"))},
                          "flags_u8": [int(flags[index*324+j]) & 255 for j in range(324)],
                          "stats_int64": [int(stats[index*11+j]) for j in range(11)]})
    state, error, created = EXPECTED[mode]
    receipt = {"protocol_version": 1, "scope": "synthetic event fault qualification; no formal timing/performance sample",
               "mode": mode, "expected_admitted_timing": {"state": state, "timing_error": error,
               "events_created": created, "events_destroyed": created}, "global_shape": [9, 9, 9],
               "tile_count": [4, 9, 9], "input_shape": [6, 9, 9], "fixture": "rho=0.5; j_inv=I",
               "maximum_abi_calls": 6 if mode == 0 else 5, "maximum_field_launches": 4, "maximum_contexts": 2,
               "result_slots": list(RESULTS), "results": list(results),
               "record_slots": ["baseline_a", "early_refusal_a", "sibling_b", "admitted_a", "recovered_a",
                                "sibling_b_after_a", "baderrbuf_historical_a"],
               "entry_boundary": "record resets only after errbuf and live-context entry; baderrbuf is not a current sample",
               "records": observations, "nonfinite_diagnostics": nonfinite, "output_snapshots": snapshots}
    errors = validate_fault_receipt(receipt)
    receipt.update(state="FAULT_QUALIFICATION_PASS" if not errors else "FAULT_QUALIFICATION_FAIL", errors=errors)
    return receipt


def validate_fault_receipt(receipt):
    """Pure independent protocol check; expected state -1 is intentional only."""
    errors = []
    mode = receipt["mode"]
    if receipt["results"] != expected_results(mode):
        errors.append("native status/control/cleanup/count differs from fixed sequence")
    if receipt["nonfinite_diagnostics"]:
        errors.append("nonfinite private timing")
    rows = receipt["records"]
    for index in (0, 2, 4, 5):
        row = rows[index]
        if any(row[key] != expected for key, expected in (("state", 1), ("timing_error", 0), ("observed_threads", 0),
                ("kernel_count", 1), ("events_created", 2), ("events_destroyed", 2), ("async_queue", 1), ("reserved", 0))):
            errors.append(f"unexpected normal timing record {index}")
        if row["stream_handle"] == 0:
            errors.append(f"missing normal stream {index}")
        for name in ("kernel_seconds", "device_seconds"):
            value = row[name]
            if not isinstance(value, (int, float)) or value < 0 or (name == "kernel_seconds" and value > .5):
                errors.append(f"invalid normal interval {index}/{name}")
    if any(rows[1][key] != 0 for key in (name for name, _ in Record._fields_)):
        errors.append("early common refusal did not reset timing")
    state, error, created = EXPECTED[mode]
    admitted = rows[3]
    if any(admitted[key] != value for key, value in (("state", state), ("timing_error", error),
            ("events_created", created), ("events_destroyed", created), ("observed_threads", 0),
            ("kernel_count", 1), ("async_queue", 1), ("reserved", 0))):
        errors.append("admitted event-fault state/error/create/destroy mismatch")
    if mode and admitted["kernel_seconds"] != 0:
        errors.append("faulted kernel timing must remain zero")
    if mode == 5 and admitted["stream_handle"] != 0:
        errors.append("null-stream fault did not retain null observation")
    if mode != 5 and admitted["stream_handle"] == 0:
        errors.append("unexpected missing admitted stream")
    for name in ("kernel_seconds", "device_seconds"):
        value = admitted[name]
        if not isinstance(value, (int, float)) or value < 0 or (name == "kernel_seconds" and value > .5):
            errors.append(f"invalid admitted interval/{name}")
    if rows[2]["raw_record_bytes_hex"] != rows[5]["raw_record_bytes_hex"]:
        errors.append("sibling context timing changed")
    if mode == 0 and rows[0]["raw_record_bytes_hex"] != rows[6]["raw_record_bytes_hex"]:
        errors.append("baderrbuf early guard did not preserve historical timing")
    snapshots = receipt["output_snapshots"]
    baseline = {key: snapshots[0][key] for key in ("fields_ieee64_hex", "flags_u8", "stats_int64")}
    for row in snapshots[:5] + (snapshots[5:] if mode == 0 else []):
        if not row["executed"] or any(row[key] != baseline[key] for key in baseline):
            errors.append(f"science output/stats changed or call missing: {row['call']}")
    return errors


def write_new(path, receipt):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, allow_nan=False)
        stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (os.name != "posix" or not args.library.is_absolute() or args.library.is_symlink()
            or not args.library.is_file() or not args.output.is_absolute() or args.output.exists()):
        parser.error("requires frozen Linux OpenACC bridge and a new absolute output directory")
    args.output.mkdir(mode=0o700)
    write_new(args.output / "invocation.json", {"modes": list(EXPECTED), "maximum_abi_calls": 31,
              "maximum_field_launches": 24, "maximum_contexts": 12,
              "execution": "separate frozen qualification card; no default run or retries"})
    parent = os.open(args.output.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    library = ctypes.CDLL(str(args.library))
    native = library.nci_test_timing_fault_probe_v1
    native.argtypes = [ctypes.c_int32, ctypes.POINTER(ctypes.c_int32), ctypes.POINTER(Record),
                       ctypes.POINTER(ctypes.c_int64), ctypes.POINTER(ctypes.c_int8), ctypes.POINTER(ctypes.c_int64)]
    native.restype = None
    receipts = []
    for mode in EXPECTED:
        results, records = (ctypes.c_int32 * 25)(), (Record * 7)()
        bits, flags, stats = (ctypes.c_int64 * 5832)(), (ctypes.c_int8 * 1944)(), (ctypes.c_int64 * 66)()
        native(mode, results, records, bits, flags, stats)
        receipt = fault_receipt(mode, results, records, bits, flags, stats)
        write_new(args.output / f"fault_mode{mode}.json", receipt)
        receipts.append({"mode": mode, "state": receipt["state"], "receipt": f"fault_mode{mode}.json"})
        if receipt["state"] != "FAULT_QUALIFICATION_PASS":
            break
    passed = len(receipts) == 6 and all(row["state"] == "FAULT_QUALIFICATION_PASS" for row in receipts)
    write_new(args.output / "qualification.json", {"state": "FAULT_QUALIFICATION_PASS" if passed else "FAULT_QUALIFICATION_FAIL",
              "modes": receipts, "expected_modes": list(EXPECTED), "formal_samples": 0})
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
