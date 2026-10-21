"""Pure OpenACC CLI arithmetic and mocked protocol tests; no native execution."""

import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import test_cli as legacy

CLI = legacy.MODULE


def gpu_card(shape=(5, 7, 9), block=None, diagnostic=False, periodic_x=0):
    card = legacy.fixture_card(b"opaque synthetic input\n")
    card["grid"]["shape"] = list(shape)
    card["metadata"]["periodic"][0] = periodic_x
    card["metadata"]["endpoint_convention"][0] = "independent_samples" if periodic_x else "finite_nodes"
    card["compute"].update(backend="openacc", output_mode="diagnostic" if diagnostic else "full")
    if block is not None:
        card["compute"].update(layout="x_slabs", slab_planes=block)
    card["limits"].update(max_points=CLI.INT64_MAX, memory_budget_bytes=CLI.INT64_MAX)
    return card


def enumerated_plan(card, atoms=0):
    """Independent, bounded test oracle enumerates every actual canonical tile."""
    nx, ny, nz = card["grid"]["shape"]
    comp = card["compute"]
    g, p = nx * ny * nz, ny * nz
    d = int(comp["output_mode"] == "diagnostic")
    if comp["layout"] == "full_grid":
        workspaces = [8 * g + 40 * (nx + ny + nz) + (37 + 72 * d) * g]
        caller, slab = (25 + 72 * d) * g, 0
    else:
        block = comp["slab_planes"]
        caller, slab = (25 + 72 * d) * block * p, 8 * (block + 4) * p
        workspaces = []
        for start in range(0, nx, block):
            b = min(block, nx - start)
            left = 2 if card["metadata"]["periodic"][0] else min(2, start)
            right = 2 if card["metadata"]["periodic"][0] else min(2, nx - start - b)
            workspaces.append(8 * (b + left + right) * p + 40 * (b + ny + nz) + (37 + 72 * d) * b * p)
    common = 65536 + 4096 * comp["omp_threads"]
    return dict(host_bytes=8 * g + atoms + 8192 + caller + slab + max(workspaces) + common + 65536,
                reader_atom_bytes=atoms, device_array_bytes=max(workspaces),
                host_fixed_common_bytes=common, host_fixed_openacc_bytes=65536,
                device_static_bytes=288, launch_parameter_bytes=272)


def build_info(library, capabilities=None):
    build = dict(protocol_version=1, source_revision="synthetic", compiler_id="stub", compiler_version="0",
                 build_type="", fp_policy="pure test only", backend_library=str(library))
    if capabilities is not None:
        build["supported_backends"] = capabilities
    return build


def native_receipt(npoints):
    return dict(protocol_version=1, state="completed", stage="evaluate", message="synthetic only", abi_status=0,
                npoints=npoints, stats=dict(total=npoints, valid=npoints, invalid=0, numeric_failures=0,
                                           bit_counts=[0, 0, 0, 0, 0, 0, npoints]))


class OpenaccArithmeticTests(unittest.TestCase):
    def test_candidate_maximum_matches_enumeration(self):
        for nx in range(5, 41):
            for block in range(1, nx + 1):
                candidates = CLI.openacc_tile_candidates(nx, block)
                self.assertLessEqual(len(candidates), 4)
                self.assertEqual(len(candidates), len(set(candidates)))
                for ny, nz in ((5, 5), (7, 9), (11, 5)):
                    for d in (False, True):
                        for periodic in (0, 1):
                            card = gpu_card((nx, ny, nz), block, d, periodic)
                            g = nx * ny * nz
                            self.assertEqual(CLI.openacc_memory_plan(card, g), enumerated_plan(card),
                                             (nx, ny, nz, block, d, periodic))

    def test_full_grid_has_no_periodic_caller_halo(self):
        for diagnostic in (False, True):
            finite = gpu_card(diagnostic=diagnostic)
            periodic = gpu_card(diagnostic=diagnostic, periodic_x=1)
            self.assertEqual(CLI.openacc_memory_plan(finite, 315), enumerated_plan(finite))
            self.assertEqual(CLI.openacc_memory_plan(finite, 315), CLI.openacc_memory_plan(periodic, 315))

    def test_tiny_and_exact_host_budgets(self):
        for block in (None, 1, 3, 5):
            for diagnostic in (False, True):
                card = gpu_card(block=block, diagnostic=diagnostic)
                expected = enumerated_plan(card)["host_bytes"]
                self.assertEqual(CLI.memory_lower_bound(card, 315), expected)
                for budget in (1, expected - 1, expected):
                    card["limits"]["memory_budget_bytes"] = budget
                    if budget < expected:
                        with self.assertRaises(CLI.CliError):
                            CLI.validate_card(card)
                    else:
                        self.assertEqual(CLI.validate_card(card), 315)

    def test_large_slab_count_still_has_only_four_candidates(self):
        # A trillion tiles cannot be enumerated, but all mapped objects fit.
        nx = 10**12 + 1
        card = gpu_card((nx, 5, 5), block=1)
        self.assertLessEqual(len(CLI.openacc_tile_candidates(nx, 1)), 4)
        self.assertEqual(CLI.validate_card(card), nx * 25)
        self.assertEqual(CLI.openacc_tile_candidates(CLI.INT64_MAX, CLI.INT64_MAX), [(0, CLI.INT64_MAX)])

    def test_mapped_field_exact_int32_boundary(self):
        # Nout = 25 * Nz; choose a product just below/above 24*Nout's cap.
        last_z = CLI.INT32_MAX // (24 * 25)
        for z, accepted in ((last_z, True), (last_z + 1, False)):
            card = gpu_card((5, 5, z))
            if accepted:
                self.assertEqual(CLI.validate_card(card), 25 * z)
            else:
                with self.assertRaisesRegex(CLI.CliError, "INT32_MAX"):
                    CLI.validate_card(card)

    def test_halo_object_limit_and_checked_int64(self):
        # B=1 periodic input object can exceed the cap even when output fits.
        z = CLI.INT32_MAX // (8 * 5 * 5) + 1
        card = gpu_card((5, 5, z), block=1, periodic_x=1)
        with self.assertRaisesRegex(CLI.CliError, "INT32_MAX"):
            CLI.validate_card(card)
        for shape in ((CLI.INT64_MAX // 25, 5, 5), (CLI.INT64_MAX, 5, 5)):
            with self.assertRaisesRegex(CLI.CliError, "int64"):
                CLI.validate_card(gpu_card(shape, block=1))

    def test_cpu_namelist_bytes_unchanged(self):
        card = legacy.fixture_card(b"synthetic bytes\n")
        expected = ("&nci_run\n protocol_version = 1,\n shape = 5, 7, 9,\n origin = 0, -0.25, 2,\n"
                    " step_vectors = 0.25, 0, 0, 0.125, 0.5, 0, 0, 0.125, 0.75,\n periodic = 0, 1, 0,\n"
                    " endpoint_convention = 'finite_nodes', 'independent_samples', 'finite_nodes',\n"
                    " quantity = 'electron_density',\n spin_convention = 'spin_summed',\n"
                    " density_representation = 'all_electron',\n length_unit = 'bohr',\n"
                    " density_unit = 'electron/bohr^3',\n output_mode = 0,\n rho_min = 9.9999999999999998e-13,\n"
                    " negative_tolerance = 0,\n omp_threads = 1,\n memory_budget_bytes = 16777216,\n"
                    " max_points = 1000\n/\n").encode("ascii")
        self.assertEqual(CLI.namelist(card), expected)
        for block in (None, 1, 3):
            cpu = copy.deepcopy(card)
            if block:
                cpu["compute"].update(layout="x_slabs", slab_planes=block)
            gpu = copy.deepcopy(cpu)
            gpu["compute"]["backend"] = "openacc"
            self.assertEqual(CLI.namelist(gpu).replace(b" backend = 1,\n", b""), CLI.namelist(cpu))
        for backend in ("cuda", "OPENACC", "", 1, True, None):
            card["compute"]["backend"] = backend
            with self.assertRaises(CLI.CliError):
                CLI.validate_card(card)


class OpenaccProtocolTests(unittest.TestCase):
    def setUp(self):
        self.card = gpu_card()
        self.receipt = native_receipt(315)
        self.receipt.update(backend="openacc", memory_plan=enumerated_plan(self.card, atoms=73))
        self.library = Path(__file__).resolve()

    def test_exact_capability_arrays_and_legacy_cpu(self):
        for capabilities in (None, ["cpu"], ["cpu", "openacc"]):
            build = build_info(self.library, capabilities)
            CLI.validate_build(build, "cpu")
            if capabilities == ["cpu", "openacc"]:
                CLI.validate_build(build, "openacc")
            else:
                with self.assertRaises(CLI.CliError):
                    CLI.validate_build(build, "openacc")
        for capabilities in ([], ["openacc"], ["openacc", "cpu"], ["cpu", "cpu"], ["cpu", "cuda"],
                             ["cpu", True], ["cpu", 1], "cpu", {}, ("cpu",)):
            with self.subTest(capabilities=capabilities), self.assertRaises(CLI.CliError):
                CLI.validate_build(build_info(self.library, capabilities))
        build = build_info(self.library)
        build["supported_backends"] = None
        with self.assertRaises(CLI.CliError):
            CLI.validate_build(build)

    def test_gpu_receipt_exact_budget_and_atom_addition(self):
        for block in (None, 1, 3):
            for diagnostic in (False, True):
                card = gpu_card(block=block, diagnostic=diagnostic)
                for atoms in (0, 73, 8192):
                    receipt = native_receipt(315)
                    receipt.update(backend="openacc", memory_plan=enumerated_plan(card, atoms))
                    card["limits"]["memory_budget_bytes"] = receipt["memory_plan"]["host_bytes"]
                    CLI.validate_native(receipt, 315, card)
                    card["limits"]["memory_budget_bytes"] -= 1
                    with self.assertRaises(CLI.CliError):
                        CLI.validate_native(receipt, 315, card)

    def test_gpu_receipt_missing_unknown_or_mismatched_metadata(self):
        mutations = [lambda r: r.pop("backend"), lambda r: r.update(backend="cpu"),
                     lambda r: r.pop("memory_plan"), lambda r: r.update(memory_plan=None),
                     lambda r: r["memory_plan"].update(extra=0)]
        for key in self.receipt["memory_plan"]:
            mutations.append(lambda r, k=key: r["memory_plan"].pop(k))
            for value in (None, True, 1.0, -1, CLI.INT64_MAX + 1, "0"):
                mutations.append(lambda r, k=key, v=value: r["memory_plan"].update({k: v}))
            if key != "reader_atom_bytes":
                for delta in (-1, 1):
                    mutations.append(lambda r, k=key, d=delta: r["memory_plan"].update({k: r["memory_plan"][k] + d}))
        # An atom increase must also increase host_bytes; int64 addition is checked.
        mutations += [lambda r: r["memory_plan"].update(reader_atom_bytes=74),
                      lambda r: r["memory_plan"].update(reader_atom_bytes=CLI.INT64_MAX)]
        for mutation in mutations:
            receipt = copy.deepcopy(self.receipt)
            mutation(receipt)
            with self.subTest(receipt=receipt), self.assertRaises(CLI.CliError) as caught:
                CLI.validate_native(receipt, 315, self.card)
            self.assertEqual(caught.exception.stage, "native_receipt")

    def test_cpu_receipt_compatibility_and_contradictions(self):
        card = legacy.fixture_card(b"opaque input\n")
        receipt = native_receipt(315)
        CLI.validate_native(receipt, 315, card)
        receipt["backend"] = "cpu"
        CLI.validate_native(receipt, 315, card)
        for value in ("openacc", "cuda", 0, None):
            receipt["backend"] = value
            with self.assertRaises(CLI.CliError):
                CLI.validate_native(receipt, 315, card)
        receipt["backend"] = "cpu"
        for value in (None, {}, self.receipt["memory_plan"]):
            receipt["memory_plan"] = value
            with self.assertRaises(CLI.CliError):
                CLI.validate_native(receipt, 315, card)

    def test_mocked_run_rejects_worker_mismatch_before_evaluation(self):
        self.mocked_run(["cpu"], expected_calls=1, expected_stage="build_info")

    def test_mocked_run_rejects_legacy_worker_before_evaluation(self):
        self.mocked_run(None, expected_calls=1, expected_stage="build_info")

    def test_mocked_run_publishes_gpu_success_last(self):
        self.mocked_run(["cpu", "openacc"], expected_calls=2)

    def test_mocked_run_rejects_bad_plan_and_never_falls_back(self):
        self.receipt["memory_plan"]["device_array_bytes"] -= 1
        self.mocked_run(["cpu", "openacc"], expected_calls=2, expected_stage="native_receipt")

    def test_mocked_run_rejects_missing_plan_without_success(self):
        self.receipt.pop("memory_plan")
        self.mocked_run(["cpu", "openacc"], expected_calls=2, expected_stage="native_receipt")

    def test_mocked_cpu_run_accepts_optional_worker_capabilities(self):
        self.card["compute"]["backend"] = "cpu"
        self.receipt = native_receipt(315)
        self.mocked_run(["cpu", "openacc"], expected_calls=2)

    def test_mocked_worker_failure_preserves_logs_without_fallback(self):
        self.mocked_run(["cpu", "openacc"], expected_calls=2, expected_stage="worker", worker_exit=4)

    def mocked_run(self, capabilities, expected_calls, expected_stage=None, worker_exit=0):
        with tempfile.TemporaryDirectory(prefix="nci-cli-openacc-mock-") as temporary:
            base = Path(temporary)
            (base / "input source.cube").write_bytes(b"opaque synthetic input\n")
            (base / "card.json").write_text(json.dumps(self.card))
            library, driver = base / "library", base / "driver"
            library.write_bytes(b"opaque fingerprint only")
            driver.write_bytes(b"never executed")
            output = base / "output"

            def child(argv, directory, prefix, timeout):
                if prefix:
                    (directory / "build-info.stdout.log").write_text(json.dumps(build_info(library, capabilities)))
                else:
                    (directory / "native.json").write_text(json.dumps(self.receipt))
                    (directory / "stderr.log").write_text("synthetic runtime notice; preserve verbatim\n")
                    for name, width, metadata in CLI.output_specs(self.card):
                        (directory / name).write_bytes(b"\0" * (width * 315))
                return dict(returncode=0 if prefix else worker_exit, timed_out=False, timeout_seconds=timeout)

            args = SimpleNamespace(card=base / "card.json", driver=driver, output_dir=output)
            with mock.patch.object(CLI, "child_process", side_effect=child) as launched:
                result = CLI.run(args)
            self.assertEqual(launched.call_count, expected_calls)
            manifest = json.loads((output / "manifest.json").read_text())
            if expected_stage:
                self.assertEqual(result, 1)
                self.assertEqual(manifest["stage"], expected_stage)
                self.assertEqual(manifest["state"], "failed")
                self.assertFalse((output / "SUCCESS").exists())
            else:
                self.assertEqual(result, 0)
                self.assertEqual(manifest["state"], "completed_numerical")
                self.assertTrue((output / "SUCCESS").is_file())
            if expected_calls == 1:
                self.assertIsNone(manifest["worker"])
            else:
                self.assertEqual((output / "stderr.log").read_text(), "synthetic runtime notice; preserve verbatim\n")


if __name__ == "__main__":
    unittest.main()
