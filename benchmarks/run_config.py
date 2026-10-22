#!/usr/bin/env python3
"""One finite P1 configuration; the frozen outer controller owns the package.

Standard library only. This module never generates density or imports scientific
libraries. Importing it has no launch side effects. All outputs are retained.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import selectors
import signal
import statistics
import subprocess
import time

LABELS = ("fresh_process_first_run", "warmup1", "warmup2") + tuple(f"formal{i}" for i in range(1, 8))
ACK = b"NCI_BENCHMARK_FIRST_RESULT_ACK_V1"
METRICS = ("kernel_seconds", "device_seconds", "teval_seconds", "te2e_seconds")
CONFIG_SECONDS = 120
CLEANUP_SECONDS = 10  # Maximum grace; outer controller still owns its package grace.
MAX_STDOUT = 4096
FIELDS = {"rdg.f64": 8, "lambda2.f64": 8, "signedrho.f64": 8, "flags.u8": 1}


class Refusal(ValueError):
    pass


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise Refusal(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def read_json(path):
    if path.is_symlink() or path.stat().st_size > 262144:
        raise Refusal(f"unsafe or oversized metadata: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(Refusal(f"nonfinite JSON: {value}")))


def finite(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise Refusal(f"invalid nonnegative finite {name}")
    return float(value)


def config_identity(n, threads, backend):
    if type(n) is not int or n not in (128, 256, 384):
        raise Refusal("grid is outside the fixed matrix")
    if type(threads) is not int or backend not in ("cpu", "openacc"):
        raise Refusal("invalid configuration")
    if threads not in ((1, 4, 8, 16) if backend == "cpu" else (1,)):
        raise Refusal("team is outside the fixed matrix")
    return f"{n}-{backend}-{threads}"


class AckParser:
    """Accept exactly one complete ACK line; never infer ACK from process exit."""
    def __init__(self):
        self.pending = b""
        self.total = 0
        self.ack_ns = None

    def feed(self, data, received_ns):
        self.total += len(data)
        if self.total > MAX_STDOUT:
            raise Refusal("benchmark stdout exceeded its protocol bound")
        self.pending += data
        while b"\n" in self.pending:
            line, self.pending = self.pending.split(b"\n", 1)
            if line != ACK or self.ack_ns is not None:
                raise Refusal("unexpected or duplicate benchmark ACK")
            self.ack_ns = received_ns

    def finish(self):
        if self.pending:
            raise Refusal("truncated ACK line")


def validate_run_document(doc, label, n, threads, backend):
    if doc.get("protocol_version") != 1 or doc.get("label") != label:
        raise Refusal("timing report identity mismatch")
    if doc.get("complete") is not True or doc.get("timing_valid") is not True:
        raise Refusal("incomplete or invalid timing report")
    if doc.get("cache_state") != "uncontrolled" or doc.get("timing_report_io") != "excluded_from_te2e":
        raise Refusal("timing/cache boundary label mismatch")
    metrics = {key: finite(doc.get(key), key) for key in METRICS}
    records = doc.get("slabs")
    if not isinstance(records, list) or len(records) != n // 4:
        raise Refusal("incomplete slab record count")
    sums = {"kernel_seconds": 0., "device_seconds": 0., "teval_seconds": 0.}
    for index, row in enumerate(records):
        if type(row) is not dict:
            raise Refusal("invalid slab record")
        integer_keys = ("start", "planes", "abi_status", "eval_start_ns", "eval_stop_ns", "state", "timing_error",
                        "observed_threads", "kernel_count", "events_created", "events_destroyed", "async_queue",
                        "reserved", "stream_handle")
        if any(type(row.get(key)) is not int for key in integer_keys):
            raise Refusal("noninteger slab observation")
        if (row["start"], row["planes"]) != (4 * index, 4):
            raise Refusal("noncanonical slab record sequence")
        # A whole invalid finite boundary slab may legitimately return status 3
        # while the shared driver verifies its flags and continues globally.
        if row.get("getter_ok") is not True or row["abi_status"] not in (0, 3):
            raise Refusal("failed ABI evaluation/getter")
        if row.get("sample_eligible") is not True:
            raise Refusal("ineligible ABI sample or stale private timing")
        if row["state"] != 1 or row["timing_error"] != 0 or row["reserved"] != 0:
            raise Refusal("invalid private timing state")
        if row["eval_start_ns"] < 0 or row["eval_stop_ns"] < row["eval_start_ns"]:
            raise Refusal("invalid evaluate clock")
        kernel = finite(row.get("kernel_seconds"), "slab kernel")
        device = finite(row.get("device_seconds"), "slab device")
        if row["kernel_count"] != 1:
            raise Refusal("unexpected field launch count")
        if backend == "cpu":
            if row["observed_threads"] != threads or any(row[key] != 0 for key in
                    ("events_created", "events_destroyed", "async_queue", "stream_handle")) or device != kernel:
                raise Refusal("CPU actual team or host field-region observation mismatch")
        elif (row["observed_threads"] != 0 or row["events_created"] != 2 or row["events_destroyed"] != 2
              or row["async_queue"] != 1 or row["stream_handle"] == 0 or kernel > .5):
            raise Refusal("GPU event, stream or launch bound failed")
        sums["kernel_seconds"] += kernel
        sums["device_seconds"] += device
        sums["teval_seconds"] += (row["eval_stop_ns"] - row["eval_start_ns"]) * 1e-9
    for key, total in sums.items():
        if not math.isclose(total, metrics[key], rel_tol=1e-12, abs_tol=1e-12):
            raise Refusal(f"aggregate does not match all raw records: {key}")
    if metrics["teval_seconds"] > metrics["te2e_seconds"] + 1e-9:
        raise Refusal("Teval exceeds enclosing Te2e")
    return metrics


def summarize_config(directory, n, threads, backend):
    """Retain summaries of the complete prefix; never label <7 formal complete."""
    config_identity(n, threads, backend)
    runs = []
    errors = []
    gap = False
    for label in LABELS:
        path = directory / label
        if not path.exists():
            gap = True
            continue
        try:
            if gap or path.is_symlink() or not path.is_dir():
                raise Refusal("non-prefix or unsafe repetition directory")
            doc = read_json(path / "timing.json")
            metrics = validate_run_document(doc, label, n, threads, backend)
            native = read_json(path / "native.json")
            if native.get("state") != "completed" or native.get("abi_status") != 0 or native.get("npoints") != n**3:
                raise Refusal("native result is incomplete")
            for name, width in FIELDS.items():
                field = path / name
                if field.is_symlink() or not field.is_file() or field.stat().st_size != width * n**3:
                    raise Refusal(f"missing or incomplete FULL field: {name}")
            if (path / "grad.f64").exists() or (path / "hess.f64").exists():
                raise Refusal("unexpected diagnostic field in FULL timing workflow")
            runs.append({"label": label, **metrics, "timing_report": f"{label}/timing.json"})
        except (OSError, ValueError, TypeError, KeyError) as exc:
            errors.append({"label": label, "error": str(exc)})
            gap = True
    formal = [row for row in runs if row["label"].startswith("formal")]
    complete = len(runs) == 10 and len(formal) == 7 and not errors
    stats = {}
    for metric in METRICS:
        values = [row[metric] for row in formal]
        if values:
            # Declare the convention; with <2 points an IQR is undefined.
            quartiles = statistics.quantiles(values, n=4, method="inclusive") if len(values) > 1 else None
            stats[metric] = {"median": statistics.median(values),
                             "iqr": quartiles[2] - quartiles[0] if quartiles else None}
    return {"state": "COMPLETE_BENCHMARK" if complete else "PARTIAL_BENCHMARK",
            "formal_count": len(formal), "completed_repetitions": len(runs), "runs": runs,
            "formal_summary": stats, "iqr_method": "inclusive", "errors": errors}


def write_json_new(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def formal_environment(threads, inherited=None):
    env = dict(os.environ if inherited is None else inherited)
    for key in ("NVCOMPILER_ACC_NOTIFY", "NVCOMPILER_ACC_TIME", "NV_ACC_TIME", "PGI_ACC_TIME", "PGI_ACC_NOTIFY",
                "ACC_NOTIFY", "CUDA_PROFILE", "CUDA_INJECTION64_PATH", "NVTX_INJECTION64_PATH"):
        if env.get(key, "") not in ("", "0"):
            raise Refusal(f"formal profiling must be off: {key}")
    env.update(OMP_NUM_THREADS=str(threads), OMP_DYNAMIC="FALSE", OMP_THREAD_LIMIT=str(threads),
               OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", BLIS_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1")
    return env


def run_config(executable, input_path, settings, output, n, threads, backend):
    identity = config_identity(n, threads, backend)
    if os.name != "posix":
        raise Refusal("the frozen native timing workflow requires POSIX/Linux")
    for path in (executable, input_path, settings):
        if path.is_symlink() or not path.is_absolute() or not path.is_file():
            raise Refusal("executable, input and settings must be absolute regular immutable paths")
    if not output.is_absolute():
        raise Refusal("output must be a new absolute directory")
    env = formal_environment(threads)
    # An existing output, including a partial prior attempt, is never reused.
    output.mkdir(mode=0o700)
    parent_fd = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    command = [str(executable), str(input_path), str(settings), str(output), str(n), str(threads),
               "0" if backend == "cpu" else "1"]
    receipt = {"protocol_version": 1, "configuration": identity, "n": n, "threads": threads,
               "backend": backend, "slab_planes": 4, "repetitions": list(LABELS),
               "cache_state": "uncontrolled", "configuration_limit_seconds": CONFIG_SECONDS,
               "package_control": "external frozen controller: serial 15 configs, 2100 seconds plus 10 cleanup",
               "field_region": "OpenMP field loop including fork/join, barrier, count reduction" if backend == "cpu"
               else "CUDA same-stream event field interval including possible host enqueue gaps",
               "device_region": "same host field region as CPU kernel_seconds; no transfers" if backend == "cpu"
               else "first upload through last completed download including intervening host work",
               "outer_comparison_metrics": ["teval_seconds", "te2e_seconds"],
               "first_result_seconds": None, "first_result_boundary": "parent Popen launch to complete durable result ACK",
               "command": command, "exit_code": None, "failure": None}
    write_json_new(output / "invocation.json", receipt)
    process = None
    parser = AckParser()
    started = time.monotonic_ns()
    previous_term = signal.getsignal(signal.SIGTERM)
    def on_termination(signum, frame):
        raise InterruptedError("outer controller requested stop")
    signal.signal(signal.SIGTERM, on_termination)
    try:
        with (output / "stderr.log").open("xb") as stderr, (output / "stdout.log").open("xb") as stdout:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=stderr,
                                       env=env, cwd=output, start_new_session=True)
            selector = selectors.DefaultSelector()
            try:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = CONFIG_SECONDS - (time.monotonic_ns() - started) * 1e-9
                    if remaining <= 0:
                        raise Refusal("whole configuration exceeded 120 seconds")
                    for key, _ in selector.select(min(remaining, .1)):
                        data = os.read(key.fd, MAX_STDOUT + 1)
                        received = time.monotonic_ns()
                        if not data:
                            selector.unregister(key.fileobj)
                            continue
                        stdout.write(data)
                        stdout.flush()
                        parser.feed(data, received)
                parser.finish()
                remaining = CONFIG_SECONDS - (time.monotonic_ns() - started) * 1e-9
                if remaining <= 0:
                    raise Refusal("whole configuration exceeded 120 seconds")
                receipt["exit_code"] = process.wait(timeout=remaining)
                if receipt["exit_code"] != 0:
                    raise Refusal("native benchmark failed; later calls/configurations must stop")
                if parser.ack_ns is None:
                    raise Refusal("no first-complete-result ACK")
            finally:
                selector.close()
                process.stdout.close()
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        receipt["failure"] = str(exc)
    except BaseException:
        receipt["failure"] = "interrupted; retain partial outputs"
        raise
    finally:
        if process is not None and process.poll() is None:
            # Only this runner's owned child process group is signalled.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=CLEANUP_SECONDS)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        if process is not None:
            receipt["exit_code"] = process.returncode
        receipt["configuration_wall_seconds"] = (time.monotonic_ns() - started) * 1e-9
        if parser.ack_ns is not None:
            receipt["first_result_seconds"] = (parser.ack_ns - started) * 1e-9
        try:
            summary = summarize_config(output, n, threads, backend)
        except (OSError, ValueError, TypeError) as exc:
            summary = {"state": "PARTIAL_BENCHMARK", "errors": [{"error": str(exc)}]}
        receipt.update(summary)
        if receipt["failure"] or receipt["exit_code"] != 0 or parser.ack_ns is None:
            receipt["state"] = "PARTIAL_BENCHMARK"
        write_json_new(output / "configuration.json", receipt)
        signal.signal(signal.SIGTERM, previous_term)
    return 0 if receipt["state"] == "COMPLETE_BENCHMARK" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("executable", "input", "settings", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--n", type=int, required=True)
    parser.add_argument("--threads", type=int, required=True)
    parser.add_argument("--backend", choices=("cpu", "openacc"), required=True)
    args = parser.parse_args()
    try:
        return run_config(args.executable, args.input, args.settings, args.output, args.n, args.threads, args.backend)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"REFUSED_NOT_STARTED: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
