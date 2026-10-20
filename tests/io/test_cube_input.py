"""Small generated synthetic parser tests; no chemistry inputs or solver runs."""
import hashlib
import math
from pathlib import Path
import random
import subprocess
import sys
import unittest

PROBE = Path(sys.argv[1]).resolve()
FIXTURES = Path(sys.argv[2]).resolve()
FIXTURES.mkdir(parents=True, exist_ok=True)
sys.argv = sys.argv[:1]

OK, IO, MISSING, EXTRA, INTEGER, REAL, NONFINITE, UNSUPPORTED = range(8)
DIMENSION, OVERFLOW, MEMORY, ALLOCATION, ATOM, SINGULAR, CONDITION = range(8, 15)
METADATA, UNIT, DENSITY, TOKEN_LONG, GRID_RANGE = range(15, 20)


def fixture(*, shape=(5, 5, 5), natoms=0, origin=(0, 0, 0),
            j=((1, 0, 0), (0, 1, 0), (0, 0, 1)), atoms=(),
            nval=None, values=None, newline="\n", comments=None):
    lines = list(comments or ("synthetic fixture only", "units deliberately not inferred"))
    header = f"{natoms} " + " ".join(map(str, origin))
    if nval is not None:
        header += f" {nval}"
    lines.append(header)
    for axis in range(3):
        lines.append(f"{shape[axis]} " + " ".join(str(j[row][axis]) for row in range(3)))
    lines.extend(atoms)
    if values is None:
        values = map(str, range(1, 126))
    lines.append(" ".join(values))
    return newline.join(lines) + newline


class CubeInputTests(unittest.TestCase):
    counter = 0

    def parse(self, text, mode="none", budget=None, points=None):
        CubeInputTests.counter += 1
        path = FIXTURES / f"synthetic_{CubeInputTests.counter:04d}.cube"
        path.write_bytes(text.encode("ascii"))
        original_hash = hashlib.sha256(path.read_bytes()).digest()
        args = [str(PROBE), str(path), mode]
        if budget is not None or points is not None:
            args.append(str(268435456 if budget is None else budget))
        if points is not None:
            args.append(str(points))
        result = subprocess.run(args, text=True, capture_output=True, timeout=10, check=True)
        self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), original_hash,
                         "Native parser modified its synthetic input file")
        self.assertEqual(result.stderr, "", result.stderr)
        output = {}
        for line in result.stdout.splitlines():
            key, _, value = line.partition(" ")
            output[key] = value.strip()
        return output

    def rejected(self, text, expected, **kwargs):
        result = self.parse(text, **kwargs)
        self.assertEqual(int(result["STATUS"]), expected, result)
        self.assertTrue(result["MESSAGE"])
        self.assertEqual(result["ALLOCATED"].split(), ["F", "F"])
        self.assertEqual(result["FLAGS"].split(), ["F", "F", "F"])
        return result

    def test_z_fastest_and_raw_not_certified(self):
        result = self.parse(fixture())
        self.assertEqual(int(result["STATUS"]), OK)
        self.assertEqual(result["SHAPE"], "5 5 5")
        values = list(map(float, result["RHO"].split()))
        self.assertEqual(values, list(range(1, 126)))
        self.assertEqual(values[(1 * 5 + 2) * 5 + 3], 39)
        self.assertEqual(result["FLAGS"].split(), ["T", "F", "F"])
        self.assertEqual(result["CLEARED"].split(), ["F", "F"])

    def test_atom_origin_nval_and_exponents(self):
        text = fixture(natoms=1, atoms=["79 11.0d0 1e-1 -2D+0 +.3E1"],
                       origin=("1d0", "-.2e1", "+3."), nval=1,
                       values=["+.125d+1"] * 125)
        result = self.parse(text)
        self.assertEqual(int(result["STATUS"]), OK)
        self.assertEqual(list(map(float, result["ORIGIN"].split())), [1, -2, 3])
        self.assertEqual(list(map(float, result["ATOM1"].split())), [79, 11, .1, -2, 3])
        self.assertTrue(all(x == 1.25 for x in map(float, result["RHO"].split())))

    def test_whitespace_records_and_large_streamed_lines(self):
        for nl in ["\n", "\r\n", "\r"]:
            with self.subTest(newline=repr(nl)):
                text = fixture(newline=nl, comments=("x" * 20000, ""),
                               values=["\t0.25" + " " * 96] * 125)
                result = self.parse(text.rstrip())
                self.assertEqual(int(result["STATUS"]), OK)
                self.assertEqual(float(result["RHO"].split()[-1]), .25)

    def test_data_wraps_arbitrary_lines(self):
        result = self.parse(fixture(values=["\n\t" + str(x) for x in range(1, 126)]))
        self.assertEqual(int(result["STATUS"]), OK)

    def test_missing_comments_and_header(self):
        for text in ["", "comment only", "one\ntwo\n", "one\ntwo\n0 0 0\n"]:
            with self.subTest(text=text):
                self.rejected(text, MISSING)

    def test_missing_atom_field_stays_in_record(self):
        self.rejected(fixture(natoms=1, atoms=["1 1 0 0"]), MISSING)

    def test_extra_header_fields(self):
        for text in [fixture(nval="1 2"), fixture().replace("5 1 0 0", "5 1 0 0 2"),
                     fixture(natoms=1, atoms=["1 1 0 0 0 2"])]:
            with self.subTest(text=text[:90]):
                self.rejected(text, EXTRA)

    def test_negative_natoms(self):
        self.rejected(fixture(natoms=-1), UNSUPPORTED)

    def test_nonpositive_and_small_dimensions(self):
        for value, expected in [(-5, UNSUPPORTED), (0, DIMENSION), (4, DIMENSION)]:
            with self.subTest(value=value):
                self.rejected(fixture(shape=(5, value, 5)), expected)

    def test_multifield_nval(self):
        for value in [0, 2, -1]:
            with self.subTest(value=value):
                self.rejected(fixture(nval=value), UNSUPPORTED)

    def test_atom_numbers(self):
        for z in ["0", "-1", "119"]:
            with self.subTest(z=z):
                self.rejected(fixture(natoms=1, atoms=[f"{z} 1 0 0 0"]), ATOM)
        self.rejected(fixture(natoms=1, atoms=["H 1 0 0 0"]), INTEGER)

    def test_missing_and_extra_density(self):
        self.rejected(fixture(values=["1"] * 124), MISSING)
        self.rejected(fixture(values=["1"] * 126), EXTRA)
        self.rejected(fixture(values=["1"] * 125 + ["trailing_garbage"]), EXTRA)

    def test_nonfinite_every_field_kind(self):
        for text in [fixture(origin=("NaN", 0, 0)),
                     fixture(j=((1, 0, 0), (0, "Inf", 0), (0, 0, 1))),
                     fixture(natoms=1, atoms=["1 -Infinity 0 0 0"]),
                     fixture(natoms=1, atoms=["1 1 NaN 0 0"])]:
            with self.subTest(text=text[:100]):
                self.rejected(text, NONFINITE)
        for value in ["NaN", "nan", "+INF", "-Inf", "Infinity"]:
            with self.subTest(value=value):
                self.rejected(fixture(values=[value] + ["1"] * 124), NONFINITE)

    def test_reject_list_directed_shortcuts_and_malformed_numbers(self):
        for value in ["125*1", "2*0.5", "1,2", "/", "1/2", "1/", "1e", "1e+", ".", "+", "1_8", "0x1", "1e2x"]:
            with self.subTest(value=value):
                self.rejected(fixture(values=[value] + ["1"] * 124), REAL)
        self.rejected(fixture(natoms="1.0"), INTEGER)
        self.rejected(fixture(natoms="0,9"), INTEGER)
        self.rejected(fixture(shape=("5,9", 5, 5)), INTEGER)
        self.rejected(fixture(values=["1e9999"] + ["1"] * 124), NONFINITE)

    def test_token_length_is_bounded(self):
        self.rejected(fixture(values=["1" * 257] + ["1"] * 124), TOKEN_LONG)

    def test_int64_and_product_overflow_before_allocation(self):
        for text in [fixture(natoms="9223372036854775808"),
                     fixture(shape=(9223372036854775807, 5, 5)),
                     fixture(shape=(500000000, 500000000, 5)),
                     fixture(natoms=9223372036854775807)]:
            with self.subTest(text=text[:130]):
                self.rejected(text, OVERFLOW)

    def test_explicit_memory_and_point_limits(self):
        self.rejected(fixture(), MEMORY, budget=9000)
        self.rejected(fixture(), MEMORY, points=124)
        self.rejected(fixture(), MEMORY, budget=0)
        self.rejected(fixture(), MEMORY, points=-1)
        self.assertEqual(int(self.parse(fixture(), points=125)["STATUS"]), OK)

    def test_singular_and_conditioned_grids(self):
        self.rejected(fixture(j=((0, 0, 0), (0, 0, 0), (0, 0, 0))), SINGULAR)
        result = self.parse(fixture(j=((1, 1, 0), (0, 0, 0), (0, 0, 1))))
        self.assertIn(int(result["STATUS"]), [SINGULAR, CONDITION])
        self.rejected(fixture(j=((1, 0, 0), (0, 1, 0), (0, 0, .000999))), CONDITION)
        self.assertEqual(int(self.parse(fixture(j=((1, 0, 0), (0, 1, 0), (0, 0, .001))))["STATUS"]), OK)

    def test_left_handed_shear_inverse_and_volume(self):
        result = self.parse(fixture(j=((-1, 1, 0), (0, 1, 0), (0, 0, 1))))
        self.assertEqual(int(result["STATUS"]), OK)
        self.assertAlmostEqual(float(result["COND"]), (3 + math.sqrt(5)) / 2, places=12)
        self.assertEqual(float(result["VOLUME"]), 1)
        self.assertEqual(list(map(float, result["INVERSE1"].split())), [-1, 1, 0])

    def test_scaled_geometry_range(self):
        for scale in [1e-200, 1e200]:
            with self.subTest(scale=scale):
                self.rejected(fixture(j=((scale, 0, 0), (0, scale, 0), (0, 0, scale))), GRID_RANGE)
        result = self.parse(fixture(j=((1e-80, 0, 0), (0, 1e-80, 0), (0, 0, 1e-80))))
        self.assertEqual(int(result["STATUS"]), OK)
        self.assertAlmostEqual(float(result["INVERSE1"].split()[0]) / 1e80, 1)

    def test_rotated_singular_values_independent_oracle(self):
        # Rotations preserve preselected singular values: no dependency on our SVD.
        rng = random.Random(20261020)
        for condition in [1.0, 2.0, 30.0, 999.0, 1001.0]:
            for _ in range(4):
                a, b = rng.uniform(-3, 3), rng.uniform(-3, 3)
                left = ((math.cos(a), -math.sin(a), 0), (math.sin(a), math.cos(a), 0), (0, 0, 1))
                right = ((1, 0, 0), (0, math.cos(b), -math.sin(b)), (0, math.sin(b), math.cos(b)))
                sv = (1.0, .3, 1 / condition) if condition > 4 else (1., 1., 1 / condition)
                j = [[sum(left[r][k] * sv[k] * right[k][c] for k in range(3)) for c in range(3)] for r in range(3)]
                result = self.parse(fixture(j=j))
                with self.subTest(condition=condition, a=a, b=b):
                    if condition > 1000:
                        self.assertEqual(int(result["STATUS"]), CONDITION, result)
                    else:
                        self.assertEqual(int(result["STATUS"]), OK, result)
                        self.assertAlmostEqual(float(result["COND"]) / condition, 1, places=11)
                        inverse = [list(map(float, result[f"INVERSE{r+1}"].split())) for r in range(3)]
                        for r in range(3):
                            for c in range(3):
                                self.assertAlmostEqual(sum(j[r][k] * inverse[k][c] for k in range(3)), float(r == c), places=11)

    def test_metadata_explicit_and_never_scientifically_certified(self):
        for mode in ["valid", "valence", "core_augmented", "promolecular"]:
            with self.subTest(mode=mode):
                result = self.parse(fixture(), mode)
                self.assertEqual(int(result["META_STATUS"]), OK)
                self.assertEqual(result["FLAGS"].split(), ["T", "T", "F"])

    def test_metadata_rejects_unknown_semantics(self):
        for mode in ["unknown", "spin", "orbital", "representation", "periodic", "endpoint", "finite_endpoint", "bad_tolerance", "nan_tolerance"]:
            with self.subTest(mode=mode):
                result = self.parse(fixture(), mode)
                self.assertEqual(int(result["META_STATUS"]), METADATA)
                self.assertEqual(result["FLAGS"].split(), ["T", "F", "F"])

    def test_metadata_units_not_guessed_or_converted(self):
        for mode in ["angstrom", "density_unit"]:
            with self.subTest(mode=mode):
                result = self.parse(fixture(comments=("BOHR ALL ELECTRON SPIN SUMMED", "fake declaration")), mode)
                self.assertEqual(int(result["META_STATUS"]), UNIT)
                self.assertEqual(float(result["FIRST_AFTER_METADATA"]), 1.)

    def test_negative_density_raw_preserved_and_metadata_gate(self):
        text = fixture(values=["-1e-7"] + ["0"] * 124)
        result = self.parse(text, "valid")
        self.assertEqual(int(result["STATUS"]), OK)
        self.assertEqual(int(result["META_STATUS"]), DENSITY)
        self.assertEqual(float(result["FIRST_AFTER_METADATA"]), -1e-7)
        result = self.parse(text, "negative_tolerance")
        self.assertEqual(int(result["META_STATUS"]), OK)
        self.assertEqual(float(result["FIRST_AFTER_METADATA"]), -1e-7)
        self.assertEqual(result["FLAGS"].split(), ["T", "T", "F"])

    def test_missing_file_error_no_partial_grid(self):
        result = subprocess.run([str(PROBE), str(FIXTURES / "does_not_exist.cube"), "none"],
                                text=True, capture_output=True, timeout=10, check=True)
        self.assertIn("STATUS 1", result.stdout)
        self.assertIn("ALLOCATED F F", result.stdout)


if __name__ == "__main__":
    execution = unittest.main(verbosity=2, exit=False)
    print(f"Native Fortran parser invocations: {CubeInputTests.counter + 1}")
    sys.exit(not execution.result.wasSuccessful())
