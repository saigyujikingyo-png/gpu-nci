"""Tiny synthetic native-worker protocol tests; no electronic-structure solver."""
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest


DRIVER = os.environ.get("NCI_DRIVER")


@unittest.skipUnless(DRIVER, "NCI_DRIVER must name the actual built native executable")
class DriverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nci-native-driver-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.output = self.base / "output"
        self.output.mkdir()
        self.cube = self.base / "input.cube"
        self.settings = self.base / "settings.nml"
        self.shape = [5, 5, 5]
        self.origin = [0., 0., 0.]
        self.vectors = [[.25, 0., 0.], [0., .25, 0.], [0., 0., .25]]
        self.values = [.5] * 125
        self.overrides = {}

    def write_inputs(self):
        lines = ["synthetic development fixture", "constant density, not a scientific case",
                 "0 " + " ".join(format(x, ".17g") for x in self.origin)]
        lines.extend(str(n) + " " + " ".join(format(x, ".17g") for x in vector)
                     for n, vector in zip(self.shape, self.vectors))
        lines.extend(" ".join(format(x, ".17g") for x in self.values[i:i+6])
                     for i in range(0, len(self.values), 6))
        self.cube.write_text("\n".join(lines) + "\n")
        fields = dict(protocol_version="1", shape="5,5,5", origin=",".join(map(str, self.origin)),
                      step_vectors=",".join(str(x) for v in self.vectors for x in v), periodic="0,0,0",
                      endpoint_convention="'finite_nodes','finite_nodes','finite_nodes'",
                      quantity="'electron_density'", spin_convention="'spin_summed'",
                      density_representation="'all_electron'", length_unit="'bohr'",
                      density_unit="'electron/bohr^3'", output_mode="0", rho_min="1e-12",
                      negative_tolerance="0", omp_threads="1", memory_budget_bytes="16777216", max_points="125")
        fields.update(self.overrides)
        self.settings.write_text("&nci_run\n" + "\n".join(f" {k}={v}," for k, v in fields.items()) + "\n/\n")

    def execute(self, env=None):
        self.write_inputs()
        original = self.cube.read_bytes()
        result = subprocess.run([DRIVER, str(self.cube), str(self.settings), str(self.output)],
                                capture_output=True, timeout=10, cwd=self.base, env=env)
        self.assertEqual(self.cube.read_bytes(), original)
        receipt = json.loads((self.output / "native.json").read_text())
        self.assertFalse((self.output / "SUCCESS").exists())  # Only Python publishes it.
        return result, receipt

    def test_build_info_one_json_object(self):
        result = subprocess.run([DRIVER, "--build-info"], capture_output=True, timeout=10, cwd=self.base)
        self.assertEqual(result.returncode, 0, result.stderr)
        info = json.loads(result.stdout)
        self.assertEqual(info["protocol_version"], 1)
        for key in ("source_revision", "compiler_id", "compiler_version", "build_type", "fp_policy", "backend_library"):
            self.assertIsInstance(info[key], str)
        self.assertTrue(Path(info["backend_library"]).is_absolute())
        self.assertTrue(Path(info["backend_library"]).is_file())

    def test_full_raw_layout_and_stats(self):
        result, receipt = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(receipt["state"], "completed")
        self.assertEqual(receipt["abi_status"], 0)
        self.assertEqual(receipt["stats"], dict(total=125, valid=1, invalid=124, numeric_failures=0,
                                               bit_counts=[124, 0, 0, 0, 0, 1, 1]))
        flags = (self.output / "flags.u8").read_bytes()
        self.assertEqual(len(flags), 125)
        self.assertEqual(flags[62], 96)
        for filename in ("rdg.f64", "signedrho.f64", "lambda2.f64"):
            values = struct.unpack("<125d", (self.output / filename).read_bytes())
            self.assertEqual(values[62], 0.)
            self.assertTrue(math.isnan(values[0]))
        self.assertFalse((self.output / "grad.f64").exists())

    def test_diagnostic_point_major_lengths(self):
        self.overrides["output_mode"] = "1"
        result, receipt = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        for filename, components in (("grad.f64", 3), ("hess.f64", 6)):
            values = struct.unpack(f"<{125 * components}d", (self.output / filename).read_bytes())
            self.assertEqual(values[62*components:63*components], (0.,) * components)
            self.assertTrue(all(math.isnan(x) for x in values[:components]))

    def test_runtime_byte_order_override_cannot_swap_fields(self):
        self.overrides['output_mode'] = '1'
        env = os.environ.copy()
        env['GFORTRAN_CONVERT_UNIT'] = 'big_endian'
        env['F_UFMTENDIAN'] = 'big'
        result, receipt = self.execute(env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        for filename in ('rdg.f64', 'lambda2.f64', 'signedrho.f64', 'grad.f64', 'hess.f64'):
            self.assertTrue(math.isnan(struct.unpack('<d', (self.output / filename).read_bytes()[:8])[0]))

    def test_geometry_exact_for_tiny_steps(self):
        self.vectors = [[1e-16, 0., 0.], [0., 1e-16, 0.], [0., 0., 1e-16]]
        self.overrides["step_vectors"] = "2e-16,0,0,0,1e-16,0,0,0,1e-16"
        result, receipt = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt["stage"], "geometry")
        self.assertIsNone(receipt["abi_status"])

    def test_metadata_rejection(self):
        self.overrides["length_unit"] = "'angstrom'"
        result, receipt = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt["stage"], "metadata")
        self.assertIsNone(receipt["stats"])

    def test_memory_reservation_before_density(self):
        self.overrides["memory_budget_bytes"] = "9000"
        result, receipt = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt["stage"], "memory")
        self.assertEqual(receipt["npoints"], 0)
        self.assertFalse((self.output / "rdg.f64").exists())

    def test_zero_valid_preserves_abi_three(self):
        self.values = [0.] * 125
        result, receipt = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt["abi_status"], 3)
        self.assertEqual(receipt["stats"]["valid"], 0)
        self.assertEqual(receipt["state"], "failed")

    def test_numerical_failure_preserves_raw_diagnostics(self):
        self.values = [1e308 if i % 2 else 0. for i in range(125)]
        self.values[62] = 1e308
        self.overrides["output_mode"] = "1"
        result, receipt = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt["abi_status"], 4)
        self.assertEqual(receipt["stats"]["numeric_failures"], 1)
        grad = struct.unpack("<375d", (self.output / "grad.f64").read_bytes())
        self.assertTrue(all(math.isnan(x) for x in grad[186:189]))

    def test_exclusive_field_creation(self):
        (self.output / "rdg.f64").write_bytes(b"preserve original")
        result, receipt = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt["stage"], "io")
        self.assertEqual((self.output / "rdg.f64").read_bytes(), b"preserve original")

    def test_unknown_namelist_variable(self):
        self.overrides["unknown"] = "1"
        result, receipt = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt["stage"], "settings")

    def test_undeclared_required_value(self):
        self.write_inputs()
        self.settings.write_text(self.settings.read_text().replace(" rho_min=1e-12,\n", ""))
        result = subprocess.run([DRIVER, str(self.cube), str(self.settings), str(self.output)],
                                capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads((self.output / "native.json").read_text())["stage"], "settings")


if __name__ == "__main__":
    unittest.main()
