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
        fields = dict(protocol_version="1", shape=','.join(map(str, self.shape)), origin=",".join(map(str, self.origin)),
                      step_vectors=",".join(str(x) for v in self.vectors for x in v), periodic="0,0,0",
                      endpoint_convention="'finite_nodes','finite_nodes','finite_nodes'",
                      quantity="'electron_density'", spin_convention="'spin_summed'",
                      density_representation="'all_electron'", length_unit="'bohr'",
                      density_unit="'electron/bohr^3'", output_mode="0", rho_min="1e-12",
                      negative_tolerance="0", omp_threads="1", memory_budget_bytes="16777216",
                      max_points=str(math.prod(self.shape)))
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


@unittest.skipUnless(DRIVER, 'NCI_DRIVER must name the actual built native executable')
class SlabDriverTests(unittest.TestCase):
    setUp = DriverTests.setUp
    write_inputs = DriverTests.write_inputs
    execute = DriverTests.execute

    def new_output(self, label):
        self.output = self.base / label
        self.output.mkdir()

    def sample(self, periodic):
        nx, ny, nz = self.shape
        self.vectors = [[.25, 0., 0.], [.125, .5, 0.], [0., .125, .25]]
        self.origin = [.5, -.25, .125]
        self.values = []
        for i in range(nx):
            for j in range(ny):
                for k in range(nz):
                    if any(periodic):
                        value = 2 + .05*math.sin(2*math.pi*i/nx) + .03*math.cos(2*math.pi*j/ny)
                        value += .02*math.sin(2*math.pi*k/nz)
                    else:
                        x, y, z = .5 + .25*i + .125*j, -.25 + .5*j + .125*k, .125 + .25*k
                        value = 20 + .1*x + .2*y + .3*z + .01*x*x + .02*x*y
                    self.values.append(value)
        self.overrides['periodic'] = ','.join(map(str, periodic))
        self.overrides['endpoint_convention'] = ','.join(repr('independent_samples' if x else 'finite_nodes')
                                                        for x in periodic)

    def compare(self, label, block, diagnostic):
        self.overrides.update(layout_mode='0', slab_planes='0', output_mode=str(int(diagnostic)))
        self.new_output(label + '-full')
        full_result, full = self.execute()
        self.assertEqual(full_result.returncode, 0, full_result.stderr)
        expected = {p.name: p.read_bytes() for p in self.output.iterdir() if p.suffix in ('.f64', '.u8')}
        self.overrides.update(layout_mode='1', slab_planes=str(block))
        self.new_output(label + '-slab')
        slab_result, slab = self.execute()
        self.assertEqual(slab_result.returncode, 0, slab_result.stderr)
        self.assertEqual(slab['stats'], full['stats'])
        self.assertEqual(slab['npoints'], math.prod(self.shape))
        self.assertEqual(slab['abi_status'], 0)
        for name, content in expected.items():
            self.assertEqual((self.output / name).read_bytes(), content, (label, name))

    def test_finite_skew_odd_blocks_tails_and_full_width(self):
        self.shape = [7, 5, 6]
        self.sample([0, 0, 0])
        for block in (1, 3, 4, 7):
            for diagnostic in (False, True):
                with self.subTest(block=block, diagnostic=diagnostic):
                    self.compare(f'b{block}-d{int(diagnostic)}', block, diagnostic)

    def test_periodic_and_mixed_axes_minimum_x(self):
        self.shape = [5, 6, 7]
        for axes in ([1, 1, 1], [1, 0, 1], [0, 1, 0]):
            self.sample(axes)
            for block in (1, 3, 5):
                with self.subTest(axes=axes, block=block):
                    self.compare('p' + ''.join(map(str, axes)) + f'-b{block}', block, True)

    def test_threads_without_scaling_claim(self):
        self.shape = [7, 7, 9]
        self.sample([1, 0, 1])
        for threads in (1, 2, 4):
            self.overrides['omp_threads'] = str(threads)
            self.compare(f't{threads}', 3, True)

    def test_accepted_negative_at_periodic_halo_seam(self):
        self.shape = [7, 7, 7]
        self.sample([1, 1, 1])
        self.values[2*7 + 3] = -1e-14
        self.overrides['negative_tolerance'] = '1e-12'
        for block in (1, 3):
            self.compare(f'neg-b{block}', block, True)

    def test_complete_input_rejected_before_any_slab_output(self):
        self.values[-1] = -1.
        self.overrides.update(layout_mode='1', slab_planes='1')
        result, receipt = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt['stage'], 'metadata')
        self.assertIsNone(receipt['stats'])
        self.assertFalse(list(self.output.glob('*.f64')))
        self.assertFalse((self.output / 'flags.u8').exists())

    def test_zero_valid_global_output_still_fails(self):
        self.values = [0.] * 125
        self.overrides.update(layout_mode='1', slab_planes='1')
        result, receipt = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt['abi_status'], 3)
        self.assertEqual(receipt['npoints'], 125)
        self.assertEqual(receipt['stats']['total'], 125)
        self.assertEqual(receipt['stats']['valid'], 0)
        self.assertEqual((self.output / 'rdg.f64').stat().st_size, 125*8)

    def test_numeric_failure_stops_after_computed_slab(self):
        self.shape = [7, 5, 5]
        self.values = [.5] * 175
        self.values[(3*5 + 2)*5 + 2] = 1e308
        self.overrides.update(layout_mode='1', slab_planes='1', output_mode='1')
        result, receipt = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt['abi_status'], 4)
        self.assertEqual(receipt['npoints'], 175)
        self.assertEqual(receipt['stats']['total'], 75)
        self.assertEqual(receipt['stats']['numeric_failures'], 1)
        self.assertEqual((self.output / 'rdg.f64').stat().st_size, 75*8)
        self.assertEqual((self.output / 'grad.f64').stat().st_size, 75*24)

    def test_exact_slab_budget_excludes_unknown_atoms_only(self):
        self.shape = [9, 7, 5]
        self.values = [.5] * 315
        block, plane, q = 1, 35, 97
        budget = 8*315 + 8*(block+4)*plane + q*block*plane + 40*(block+7+5) + 8192 + 65536 + 4096
        self.overrides.update(layout_mode='1', slab_planes='1', output_mode='1', memory_budget_bytes=str(budget))
        result, receipt = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.new_output('budget-minus-one')
        self.overrides['memory_budget_bytes'] = str(budget-1)
        result, receipt = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt['stage'], 'memory')
        self.assertFalse((self.output / 'rdg.f64').exists())
        self.new_output('same-budget-full')
        self.overrides.update(layout_mode='0', slab_planes='0', memory_budget_bytes=str(budget))
        result, receipt = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt['stage'], 'memory')

    def test_invalid_layout_namelist_values(self):
        for i, (layout, planes) in enumerate(((2, 1), (1, 0), (1, 6), (0, 1), (1, -(1 << 63)))):
            self.new_output(f'invalid-{i}')
            self.overrides.update(layout_mode=str(layout), slab_planes=str(planes))
            result, receipt = self.execute()
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(receipt['stage'], 'settings')


if __name__ == "__main__":
    unittest.main()
