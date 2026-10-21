"""Actual public C ABI only: no hooks, skips, candidate-derived expectations or clocks."""
import ctypes as ct
from itertools import product

import numpy as np
import pytest
from numpy.testing import assert_allclose, assert_array_equal

from .support import guard_case, byte_snapshot, assert_unchanged, FIELDS
from reference.abi import (Evaluation, options, FULL, DIAGNOSTIC, OK, INVALID_ARGUMENT,
                           UNSUPPORTED, INVALID_INPUT, NUMERIC_FAILURE, BACKEND_UNAVAILABLE)
from reference.fields import quadratic, periodic_fourier, fd4, input_flags
from reference.extreme import (finite_large_rdg_fixture, exact_center_derivatives,
                               high_precision_rdg)
from slab_cases import (J, slab, assert_reference, assert_same_fields, stats_counts,
                        assert_stats, extreme_case)
import test_library_fields as original

PERIODIC = list(product((False, True), repeat=3))


def gpu_options(**kwargs):
    return options(backend=1, **kwargs)


def run_reference(recorder, handle, case, label, rho, grad, hess, periodic, rho_min=1e-8):
    rc, error = recorder.run(handle, case, label)
    expected_flags = input_flags(rho, periodic, rho_min)
    valid = (expected_flags & 15) == 0
    assert rc == (OK if np.any(valid) else INVALID_INPUT), error
    assert_reference(case, rho, grad, hess, periodic, rho_min)
    return rc


@pytest.mark.parametrize('periodic', PERIODIC)
@pytest.mark.parametrize('mode', [FULL, DIAGNOSTIC])
def test_full_b1_b3_all_boundaries(public, periodic, mode):
    rho, grad, hess = periodic_fourier((7, 9, 11), J,
        [(.1, (1, 2, 1), .2), (.08, (2, -1, 0), -.4)])
    label = f'matrix/{int(mode)}/{"".join(str(int(p)) for p in periodic)}'
    full = guard_case(Evaluation(rho, J, periodic, mode))
    with public.context(gpu_options(mode=mode), label) as handle:
        run_reference(public, handle, full, label+'/full', rho, grad, hess, periodic)
        for block in (1, 3):
            counts = np.zeros(11, dtype=np.int64)
            for start in range(0, 7, block):
                count = min(block, 7-start)
                case = guard_case(slab(rho, start, count, periodic, mode))
                rc, error = public.run(handle, case, f'{label}/B{block}/s{start}')
                expected = Evaluation(rho[start:start+count], J, periodic, mode)
                for name in FIELDS:
                    value = getattr(full, name)
                    if value is not None:
                        setattr(expected, name, value[start:start+count])
                assert_same_fields(case, expected)
                assert_stats(case)
                assert rc == (OK if case.stats.valid_points else INVALID_INPUT), error
                counts += stats_counts(case.stats)
            assert_array_equal(counts, stats_counts(full.stats))


@pytest.mark.parametrize('periodic', [(False,)*3, (True,)*3])
def test_nx5_b1_short_tail_and_duplicated_halo(public, periodic):
    rho, grad, hess = periodic_fourier((5, 7, 9), J, [(.1, (1, 1, 2), .3)])
    with public.context(gpu_options(), 'nx5') as handle:
        full = guard_case(Evaluation(rho, J, periodic))
        run_reference(public, handle, full, f'nx5/{periodic}/full', rho, grad, hess, periodic)
        for block in (1, 3):
            counts = np.zeros(11, dtype=np.int64)
            for start in range(0, 5, block):
                count = min(block, 5-start)
                case = guard_case(slab(rho, start, count, periodic))
                rc, _ = public.run(handle, case, f'nx5/{periodic}/B{block}/s{start}')
                for name in FIELDS:
                    a, b = getattr(case, name), getattr(full, name)[start:start+count]
                    assert_array_equal(np.isnan(a), np.isnan(b))
                    if name == 'flags':
                        assert_array_equal(a, b)
                    else:
                        mask = np.isfinite(b)
                        assert_array_equal(a[mask].view(np.uint64), b[mask].view(np.uint64))
                assert_stats(case)
                assert rc == (OK if case.stats.valid_points else INVALID_INPUT)
                counts += stats_counts(case.stats)
            assert_array_equal(counts, stats_counts(full.stats))


SPECIAL = ['constant-full', 'constant-diagnostic'] + [
    f'quadratic-{hand}-{sign}' for hand in (0, 1) for sign in (0, 1)] + [
    'negative-center', 'negative-corner', 'near-positive', 'near-negative',
    'repeat-negative', 'repeat-positive', 'condition-999', 'condition-skew',
    'low-zero', 'all-invalid', 'overflow', 'large-finite', 'subnormal-constant', 'subnormal-gradient']


@pytest.mark.parametrize('kind', SPECIAL)
def test_original_mathematical_edge_cases(public, kind):
    mode, periodic, matrix, opts = DIAGNOSTIC, (False,)*3, np.eye(3), {}
    if kind.startswith('constant'):
        mode = FULL if kind.endswith('full') else DIAGNOSTIC
        rho = np.full((7, 9, 11), .125)
        grad, hess = np.zeros((*rho.shape, 3)), np.zeros((*rho.shape, 3, 3))
    elif kind.startswith('quadratic') or kind.startswith('repeat') or kind.startswith('near'):
        matrix = J.copy()
        spectrum = [-.4, .2, .6]
        if kind.startswith('quadratic'):
            _, hand, sign = kind.split('-')
            if int(hand):
                matrix[:, 0] *= -1
            if int(sign):
                spectrum = [-.7, -.2, .5]
        if kind.startswith('repeat'):
            spectrum = [-.2, -.2, .5] if kind.endswith('negative') else [-.5, .2, .2]
        q, _ = np.linalg.qr(np.array([[1., 2, -1], [3, 1, 2], [2, -2, 3]]))
        h = q @ np.diag(spectrum) @ q.T
        if kind.startswith('near'):
            matrix = np.eye(3)
            h = np.diag([-1e-7, (-1 if kind.endswith('negative') else 1)*1e-13, 1e-7])
            rho, grad, hess = quadratic((9, 9, 9), matrix, h, origin=[-4]*3, offset=1e-4)
        else:
            rho, grad, hess = quadratic((7, 9, 11), matrix, h,
                                      linear=[.1, -.2, .3], origin=[-.4, .3, -.2])
    elif kind.startswith('negative'):
        rho, periodic = np.ones((17,)*3), (True,)*3
        rho[(8, 8, 8) if kind.endswith('center') else (0, 0, 0)] = -5e-12
        opts['negative_tolerance'] = 1e-10
        grad, hess = fd4(rho, matrix)
    elif kind.startswith('condition'):
        inverse = np.diag([1., 1., 1/999]) if kind.endswith('999') else np.array([[1.,31,0],[0,1,0],[0,0,1]])
        matrix = np.linalg.inv(inverse)
        rho = np.ones((5,)*3)
        grad, hess = np.zeros((*rho.shape, 3)), np.zeros((*rho.shape, 3, 3))
    elif kind == 'low-zero':
        rho, periodic = np.ones((9,)*3), (True,)*3
        rho[3,4,4], rho[5,4,4], rho[4,6,4], rho[4,4,6] = 0, .1, .2, np.nextafter(.2, np.inf)
        opts['rho_min'] = .2
        grad, hess = fd4(rho, matrix)
    elif kind == 'all-invalid':
        rho = np.full((5,)*3, 1e-10)
        grad, hess = np.zeros((*rho.shape, 3)), np.zeros((*rho.shape, 3, 3))
    elif kind == 'overflow':
        rho = np.ones((5,)*3)
        rho[2,2,2], rho[3,2,2] = 1e-250, 2
        opts['rho_min'] = 1e-260
    elif kind == 'large-finite':
        rho = finite_large_rdg_fixture()
    else:
        rho = np.full((5,)*3, 0x10, dtype=np.uint64).view(np.float64)
        opts['rho_min'] = float(np.array([1], dtype=np.uint64).view(np.float64)[0])
        if kind.endswith('constant'):
            matrix = np.diag([1e-308]*3)
        else:
            rho.view(np.uint64)[0,2,2], rho.view(np.uint64)[4,2,2] = 0x16, 0x0a
    case = guard_case(Evaluation(rho, matrix, periodic, mode))
    if kind == 'subnormal-constant':
        case.tile.j_inv[:] = np.diag([1e308]*3).ravel()
    with public.context(gpu_options(mode=mode, **opts), kind) as handle:
        rc, error = public.run(handle, case, kind)
    if kind == 'overflow':
        assert rc == NUMERIC_FAILURE, error
        flags = input_flags(rho, rho_min=opts['rho_min'])
        flags[2,2,2] |= 16
        assert_array_equal(case.flags, flags)
        assert_stats(case)
        assert case.stats.numeric_failures == 1
        for field in case.arrays()[:-1]:
            assert np.all(np.isnan(field))
        assert 'point 62' in error and 'non-finite eigenvalue or RDG' in error
    elif kind in ('large-finite', 'subnormal-constant', 'subnormal-gradient'):
        assert rc == OK, error
        expected = input_flags(rho, rho_min=opts.get('rho_min', 1e-8))
        valid = original.check_flags_stats(case, expected, lambda *args: None)
        assert np.count_nonzero(valid) == 1
        g, h = exact_center_derivatives(rho)
        if kind == 'subnormal-constant':
            assert_array_equal(case.grad[valid], 0)
            assert_array_equal(case.hess[valid], 0)
            assert_array_equal(case.rdg[valid], 0)
        else:
            assert_allclose(case.grad[2,2,2], [float(v) for v in g], atol=0, rtol=1e-10)
            assert_allclose(case.hess[2,2,2], [float(h[a][b]) for a,b in ((0,0),(1,1),(2,2),(0,1),(0,2),(1,2))], atol=1e-12, rtol=1e-10)
            reference = float(high_precision_rdg(float(rho[2,2,2]), g))
            assert_allclose(case.rdg[2,2,2], reference,
                            atol=0 if kind == 'subnormal-gradient' else 1e-11, rtol=1e-9)
            if kind == 'subnormal-gradient':
                assert int(case.grad[2,2,2,0].view(np.uint64)) == 1
                assert case.rdg[2,2,2] > 0
        assert case.flags[2,2,2] == 96
        assert_allclose(case.lambda2[2,2,2], 0, atol=1e-12, rtol=1e-10)
        if kind.startswith('subnormal'):
            assert case.lambda2[2,2,2] == case.signedrho[2,2,2] == 0
            assert_array_equal(case.hess[2,2,2], 0)
    else:
        assert rc == (INVALID_INPUT if kind == 'all-invalid' else OK), error
        assert_reference(case, rho, grad, hess, periodic, opts.get('rho_min', 1e-8))
        valid = (case.flags & 31) == 0
        if kind.startswith('negative'):
            assert np.count_nonzero(case.flags & 8) == 61
        if kind.startswith('near'):
            sign = -1 if kind.endswith('negative') else 1
            assert np.all(np.sign(case.lambda2[valid]) == sign)
            assert np.all(np.abs(case.lambda2[valid]) < 1e-12)
        if kind.startswith('constant'):
            assert np.all(case.flags[valid] & 32)


@pytest.mark.parametrize('periodic', [(True,)*3, (False,True,False)])
@pytest.mark.parametrize('location', [(0,0,0), (3,2,0)])
def test_negative_slab_seams(public, periodic, location):
    rho = np.ones((7,9,11)); rho[location] = -5e-12
    g, h = fd4(rho, J)
    expected = Evaluation(rho, J, periodic)
    with public.context(gpu_options(negative_tolerance=1e-10), 'negative-seam') as handle:
        run_reference(public, handle, expected, f'seam/{periodic}/{location}/full', rho, g, h, periodic)
        for start in (0,3,6):
            count = min(3,7-start)
            case = guard_case(slab(rho, start, count, periodic))
            rc, _ = public.run(handle, case, f'seam/{periodic}/{location}/s{start}')
            assembled = Evaluation(rho[start:start+count], J, periodic)
            for name in FIELDS:
                setattr(assembled, name, getattr(expected, name)[start:start+count])
            assert_same_fields(case, assembled)
            assert_stats(case)
            assert rc == (OK if case.stats.valid_points else INVALID_INPUT)


def test_cpu_selector_in_optional_library_and_gpu_tolerance(public):
    rho, grad, hess = periodic_fourier((7,9,11), J, [(.1,(1,2,1),.2)])
    for backend in (0, 1):
        case = guard_case(Evaluation(rho, J, (True,)*3))
        with public.context(options(backend=backend), f'selector-{backend}') as handle:
            run_reference(public, handle, case, f'selector-{backend}', rho, grad, hess, (True,)*3)


def test_interleaved_contexts_and_synchronous_return(public):
    rho,grad,hess=periodic_fourier((7,9,11),J,[(.1,(1,2,1),.2)])
    a=guard_case(Evaluation(np.full((5,7,9), .125)))
    b=guard_case(Evaluation(rho,J,(True,)*3,mode=FULL))
    with public.context(gpu_options(mode=FULL), 'B') as hb:
        with public.context(gpu_options(), 'A') as ha:
            run_reference(public,ha,a,'A-first',a.rho,
                          np.zeros((*a.rho.shape,3)),np.zeros((*a.rho.shape,3,3)),(False,)*3)
            run_reference(public,hb,b,'B-first',rho,grad,hess,(True,)*3)
            saved = byte_snapshot(b)
        # A is destroyed; B outputs remain complete after synchronous return.
        assert byte_snapshot(b) == saved
        b.rho[...] = 2*rho
        run_reference(public,hb,b,'B-after-A-free-new-input',2*rho,2*grad,2*hess,(True,)*3)
        assert_stats(a); assert_stats(b)


@pytest.mark.parametrize('finite,end', [(False,None),(True,None),(True,'left'),(True,'right')])
def test_huge_global_x_only_local_storage(public, finite, end):
    nx = 1 << 40
    rho = np.full((7,9,8), .125)
    case = slab(rho, 2, 1, (True,True,True), jacobian=np.eye(3))
    case.tile.global_n[0] = nx
    case.tile.periodic[0] = not finite
    case.tile.tile_start[0] = (1 << 39) + 3
    case.tile.input_origin[0] = case.tile.tile_start[0] - 2
    if end:
        case = slab(rho, 0 if end == 'left' else 6, 1, (False,True,True), jacobian=np.eye(3))
        case.tile.global_n[0] = nx
        if end == 'right':
            case.tile.tile_start[0] = nx-1
            case.tile.input_origin[0] = nx-3
    case = guard_case(case)
    with public.context(gpu_options(), 'huge-X') as handle:
        rc, error = public.run(handle, case, f'huge-X/{finite}/{end}')
    assert rc == (INVALID_INPUT if end else OK), error
    assert_stats(case)
    if end:
        assert np.all(case.flags == 1)
    else:
        assert np.all(case.flags == 96)
        assert_array_equal(case.rdg, 0)
