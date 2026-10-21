"""No-write public preflight, byte counts and selector failures; no optional skips."""
import ctypes as ct
import numpy as np
import pytest
from .support import guard_case, byte_snapshot, assert_unchanged
from .test_public import gpu_options
from reference.abi import (Evaluation, options, OK, INVALID_ARGUMENT, UNSUPPORTED,
                           INVALID_INPUT, BACKEND_UNAVAILABLE, ptr, U8_P)
from slab_cases import slab, extreme_case
from reference.fields import fd4
from slab_cases import assert_reference

BAD_OPTIONS = [('abi_version',0), ('struct_bytes',41), ('reserved',1),
    ('backend',99), ('output_mode',99), ('omp_threads',0), ('omp_threads',17),
    ('rho_min',0), ('rho_min',float('nan')), ('rho_min',float('inf')),
    ('negative_tolerance',-1), ('negative_tolerance',float('nan'))]


@pytest.mark.parametrize('field,value', BAD_OPTIONS)
def test_invalid_create_is_null_and_errbuf_bounded(public, field, value):
    opts, handle = gpu_options(), ct.c_void_p(0x1234)
    setattr(opts, field, value)
    before = bytes(opts)
    storage = (ct.c_char*16)(*([b'X']*16))
    error = ct.cast(ct.byref(storage,4), ct.POINTER(ct.c_char))
    rc = public.raw.create(ct.byref(opts),ct.byref(handle),error,4)
    public.retain('create-rejected', f'option/{field}/{value}', rc, '',
                  dict(options=before, errbuf=bytes(storage)))
    assert rc == INVALID_ARGUMENT and handle.value is None
    assert bytes(opts) == before
    assert bytes(storage)[:4] == b'XXXX'
    assert bytes(storage)[8:] == b'X'*8 and 0 in bytes(storage)[4:8]


def test_cuda_selector_never_falls_back(public):
    opts, handle, error = options(backend=2), ct.c_void_p(0x1234), ct.create_string_buffer(128)
    rc = public.raw.create(ct.byref(opts), ct.byref(handle), error, len(error))
    public.retain('create-rejected', 'cuda-unavailable', rc, error.value.decode(), dict(options=bytes(opts)))
    assert rc == BACKEND_UNAVAILABLE and handle.value is None


MUTATIONS = ['tile-version','tile-bytes','tile-reserved','capacity-rho','capacity-field',
    'capacity-flags','capacity-grad','capacity-hess','j-singular','j-illconditioned','j-nan',
    'j-inf','dimension','periodic','stride','y-partial','missing-halo','wrong-origin',
    'nan-rho','inf-rho','negative-rho','halo-nan','halo-negative','mapped-object-limit']


def mutated(kind):
    case = Evaluation(np.ones((5,7,9)))
    expected = INVALID_ARGUMENT
    if kind == 'tile-version': case.tile.abi_version = 2
    elif kind == 'tile-bytes': case.tile.struct_bytes = 281
    elif kind == 'tile-reserved': case.tile.reserved = 1
    elif kind.startswith('capacity'):
        name = dict(rho='rho',field='field',flags='flags',grad='grad',hess='hess')[kind.split('-')[1]]+'_capacity'
        setattr(case.tile,name,getattr(case.tile,name)-1)
    elif kind == 'j-singular': case.tile.j_inv[:] = [0]*9
    elif kind == 'j-illconditioned': case.tile.j_inv[:] = np.diag([1,1,1001]).ravel()
    elif kind == 'j-nan': case.tile.j_inv[0] = float('nan')
    elif kind == 'j-inf': case.tile.j_inv[0] = float('inf')
    elif kind == 'dimension': case.tile.global_n[0] = case.tile.tile_count[0] = case.tile.input_shape[0] = 4
    elif kind == 'periodic': case.tile.periodic[0] = 2
    elif kind == 'stride': case.tile.input_strides[2] = 2; expected = UNSUPPORTED
    elif kind == 'y-partial': case.tile.tile_count[1] = 6; expected = UNSUPPORTED
    elif kind in ('missing-halo','wrong-origin'):
        case = slab(np.ones((7,9,11)),3,1,(True,)*3)
        if kind == 'missing-halo': case.tile.input_shape[0] -= 1
        else: case.tile.input_origin[0] += 1
        expected = UNSUPPORTED
    elif kind in ('nan-rho','inf-rho','negative-rho'):
        case.rho[0,0,0] = dict(**{'nan-rho':float('nan'),'inf-rho':float('inf'),'negative-rho':-1e-9})[kind]
        expected = INVALID_INPUT
    elif kind in ('halo-nan','halo-negative'):
        case = slab(np.ones((7,9,11)),3,1,(True,)*3)
        case.rho[-1,-1,-1] = float('nan') if kind == 'halo-nan' else -1e-9
        expected = INVALID_INPUT
    elif kind == 'mapped-object-limit':
        shape = (5,5,1 << 24)  # backing arrays remain 315 points; plan must reject before rho read
        case.tile.global_n[:] = case.tile.tile_count[:] = case.tile.input_shape[:] = shape
        case.tile.input_strides[:] = (shape[1]*shape[2],shape[2],1)
        count = 25*(1 << 24)
        case.tile.rho_capacity = case.tile.field_capacity = case.tile.flags_capacity = count
        case.tile.grad_capacity, case.tile.hess_capacity = 3*count,6*count
        expected = UNSUPPORTED
    else: raise ValueError(kind)
    return guard_case(case), expected


@pytest.mark.parametrize('kind', MUTATIONS)
def test_rejected_input_is_bytewise_atomic(public, kind):
    case, expected = mutated(kind)
    ct.memset(ct.byref(case.stats),0x3C,88)
    before = byte_snapshot(case)
    with public.context(gpu_options(),kind) as handle:
        rc, error = public.run(handle,case,'reject/'+kind)
    assert rc == expected, error
    assert_unchanged(case,before)


@pytest.mark.parametrize('index', [0,1,2,3,4,5,6,7,8,9,10])
def test_null_arguments_atomic(public,index):
    case = guard_case(Evaluation(np.ones((5,7,9))))
    ct.memset(ct.byref(case.stats),0x3C,88)
    before = byte_snapshot(case)
    with public.context(gpu_options(),'null') as handle:
        rc,_ = public.run(handle,case,f'null/{index}',{index:None})
    assert rc == INVALID_ARGUMENT
    assert_unchanged(case,before)


@pytest.mark.parametrize('name', ['rdg','signedrho','lambda2','grad','hess','flags','stats','errbuf'])
def test_alias_at_last_halo_element_atomic(public,name):
    case = slab(np.ones((7,9,11)),3,1,(True,)*3)
    storage = np.ones(case.rho.size + 6*case.flags.size+20)
    case.rho = storage[:case.rho.size].reshape(case.rho.shape)
    address = storage.ctypes.data + case.rho.nbytes - 8
    mapping = {'rdg':3,'signedrho':4,'lambda2':5,'grad':6,'hess':7,'flags':8,'stats':9,'errbuf':10}
    if name in ('flags','errbuf'):
        pointer = ct.cast(address, U8_P if name=='flags' else ct.POINTER(ct.c_char))
    elif name == 'stats': pointer = ct.cast(address,ct.POINTER(type(case.stats)))
    else: pointer = ct.cast(address,ct.POINTER(ct.c_double))
    before, backing = byte_snapshot(case), storage.tobytes()
    with public.context(gpu_options(),'alias') as handle:
        rc,_ = public.run(handle,case,'alias/'+name,{mapping[name]:pointer})
    assert rc == INVALID_ARGUMENT
    assert_unchanged(case,before)
    assert storage.tobytes() == backing


@pytest.mark.parametrize('kind',['start_min','count_min','origin_min','shape_min',
    'global_overflow','global_byte_limit','input_overflow','halo_overflow'])
def test_extreme_extent_atomic(public,kind):
    case = guard_case(extreme_case(kind))
    before = byte_snapshot(case)
    with public.context(gpu_options(),'extreme') as handle:
        rc,_ = public.run(handle,case,'extreme/'+kind)
    assert rc == (UNSUPPORTED if kind=='origin_min' else INVALID_ARGUMENT)
    assert_unchanged(case,before)


@pytest.mark.parametrize('kind',['full-grad','full-capacity','diagnostic-grad','diagnostic-hess'])
def test_output_mode_rules(public,kind):
    full = kind.startswith('full')
    case = guard_case(Evaluation(np.ones((5,7,9))))
    if kind=='full-capacity': case.grad=case.hess=None
    if kind=='diagnostic-grad': case.grad=None
    if kind=='diagnostic-hess': case.hess=None
    before=byte_snapshot(case)
    with public.context(gpu_options(mode=0 if full else 1),'mode') as handle:
        rc,_=public.run(handle,case,'mode/'+kind)
    assert rc==INVALID_ARGUMENT
    assert_unchanged(case,before)


@pytest.mark.parametrize('kind',['at-negative-tolerance','just-below-negative-tolerance','negative-zero'])
def test_exact_density_preflight_boundaries(public,kind):
    rho=np.ones((7,9,11))
    rho[3,4,5]=dict(**{'at-negative-tolerance':-1e-6,
                       'just-below-negative-tolerance':np.nextafter(-1e-6,-np.inf),
                       'negative-zero':-0.0})[kind]
    case=guard_case(Evaluation(rho,periodic=(True,)*3))
    before=byte_snapshot(case)
    with public.context(gpu_options(negative_tolerance=1e-6),kind) as handle:
        rc,error=public.run(handle,case,kind)
    if kind=='just-below-negative-tolerance':
        assert rc==INVALID_INPUT,error
        assert_unchanged(case,before)
    else:
        assert rc==OK,error
        grad,hess=fd4(rho,np.eye(3))
        assert_reference(case,rho,grad,hess,(True,)*3)
