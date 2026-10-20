"""Protocol tests with a synthetic stub executable, not native numerical evidence."""

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CLI = Path(os.environ.get("NCI_CLI", Path(__file__).resolve().parents[2] / "cli" / "nci_cli.py")).resolve()
SPEC = importlib.util.spec_from_file_location("offline_cli", CLI)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

STUB = r'''import json, os, pathlib, re, struct, sys, time
mode = MODE
backend = pathlib.Path(BACKEND)
if len(sys.argv) == 2 and sys.argv[1] == '--build-info':
    if mode == 'probe_timeout': time.sleep(30)
    if mode == 'probe_fail': sys.exit(3)
    if mode == 'probe_bad': print('{}'); sys.exit(0)
    if mode == 'probe_duplicate': print('{"protocol_version":1,"protocol_version":1}'); sys.exit(0)
    print(json.dumps(dict(protocol_version=1,source_revision='UNKNOWN',compiler_id='stub',
        compiler_version='0',build_type='',fp_policy='synthetic protocol only',backend_library=str(backend))))
    sys.exit(0)
snapshot, settings, directory = map(pathlib.Path, sys.argv[1:])
assert snapshot.is_absolute() and settings.is_absolute() and directory.is_absolute()
assert 'LD_PRELOAD' not in os.environ and 'LD_LIBRARY_PATH' not in os.environ
text = settings.read_text()
shape = list(map(int,re.search(r' shape = ([^\n]+)',text).group(1).rstrip(',').split(',')))
n = shape[0]*shape[1]*shape[2]
diagnostic = bool(int(re.search(r' output_mode = (\d+)',text).group(1)))
if mode == 'timeout': print('launched',flush=True); time.sleep(30)
if mode == 'snapshot_change': snapshot.write_bytes(b'altered snapshot')
if mode == 'settings_change': settings.write_text('altered settings')
if mode == 'backend_change': backend.write_bytes(b'altered backend')
if mode == 'driver_change': pathlib.Path(__file__).write_text('# changed\n')
for name,width in [('rdg.f64',8),('lambda2.f64',8),('signedrho.f64',8),('flags.u8',1)]+([('grad.f64',24),('hess.f64',48)] if diagnostic else []):
    size = n*width + (1 if mode == 'bad_size' and name == 'rdg.f64' else 0)
    with (directory/name).open('xb') as f: f.write((b'\x40' if width == 1 else b'\x00')*size)
stats = dict(total=n,valid=n,invalid=0,numeric_failures=0,bit_counts=[0,0,0,0,0,0,n])
receipt = dict(protocol_version=1,state='completed',stage='evaluate',message='stub only',abi_status=0,npoints=n,stats=stats)
if mode == 'bad_valid': stats['valid'] = True
if mode == 'bad_union': stats['invalid'] = 1
if mode == 'bad_bit4': stats['bit_counts'][4] = 1
if mode == 'bad_bit5': stats['bit_counts'][5] = n+1
if mode == 'bad_bit6': stats['bit_counts'][6] = 0
if mode == 'bad_boolean_bit': stats['bit_counts'][6] = True
if mode == 'bad_invalid_bits': stats['bit_counts'][0] = 1
if mode == 'zero_valid': stats.update(valid=0,invalid=n,bit_counts=[n,0,0,0,0,0,0])
if mode == 'bad_npoints': receipt['npoints'] = n-1
if mode == 'bad_total': stats['total'] = n-1
if mode == 'failed_receipt': receipt.update(state='failed',abi_status=4)
if mode == 'null_stats': receipt['stats'] = None
if mode == 'spoof_success': (directory/'SUCCESS').write_text('untrusted worker marker')
if mode != 'missing_native': (directory/'native.json').write_text(json.dumps(receipt))
print('stub stdout')
print('stub stderr',file=sys.stderr)
if mode == 'exit_nonzero': sys.exit(4)
'''


def fixture_card(data):
    return {"schema_version": 1,
            "input": {"path": "input source.cube", "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                      "source": dict(kind="synthetic", reference="protocol fixture", permission="generated",
                                     producer="stub test", producer_version="1", settings="no numerical calculation",
                                     density_precision="unknown")},
            "grid": {"shape": [5, 7, 9], "origin": [0, -0.25, 2],
                     "step_vectors": [[0.25, 0, 0], [0.125, 0.5, 0], [0, 0.125, 0.75]], "axis_order": "z_fastest"},
            "metadata": dict(quantity="electron_density", spin_convention="spin_summed", density_representation="all_electron",
                             length_unit="bohr", density_unit="electron/bohr^3", periodic=[0, 1, 0],
                             endpoint_convention=["finite_nodes", "independent_samples", "finite_nodes"]),
            "compute": dict(backend="cpu", layout="full_grid", output_mode="full", rho_min=1e-12,
                            negative_tolerance=0, omp_threads=1),
            "limits": dict(memory_budget_bytes=16777216, max_points=1000, timeout_seconds=2)}


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.card = fixture_card(b"synthetic bytes\n")

    def rejected(self, card):
        with self.assertRaises(MODULE.CliError):
            MODULE.validate_card(card)

    def test_card_and_all_representation_enums(self):
        for representation in ("all_electron", "valence", "core_augmented", "promolecular"):
            self.card["metadata"]["density_representation"] = representation
            self.assertEqual(MODULE.validate_card(self.card), 315)

    def test_int64_allocation_products(self):
        self.card['grid']['shape'] = [5, 5, MODULE.INT64_MAX // 25]
        self.card['limits']['max_points'] = MODULE.INT64_MAX
        self.rejected(self.card)  # N fits, but tracked bytes do not.

    def test_unknown_and_missing_at_every_object(self):
        paths = [(), ("input",), ("input", "source"), ("grid",), ("metadata",), ("compute",), ("limits",)]
        for path in paths:
            for operation in ("add", "remove"):
                with self.subTest(path=path, operation=operation):
                    card = copy.deepcopy(self.card)
                    target = card
                    for key in path:
                        target = target[key]
                    if operation == "add": target["unknown"] = 1
                    else: target.pop(next(iter(target)))
                    self.rejected(card)

    def test_numeric_types_ranges_and_null(self):
        for parent, key, values in [("compute", "rho_min", [None, True, 0, -1, float("inf"), float("nan"), "1"]),
                                    ("compute", "negative_tolerance", [-1, True, None]),
                                    ("compute", "omp_threads", [0, 17, 1.0, True]),
                                    ("limits", "timeout_seconds", [0, 3601, True, 1.5]),
                                    ("limits", "max_points", [314, 1 << 63, True]),
                                    ("input", "bytes", [0, 1 << 63, True])]:
            for value in values:
                with self.subTest(parent=parent, key=key, value=value):
                    card = copy.deepcopy(self.card)
                    card[parent][key] = value
                    self.rejected(card)

    def test_geometry_and_checked_allocation(self):
        for shape in ([4, 7, 9], [True, 7, 9], [5.0, 7, 9], [1 << 62, 5, 5], [5, 7]):
            card = copy.deepcopy(self.card)
            card["grid"]["shape"] = shape
            self.rejected(card)
        self.card["limits"]["memory_budget_bytes"] = 1
        self.rejected(self.card)

    def test_source_units_metadata_and_hash(self):
        changes = [("input", "sha256", "A" * 64), ("input", "path", ""),
                   ("metadata", "length_unit", "angstrom"), ("metadata", "density_unit", "unknown"),
                   ("metadata", "spin_convention", "spin_difference"),
                   ("metadata", "endpoint_convention", ["finite_nodes"] * 3),
                   ("metadata", "periodic", [0, True, 0])]
        for parent, key, value in changes:
            card = copy.deepcopy(self.card)
            card[parent][key] = value
            self.rejected(card)
        for value in (None, "", "x" * 4097):
            card = copy.deepcopy(self.card)
            card["input"]["source"]["reference"] = value
            self.rejected(card)

    def test_strict_json(self):
        for value in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}', b'{} {}', b'\xff'):
            with self.subTest(value=value), self.assertRaises(MODULE.CliError):
                MODULE.strict_json(value, "test")

    def test_namelist_column_order_and_enums_only(self):
        text = MODULE.namelist(self.card).decode()
        self.assertIn("step_vectors = 0.25, 0, 0, 0.125, 0.5, 0, 0, 0.125, 0.75,", text)
        self.assertIn("endpoint_convention = 'finite_nodes', 'independent_samples', 'finite_nodes'", text)
        self.assertEqual(text.count("&nci_run"), 1)
        self.assertNotIn(self.card["input"]["source"]["settings"], text)


@unittest.skipIf(os.name == "nt", "synthetic executable uses a POSIX shebang; run under WSL")
class ComponentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nci-cli-protocol-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.cards = self.base / "card location"
        self.cards.mkdir()
        self.cwd = self.base / "outside repository"
        self.cwd.mkdir()
        self.data = b"synthetic opaque input; the CLI must not parse CUBE\n"
        self.source = self.cards / "input source.cube"
        self.source.write_bytes(self.data)
        self.card = fixture_card(self.data)
        self.card_path = self.cards / "card.json"
        self.backend = self.base / "backend stub.so"
        self.backend.write_bytes(b"synthetic backend fingerprint only\n")
        self.driver = self.base / "worker stub"
        self.output = self.base / "new output"

    def execute(self, mode="ok", raw_card=None):
        self.card_path.write_bytes(raw_card if raw_card is not None else json.dumps(self.card).encode())
        script = "#!" + sys.executable + "\n" + STUB.replace("mode = MODE", "mode = " + repr(mode)).replace("pathlib.Path(BACKEND)", "pathlib.Path(" + repr(str(self.backend)) + ")")
        self.driver.write_text(script)
        self.driver.chmod(0o700)
        result = subprocess.run([sys.executable, str(CLI), "run", "--card", str(self.card_path),
                                 "--driver", str(self.driver), "--output-dir", str(self.output)],
                                cwd=self.cwd, capture_output=True, timeout=15)
        manifest_path = self.output / "manifest.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
        return result, manifest

    def assert_failed(self, mode, stage=None):
        result, manifest = self.execute(mode)
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertEqual(manifest["state"], "failed")
        if stage: self.assertEqual(manifest["stage"], stage)
        self.assertFalse((self.output / "SUCCESS").exists())
        self.assertEqual(self.source.read_bytes(), self.data)
        return manifest

    def test_full_receipt_and_hashes_outside_cwd(self):
        result, manifest = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(manifest["state"], "completed_numerical")
        self.assertEqual(manifest["scientific"], dict(certified=False, uncertainty="unknown", completion="numerical_only"))
        self.assertEqual(manifest["native"], json.loads((self.output / "native.json").read_text()))
        self.assertEqual(manifest["build"]["source_revision"], "UNKNOWN")
        self.assertEqual(manifest["input"]["path"], str(self.source))
        self.assertEqual(manifest["worker"], dict(returncode=0, timed_out=False, timeout_seconds=2))
        self.assertEqual(set(manifest["outputs"]), {"rdg.f64", "lambda2.f64", "signedrho.f64", "flags.u8"})
        for name, output in manifest["outputs"].items():
            content = (self.output / name).read_bytes()
            self.assertEqual(output["bytes"], len(content))
            self.assertEqual(output["sha256"], hashlib.sha256(content).hexdigest())
            self.assertEqual(output["shape"], [5, 7, 9])
            self.assertEqual(output["point_order"], "z_fastest")
            self.assertEqual(output["byte_order"], "little")
        self.assertEqual((self.output / "SUCCESS").read_text(), hashlib.sha256((self.output / "manifest.json").read_bytes()).hexdigest() + "\n")
        self.assertEqual((self.output / "card.json").read_bytes(), self.card_path.read_bytes())
        self.assertEqual(self.source.read_bytes(), self.data)

    def test_diagnostic_declarations(self):
        self.card["compute"]["output_mode"] = "diagnostic"
        result, manifest = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        grad, hess = (manifest["outputs"][key] for key in ("grad.f64", "hess.f64"))
        self.assertEqual(grad["shape"], [5, 7, 9, 3])
        self.assertEqual(grad["component_order"], ["gx", "gy", "gz"])
        self.assertEqual(grad["unit"], "electron/bohr^4")
        self.assertEqual(hess["component_order"], ["xx", "yy", "zz", "xy", "xz", "yz"])
        self.assertEqual(hess["bytes"], 315 * 48)
        self.assertEqual(hess["unit"], "electron/bohr^5")

    def test_existing_output_untouched(self):
        self.output.mkdir()
        (self.output / "sentinel").write_bytes(b"preserve")
        result, manifest = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(manifest)
        self.assertEqual(list(self.output.iterdir()), [self.output / "sentinel"])

    def test_card_duplicate_and_oversize_preserved_failure(self):
        result, manifest = self.execute(raw_card=b'{"schema_version":1,"schema_version":1}')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(manifest["stage"], "card")
        self.assertFalse((self.output / "SUCCESS").exists())

    def test_oversize_json(self):
        result, manifest = self.execute(raw_card=b" " * (MODULE.MAX_JSON + 1))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(manifest["stage"], "card")

    def test_hash_mismatch(self):
        self.card["input"]["sha256"] = "0" * 64
        self.assert_failed("ok", "snapshot")

    def test_byte_count_mismatch(self):
        self.card["input"]["bytes"] -= 1
        self.assert_failed("ok", "snapshot")

    def test_missing_native(self):
        self.assert_failed("missing_native", "native_receipt")

    def test_nonzero_exit_preserves_native_and_logs(self):
        manifest = self.assert_failed("exit_nonzero", "worker")
        self.assertEqual(manifest["worker"]["returncode"], 4)
        self.assertIsNotNone(manifest["native"])
        self.assertIn("stub stderr", (self.output / "stderr.log").read_text())

    def test_timeout_records_owned_child_exit(self):
        self.card["limits"]["timeout_seconds"] = 1
        manifest = self.assert_failed("timeout", "worker")
        self.assertTrue(manifest["worker"]["timed_out"])
        self.assertNotEqual(manifest["worker"]["returncode"], 0)
        self.assertIn("launched", (self.output / "stdout.log").read_text())

    def test_wrong_raw_file_size(self):
        self.assert_failed("bad_size", "outputs")

    def test_snapshot_modified_by_worker(self):
        self.assert_failed("snapshot_change", "integrity")

    def test_backend_modified_by_worker(self):
        self.assert_failed("backend_change", "integrity")

    def test_driver_modified_by_worker(self):
        self.assert_failed("driver_change", "integrity")

    def test_settings_modified_by_worker(self):
        self.assert_failed("settings_change", "integrity")

    def test_worker_cannot_forge_success_marker(self):
        self.assert_failed("spoof_success", "integrity")
        self.assertEqual((self.output / "SUCCESS.rejected.0").read_text(), "untrusted worker marker")

    def test_probe_timeout(self):
        manifest = self.assert_failed("probe_timeout", "build_info")
        self.assertTrue(manifest['build_probe']['timed_out'])
        self.assertIsNone(manifest['worker'])


def component_case(mode, stage):
    def test(self):
        self.assert_failed(mode, stage)
    return test


for _mode in ("probe_fail", "probe_bad", "probe_duplicate"):
    setattr(ComponentTests, "test_" + _mode, component_case(_mode, "build_info"))
for _mode in ("bad_valid", "bad_union", "bad_bit4", "bad_bit5", "bad_bit6", "bad_boolean_bit", "bad_invalid_bits",
              "zero_valid", "bad_npoints", "bad_total", "failed_receipt", "null_stats"):
    setattr(ComponentTests, "test_receipt_" + _mode, component_case(_mode, "native_receipt"))


if __name__ == "__main__":
    unittest.main()
