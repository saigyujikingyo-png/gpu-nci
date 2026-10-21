"""Pure protocol fixtures. No native process, build, GPU, or scientific imports."""
import importlib.util
import json
from pathlib import Path
import tempfile
import stat
import ctypes
import sys
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / "benchmarks" / "run_config.py"
SPEC = importlib.util.spec_from_file_location("nci_p1_run_config", SOURCE)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
PROBE_SPEC = importlib.util.spec_from_file_location("nci_p1_qualify_probe", Path(__file__).with_name("qualify_probe.py"))
probe = importlib.util.module_from_spec(PROBE_SPEC)
PROBE_SPEC.loader.exec_module(probe)
sys.path.insert(0, str(Path(__file__).parent))
try:
    import qualify_faults as faults
finally:
    sys.path.pop(0)


def timing_fixture(label="formal1", n=128, threads=4, backend="cpu"):
    rows = []
    for index in range(n // 4):
        rows.append(dict(start=4*index, planes=4, abi_status=0, getter_ok=True, sample_eligible=True,
                         eval_start_ns=1000000*index, eval_stop_ns=1000000*index+100000,
                         state=1, timing_error=0, observed_threads=threads if backend == "cpu" else 0,
                         kernel_count=1, events_created=0 if backend == "cpu" else 2,
                         events_destroyed=0 if backend == "cpu" else 2,
                         async_queue=0 if backend == "cpu" else 1,
                         stream_handle=0 if backend == "cpu" else 12345678, reserved=0,
                         kernel_seconds=.00001, device_seconds=.00001 if backend == "cpu" else .00002))
    return dict(protocol_version=1, label=label, complete=True, timing_valid=True,
                cache_state="uncontrolled", timing_report_io="excluded_from_te2e", te2e_seconds=.1,
                teval_seconds=sum((r["eval_stop_ns"]-r["eval_start_ns"])*1e-9 for r in rows),
                kernel_seconds=sum(r["kernel_seconds"] for r in rows),
                device_seconds=sum(r["device_seconds"] for r in rows), slabs=rows)


class AckTests(unittest.TestCase):
    def test_fragmented_ack_timestamp_is_complete_line_arrival(self):
        parser = runner.AckParser()
        parser.feed(runner.ACK[:8], 10)
        self.assertIsNone(parser.ack_ns)
        parser.feed(runner.ACK[8:] + b"\n", 20)
        parser.finish()
        self.assertEqual(parser.ack_ns, 20)

    def test_duplicate_or_trace_line_refused(self):
        for data in (runner.ACK+b"\n"+runner.ACK+b"\n", b"launch CUDA kernel\n"):
            with self.subTest(data=data), self.assertRaises(runner.Refusal):
                runner.AckParser().feed(data, 10)

    def test_truncated_ack_is_not_a_result(self):
        parser = runner.AckParser()
        parser.feed(runner.ACK, 10)
        with self.assertRaises(runner.Refusal):
            parser.finish()

    def test_stdout_bound(self):
        with self.assertRaises(runner.Refusal):
            runner.AckParser().feed(b"x" * (runner.MAX_STDOUT+1), 10)


class RecordTests(unittest.TestCase):
    def validate(self, doc, backend="cpu"):
        return runner.validate_run_document(doc, "formal1", 128, 4 if backend == "cpu" else 1, backend)

    def test_valid_cpu_and_gpu_records(self):
        self.validate(timing_fixture())
        self.validate(timing_fixture(threads=1, backend="openacc"), "openacc")

    def test_all_invalid_boundary_slab_status_three_allowed(self):
        doc = timing_fixture()
        doc["slabs"][0]["abi_status"] = 3
        self.validate(doc)

    def test_wrong_actual_team_refused(self):
        doc = timing_fixture()
        doc["slabs"][0]["observed_threads"] = 1
        with self.assertRaises(runner.Refusal):
            self.validate(doc)

    def test_event_failure_or_missing_stream_refused(self):
        for key, value in (("events_destroyed", 1), ("stream_handle", 0), ("state", -1),
                           ("timing_error", 7), ("kernel_count", 2), ("async_queue", 0), ("async_queue", 17)):
            doc = timing_fixture(threads=1, backend="openacc")
            doc["slabs"][0][key] = value
            with self.subTest(key=key), self.assertRaises(runner.Refusal):
                self.validate(doc, "openacc")

    def test_launch_over_500ms_refused_without_adaptation(self):
        doc = timing_fixture(threads=1, backend="openacc")
        doc["slabs"][0]["kernel_seconds"] = .50001
        with self.assertRaises(runner.Refusal):
            self.validate(doc, "openacc")

    def test_nan_negative_clock_and_noncanonical_sequence_refused(self):
        for key, value in (("kernel_seconds", float("nan")), ("eval_start_ns", -1),
                           ("eval_stop_ns", -1), ("start", 1), ("planes", 3), ("reserved", 1),
                           ("getter_ok", False), ("observed_threads", True), ("sample_eligible", False)):
            doc = timing_fixture()
            doc["slabs"][0][key] = value
            with self.subTest(key=key), self.assertRaises(runner.Refusal):
                self.validate(doc)

    def test_raw_aggregate_and_count_must_agree(self):
        for mutation in (lambda doc: doc["slabs"].pop(), lambda doc: doc.update(kernel_seconds=42),
                         lambda doc: doc.update(te2e_seconds=0), lambda doc: doc.update(complete=False)):
            doc = timing_fixture()
            mutation(doc)
            with self.assertRaises(runner.Refusal):
                self.validate(doc)

    def test_ineligible_or_refused_call_cannot_reuse_stale_valid_record(self):
        for status in (0, 1, 3):
            doc = timing_fixture()
            doc["slabs"][0].update(abi_status=status, sample_eligible=False)
            with self.subTest(status=status), self.assertRaises(runner.Refusal):
                self.validate(doc)


class ProbeDiagnosticTests(unittest.TestCase):
    def test_nonfinite_preserves_native_bits_state_and_errors_and_forces_fail(self):
        cases = ((0x7ff8000000001234, "nan", "quiet"),
                 (0xfff0000000000001, "nan", "signaling"),
                 (0x7ff0000000000000, "positive_infinity", None),
                 (0xfff0000000000000, "negative_infinity", None))
        for bits, classification, nan_kind in cases:
            with self.subTest(bits=f"{bits:016x}"):
                records = (probe.Record * 6)()
                records[0].state = -1
                records[0].timing_error = 73
                offset = probe.Record.kernel_seconds.offset
                ctypes.memmove(ctypes.addressof(records[0]) + offset, bits.to_bytes(8, sys.byteorder), 8)
                receipt = probe.probe_receipt(384, 1, 1, [0] * 10, records, .25)
                saved = json.loads(json.dumps(receipt, allow_nan=False))
                self.assertEqual(saved["state"], "QUALIFICATION_PROBE_FAIL")
                self.assertEqual(saved["results"], [0] * 10)
                self.assertEqual(saved["records"][0]["state"], -1)
                self.assertEqual(saved["records"][0]["timing_error"], 73)
                diagnostic = saved["records"][0]["kernel_seconds"]
                self.assertEqual(diagnostic["classification"], classification)
                self.assertEqual(diagnostic["ieee754_binary64_bits_hex"], f"0x{bits:016x}")
                self.assertEqual(diagnostic.get("nan_kind"), nan_kind)
                self.assertEqual(saved["nonfinite_diagnostics"][0]["record_index"], 0)

    def test_finite_probe_values_stay_numeric_including_negative_zero(self):
        records = (probe.Record * 6)()
        records[0].kernel_seconds = -0.0
        records[0].device_seconds = 1.25
        saved = json.loads(json.dumps(probe.probe_receipt(9, 0, 1, [0] * 10, records, .5), allow_nan=False))
        self.assertEqual(saved["state"], "QUALIFICATION_PROBE_PASS")
        self.assertEqual(saved["records"][0]["device_seconds"], 1.25)
        self.assertEqual(saved["nonfinite_diagnostics"], [])
        self.assertEqual(probe.struct.pack("=d", saved["records"][0]["kernel_seconds"]), probe.struct.pack("=d", -0.0))

    def test_largest_probe_receipt_declares_interior_eight_plane_fixture(self):
        receipt = probe.probe_receipt(384, 1, 1, [0] * 10, (probe.Record * 6)(), .5)
        self.assertEqual(receipt["tile_start"], [4, 0, 0])
        self.assertEqual(receipt["input_origin"], [2, 0, 0])
        self.assertEqual(receipt["input_shape"], [8, 384, 384])
        self.assertEqual(receipt["maximum_evaluations"], 1)
        self.assertIn("pinned mixed quadratic v1", receipt["fixture"])
        self.assertIn("not a stored-water worst-case bound", receipt["scope"])


class FaultControlTests(unittest.TestCase):
    def fixture(self, mode):
        records = (faults.Record * 7)()
        for index in (0, 2, 3, 4, 5):
            record = records[index]
            record.state = 1
            record.kernel_count = 1
            record.events_created = record.events_destroyed = 2
            record.async_queue = 1
            record.stream_handle = 1234
            record.kernel_seconds = .0001
            record.device_seconds = .0002
        if mode:
            record = records[3]
            record.state, record.timing_error, created = faults.EXPECTED[mode]
            record.events_created = record.events_destroyed = created
            record.kernel_seconds = 0
            if mode == 5:
                record.stream_handle = 0
        if mode == 0:
            ctypes.memmove(ctypes.addressof(records[6]), ctypes.addressof(records[0]), ctypes.sizeof(faults.Record))
        return records

    def receipt(self, mode, records=None):
        return faults.fault_receipt(mode, faults.expected_results(mode), self.fixture(mode) if records is None else records,
                                    [0] * 5832, [0] * 1944, [0] * 66)

    def test_fixed_modes_accept_only_expected_failure_records(self):
        self.assertEqual(list(faults.EXPECTED), list(range(6)))
        for mode in faults.EXPECTED:
            with self.subTest(mode=mode):
                receipt = self.receipt(mode)
                self.assertEqual(receipt["state"], "FAULT_QUALIFICATION_PASS")
                self.assertEqual(receipt["results"][19], 6 if mode == 0 else 5)
                self.assertEqual(receipt["maximum_field_launches"], 4)
                self.assertEqual(len(receipt["output_snapshots"]), 6)
                self.assertEqual(receipt["output_snapshots"][5]["executed"], mode == 0)
                if mode == 0:
                    self.assertEqual(receipt["results"][20:25], [1, 0, 0, 0, 0])
                self.assertEqual(len(receipt["records"][3]["timing_ieee754_binary64_bits_hex"]["kernel_seconds"]), 18)
                json.dumps(receipt, allow_nan=False)

    def test_fault_cleanup_output_or_one_shot_mismatch_is_failure(self):
        for change in (lambda receipt: receipt["records"][3].update(events_destroyed=0),
                       lambda receipt: receipt["records"][4].update(state=-1, timing_error=7),
                       lambda receipt: receipt["records"][1].update(events_created=1),
                       lambda receipt: receipt["output_snapshots"][3]["flags_u8"].__setitem__(1, 127),
                       lambda receipt: receipt["records"][5].update(raw_record_bytes_hex="changed"),
                       lambda receipt: receipt["results"].__setitem__(8, 4)):
            receipt = self.receipt(4)
            change(receipt)
            self.assertTrue(faults.validate_fault_receipt(receipt))

    def test_fault_report_nonfinite_is_serializable_fail_with_raw_bits(self):
        records = self.fixture(3)
        payload = 0x7ff8000000004321
        ctypes.memmove(ctypes.addressof(records[3]) + faults.Record.device_seconds.offset,
                       payload.to_bytes(8, sys.byteorder), 8)
        receipt = self.receipt(3, records)
        saved = json.loads(json.dumps(receipt, allow_nan=False))
        self.assertEqual(saved["state"], "FAULT_QUALIFICATION_FAIL")
        self.assertEqual(saved["records"][3]["timing_error"], 6)
        self.assertEqual(saved["records"][3]["device_seconds"]["ieee754_binary64_bits_hex"], f"0x{payload:016x}")
        self.assertEqual(saved["records"][3]["timing_ieee754_binary64_bits_hex"]["device_seconds"], f"0x{payload:016x}")

class ControlTests(unittest.TestCase):
    def test_fixed_matrix_and_no_added_small_formal_case(self):
        for n in (128, 256, 384):
            for threads in (1, 4, 8, 16):
                runner.config_identity(n, threads, "cpu")
            runner.config_identity(n, 1, "openacc")
        for case in ((17, 1, "cpu"), (128, 2, "cpu"), (384, 4, "openacc")):
            with self.assertRaises(runner.Refusal):
                runner.config_identity(*case)

    def test_duplicate_json_key_and_nonfinite_refused(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            path = Path(tmp) / "receipt.json"
            for text in ('{"x":1,"x":2}', '{"x":NaN}'):
                path.write_text(text)
                with self.assertRaises(runner.Refusal):
                    runner.read_json(path)

    def test_no_partial_median_is_called_complete(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            base = Path(tmp)
            for label in runner.LABELS[:5]:
                directory = base / label
                directory.mkdir()
                (directory / "timing.json").write_text(json.dumps(timing_fixture(label)))
                (directory / "native.json").write_text(json.dumps(dict(state="completed", abi_status=0, npoints=128**3)))
                # Pure source fixture: fake only field file stat, never create
                # large numerical output or execute the benchmark.
            original_is_file = Path.is_file
            original_stat = Path.stat
            def fixture_is_file(path):
                return path.name in runner.FIELDS or original_is_file(path)
            def fixture_stat(path, **kwargs):
                if path.name in runner.FIELDS:
                    return type("Stat", (), {"st_size": runner.FIELDS[path.name]*128**3, "st_mode": stat.S_IFREG})()
                return original_stat(path, **kwargs)
            # Symlink checks use lstat, so leave them real for absent fixture fields.
            with patch.object(Path, "is_file", fixture_is_file), patch.object(Path, "stat", fixture_stat):
                summary = runner.summarize_config(base, 128, 4, "cpu")
            self.assertEqual(summary["state"], "PARTIAL_BENCHMARK")
            self.assertEqual(summary["formal_count"], 2)
            self.assertEqual(summary["completed_repetitions"], 5)
            self.assertIn("te2e_seconds", summary["formal_summary"])

    def test_formal_profiler_refusal_and_thread_environment(self):
        with self.assertRaises(runner.Refusal):
            runner.formal_environment(4, {"NVCOMPILER_ACC_TIME": "1"})
        env = runner.formal_environment(8, {})
        self.assertEqual(env["OMP_NUM_THREADS"], "8")
        self.assertEqual(env["OMP_DYNAMIC"], "FALSE")
        self.assertEqual(env["MKL_NUM_THREADS"], "1")

    def test_exclusive_receipt_preserves_first_attempt(self):
        # Portable pure no-overwrite check; native fsync qualification is Linux.
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            path = Path(tmp) / "configuration.json"
            path.write_text("retained failure")
            with self.assertRaises(FileExistsError):
                runner.write_json_new(path, {"state": "replacement"})
            self.assertEqual(path.read_text(), "retained failure")

    def test_complete_requires_ten_runs_and_all_four_full_fields(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            base = Path(tmp)
            for label in runner.LABELS:
                directory = base / label
                directory.mkdir()
                (directory / "timing.json").write_text(json.dumps(timing_fixture(label)))
                (directory / "native.json").write_text(json.dumps(dict(state="completed", abi_status=0, npoints=128**3)))
            original_stat = Path.stat
            original_is_file = Path.is_file
            damaged = set()
            def fixture_stat(path, **kwargs):
                if path.name in runner.FIELDS:
                    size = runner.FIELDS[path.name]*128**3
                    if path.parent.name == "formal7" and path.name in damaged:
                        size -= 1
                    return type("Stat", (), {"st_size": size, "st_mode": stat.S_IFREG})()
                return original_stat(path, **kwargs)
            def fixture_is_file(path):
                return path.name in runner.FIELDS or original_is_file(path)
            with patch.object(Path, "stat", fixture_stat), patch.object(Path, "is_file", fixture_is_file):
                summary = runner.summarize_config(base, 128, 4, "cpu")
                self.assertEqual(summary["state"], "COMPLETE_BENCHMARK")
                self.assertEqual(summary["formal_count"], 7)
                damaged.add("flags.u8")
                summary = runner.summarize_config(base, 128, 4, "cpu")
                self.assertEqual(summary["state"], "PARTIAL_BENCHMARK")
                self.assertEqual(summary["formal_count"], 6)
                self.assertIn("flags.u8", summary["errors"][0]["error"])


if __name__ == "__main__":
    unittest.main()
