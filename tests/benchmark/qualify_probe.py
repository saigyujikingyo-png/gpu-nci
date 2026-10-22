#!/usr/bin/env python3
"""Explicit native qualification entry, never run by pure test discovery.

This launches science only under the separate frozen qualification controller.
It does not generate performance inputs or contribute formal benchmark samples.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import struct
import sys
import time


class Record(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int32) for name in
                ("state", "timing_error", "observed_threads", "kernel_count", "events_created",
                 "events_destroyed", "async_queue", "reserved")] + [
                     ("stream_handle", ctypes.c_int64), ("kernel_seconds", ctypes.c_double),
                     ("device_seconds", ctypes.c_double)]


def encode_binary64(value, bits):
    """Keep finite values unchanged; retain exact nonfinite bits as JSON data."""
    exponent = (bits >> 52) & 0x7ff
    mantissa = bits & ((1 << 52) - 1)
    if exponent != 0x7ff:
        return value, False
    sign = bits >> 63
    diagnostic = {"classification": "nan" if mantissa else "negative_infinity" if sign else "positive_infinity",
                  "ieee754_binary64_bits_hex": f"0x{bits:016x}", "signbit": sign}
    if mantissa:
        diagnostic["nan_kind"] = "quiet" if mantissa & (1 << 51) else "signaling"
    return diagnostic, True


def encode_record(record):
    """Read IEEE bits from the original C storage, before Python FP handling."""
    encoded, anomalies = {}, []
    for name, kind in Record._fields_:
        value = getattr(record, name)
        if kind is ctypes.c_double:
            raw = ctypes.string_at(ctypes.addressof(record) + getattr(Record, name).offset, 8)
            bits = int.from_bytes(raw, sys.byteorder)
            value, nonfinite = encode_binary64(value, bits)
            if nonfinite:
                anomalies.append({"field": name, **value})
        encoded[name] = value
    return encoded, anomalies


def probe_receipt(n, backend, threads, results, records, elapsed):
    encoded_records, anomalies = [], []
    for index, record in enumerate(records):
        encoded, fields = encode_record(record)
        encoded_records.append(encoded)
        anomalies.extend({"record_index": index, **item} for item in fields)
    elapsed_bits = int.from_bytes(struct.pack("=d", elapsed), sys.byteorder)
    elapsed_value, invalid_elapsed = encode_binary64(elapsed, elapsed_bits)
    if invalid_elapsed:
        anomalies.append({"field": "wall_seconds", **elapsed_value})
    passed = results[0] == 0 and not anomalies
    return {"state": "QUALIFICATION_PROBE_PASS" if passed else "QUALIFICATION_PROBE_FAIL",
            "scope": "synthetic launch qualification; not a stored-water worst-case bound or formal performance sample",
            "n": n, "backend": backend, "threads": threads,
            "global_shape": [n] * 3, "tile_count": [4, n, n],
            "tile_start": [4, 0, 0] if n == 384 else [0, 0, 0],
            "input_origin": [2, 0, 0] if n == 384 else [0, 0, 0],
            "input_shape": [8 if n == 384 else 6, n, n],
            "fixture": "pinned mixed quadratic v1 coefficients; q=(global_index-192)/256; j_inv=256I"
            if n == 384 else "constant rho=0.5; j_inv=I",
            "maximum_evaluations": 1 if n == 384 else 4,
            "result_slots": ["overall", "create_a", "create_b", "evaluate_a", "evaluate_b", "invalid_a",
                             "reevaluate_a", "cleanup_a", "cleanup_b", "handles_cleanup_attempted"],
            "results": list(results), "wall_seconds": elapsed_value,
            "nonfinite_diagnostics": anomalies,
            "record_slots": ["a_first", "b_before_evaluate", "b_first", "a_after_invalid",
                             "b_after_a_invalid", "a_repeated"], "records": encoded_records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend", type=int, choices=(0, 1), required=True)
    parser.add_argument("--threads", type=int, choices=(1, 4, 8, 16), required=True)
    parser.add_argument("--n", type=int, choices=(9, 384), default=9)
    args = parser.parse_args()
    if os.name != "posix" or not args.library.is_absolute() or not args.library.is_file():
        parser.error("qualification requires the frozen Linux bridge absolute path")
    if args.output.exists() or not args.output.is_absolute():
        parser.error("output must be a new absolute directory")
    if (args.backend == 1 and args.threads != 1) or (args.n == 384 and args.backend != 1):
        parser.error("GPU host team is one; the largest-plane probe is GPU-only")
    args.output.mkdir(mode=0o700)
    native = ctypes.CDLL(str(args.library))
    probe = native.nci_test_timing_probe_v1
    probe.argtypes = [ctypes.c_int32, ctypes.c_int32, ctypes.c_int32,
                      ctypes.POINTER(ctypes.c_int32), ctypes.POINTER(Record)]
    probe.restype = None
    results, records = (ctypes.c_int32 * 10)(), (Record * 6)()
    started = time.monotonic_ns()
    probe(args.backend, args.threads, args.n, results, records)
    elapsed = (time.monotonic_ns() - started) * 1e-9
    receipt = probe_receipt(args.n, args.backend, args.threads, results, records, elapsed)
    with (args.output / "probe.json").open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, allow_nan=False)
        stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
    for directory in (args.output, args.output.parent):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    return 0 if receipt["state"] == "QUALIFICATION_PROBE_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
