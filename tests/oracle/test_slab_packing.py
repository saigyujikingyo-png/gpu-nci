"""Packing selfchecks run with no production library installed."""
import numpy as np
import pytest
from numpy.testing import assert_array_equal

from reference.abi import DIAGNOSTIC, FULL, Evaluation
from reference.fields import quadratic
import slab_cases
from slab_cases import assert_reference, extreme_case, slab


@pytest.mark.parametrize("nx,block", [(5, 1), (5, 3), (5, 5), (7, 4)])
@pytest.mark.parametrize("periodic", [False, True])
@pytest.mark.parametrize("mode", [FULL, DIAGNOSTIC])
def test_independent_packer_plane_labels_and_capacities(nx, block, periodic, mode):
    rho = np.arange(nx * 7 * 9, dtype=np.float64).reshape(nx, 7, 9)
    before = rho.copy()
    starts = []
    for start in range(0, nx, block):
        count = min(block, nx - start)
        case = slab(rho, start, count, (periodic, True, False), mode)
        t = case.tile
        assert tuple(t.global_n) == rho.shape
        assert tuple(t.tile_start) == (start, 0, 0)
        assert tuple(t.tile_count) == (count, 7, 9)
        assert tuple(t.input_strides) == (63, 9, 1)
        expected = list(range(start - 2, start + count + 2)) if periodic else list(
            range(max(0, start - 2), min(nx, start + count + 2)))
        assert t.input_origin[0] == expected[0]
        assert t.input_shape[0] == len(expected)
        for local, global_x in enumerate(expected):
            assert_array_equal(case.rho[local], rho[global_x % nx])
        assert t.rho_capacity == len(expected) * 63
        assert t.field_capacity == t.flags_capacity == count * 63
        assert t.grad_capacity == (3 * count * 63 if mode == DIAGNOSTIC else 0)
        assert t.hess_capacity == (6 * count * 63 if mode == DIAGNOSTIC else 0)
        assert not np.shares_memory(case.rho, rho)
        starts += list(range(start, start + count))
    assert starts == list(range(nx))
    assert_array_equal(rho, before)


@pytest.mark.parametrize("kind,shape,field,x", [
    ("global_overflow", (7, 8, 5), "global_n", 2**62+1),
    ("global_byte_limit", (7, 5, 5), "global_n", 2**54),
    ("input_overflow", (7, 8, 5), "input_shape", 2**62+1)])
def test_overflow_fixture_changes_only_target_x_extent(kind, shape, field, x):
    baseline = slab(np.ones(shape), 3, 1, (True, True, True))
    case = extreme_case(kind)
    # Construct the expected legal descriptor first, changing just the intended X.
    getattr(baseline.tile, field)[0] = x
    assert bytes(case.tile) == bytes(baseline.tile)
    assert tuple(case.tile.tile_count[1:]) == tuple(case.tile.global_n[1:])
    assert tuple(case.tile.input_shape[1:]) == tuple(case.tile.global_n[1:])
    assert_array_equal(case.rho, baseline.rho)
    assert case.rho.size <= 200
    assert case.flags.size <= 40


@pytest.mark.parametrize("kind,field", [("global_overflow", "global_n"),
                                       ("input_overflow", "input_shape")])
def test_overflow_product_wraps_to_value_that_fits_real_capacity(kind, field):
    case = extreme_case(kind)
    x, y, z = getattr(case.tile, field)
    exact = x*y*z
    assert exact > 2**63-1
    wrapped = exact % 2**64
    assert wrapped == 40  # Positive signed int64, not a negative/zero-size shortcut.
    if field == "input_shape":
        assert case.tile.rho_capacity == case.rho.size == 200
        assert wrapped <= case.tile.rho_capacity
    else:
        assert wrapped == case.tile.field_capacity == case.tile.flags_capacity == 40


def test_global_byte_limit_fixture_is_safe_in_points_but_overflows_bytes():
    case = extreme_case("global_byte_limit")
    x, y, z = case.tile.global_n
    n = x*y*z
    assert 0 < n <= 2**63-1
    assert n*48 > 2**63-1


def reference_case(mode, kind):
    """Invent completed arrays and exact counts without loading any library."""
    periodic = (kind == "periodic-low",) * 3
    shape = (0, 5, 5) if kind == "empty" else (5, 5, 5)
    if kind == "nonempty":
        rho, grad, hess = quadratic(shape, np.eye(3), np.diag([-.5, -.25, .75]),
                                    origin=[-2] * 3)
    else:
        rho = np.full(shape, 1e-10)
        grad, hess = np.zeros((*shape, 3)), np.zeros((*shape, 3, 3))
    case = Evaluation(rho, periodic=periodic, mode=mode)
    for name in slab_cases.FIELDS[:-1]:
        field = getattr(case, name)
        if field is not None:
            field.fill(np.nan)
    if kind == "empty":
        case.flags.fill(0)
        counts = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    elif kind == "periodic-low":
        case.flags.fill(4)
        counts = [125, 0, 125, 0, 0, 0, 125, 0, 0, 0, 0]
    else:
        case.flags.fill(1 if kind == "nonempty" else 5)
        case.flags[2, 2, 2] = 64 if kind == "nonempty" else 4
        counts = ([125, 1, 124, 0, 124, 0, 0, 0, 0, 0, 1] if kind == "nonempty"
                  else [125, 0, 125, 0, 124, 0, 125, 0, 0, 0, 0])
    if kind == "nonempty":
        case.rdg[2, 2, 2], case.signedrho[2, 2, 2], case.lambda2[2, 2, 2] = 0, -20, -.25
        if mode == DIAGNOSTIC:
            case.grad[2, 2, 2] = 0
            case.hess[2, 2, 2] = [-.5, -.25, .75, 0, 0, 0]
    case.stats.total_points, case.stats.valid_points, case.stats.invalid_points, case.stats.numeric_failures = counts[:4]
    case.stats.bit_counts[:] = counts[4:]
    return case, rho, grad, hess, periodic


@pytest.mark.parametrize("mode", [FULL, DIAGNOSTIC])
@pytest.mark.parametrize("kind", ["empty", "finite-low", "periodic-low"])
def test_zero_valid_reference_checks_without_lapack(mode, kind, monkeypatch):
    def forbidden(*args):
        pytest.fail("zero valid points must not invoke the eigensolver reference")
    monkeypatch.setattr(slab_cases, "nci", forbidden)
    assert_reference(*reference_case(mode, kind))


@pytest.mark.parametrize("mode", [FULL, DIAGNOSTIC])
@pytest.mark.parametrize("bit", [0, 4, 5, 6, 7])
def test_zero_valid_reference_rejects_wrong_flags(mode, bit):
    case, *inputs = reference_case(mode, "finite-low")
    case.flags[2, 2, 2] ^= 1 << bit
    with pytest.raises(AssertionError):
        assert_reference(case, *inputs)


PRESENT_FIELDS = [(mode, name) for mode in (FULL, DIAGNOSTIC)
                  for name in ("rdg", "signedrho", "lambda2", "grad", "hess")
                  if mode == DIAGNOSTIC or name not in ("grad", "hess")]


@pytest.mark.parametrize("mode,name", PRESENT_FIELDS)
def test_zero_valid_reference_rejects_finite_invalid_field(mode, name):
    case, *inputs = reference_case(mode, "finite-low")
    getattr(case, name)[2, 2, 2] = 0
    with pytest.raises(AssertionError):
        assert_reference(case, *inputs)


@pytest.mark.parametrize("mode", [FULL, DIAGNOSTIC])
@pytest.mark.parametrize("counter", range(11))
def test_zero_valid_reference_rejects_each_wrong_stat(mode, counter):
    case, *inputs = reference_case(mode, "periodic-low")
    if counter < 4:
        name = ("total_points", "valid_points", "invalid_points", "numeric_failures")[counter]
        setattr(case.stats, name, getattr(case.stats, name) + 1)
    else:
        case.stats.bit_counts[counter - 4] += 1
    with pytest.raises(AssertionError):
        assert_reference(case, *inputs)


@pytest.mark.parametrize("mode", [FULL, DIAGNOSTIC])
def test_nonempty_reference_still_calls_lapack(mode, monkeypatch):
    original = slab_cases.nci
    calls = []
    def recorded(rho, grad, hess):
        calls.append(rho.size)
        return original(rho, grad, hess)
    monkeypatch.setattr(slab_cases, "nci", recorded)
    assert_reference(*reference_case(mode, "nonempty"))
    assert calls == [1]


@pytest.mark.parametrize("mode,name", PRESENT_FIELDS)
@pytest.mark.parametrize("replacement", [1., np.nan])
def test_nonempty_reference_rejects_wrong_valid_field(mode, name, replacement):
    case, *inputs = reference_case(mode, "nonempty")
    getattr(case, name)[2, 2, 2] = replacement
    with pytest.raises(AssertionError):
        assert_reference(case, *inputs)
