"""Same production object public calls, controlled only through private Fortran hooks."""
import ctypes as ct
import numpy as np
import pytest
from .support import guard_case,byte_snapshot,assert_unchanged
from .private import validate_ledger,array_sizes
from .test_public import gpu_options
from .test_rejections import mutated
from reference.abi import (Evaluation,options,FULL,DIAGNOSTIC,OK,INVALID_ARGUMENT,
                           INVALID_INPUT,NUMERIC_FAILURE,ALLOCATION_FAILURE,BACKEND_UNAVAILABLE)
from slab_cases import assert_stats,slab


def observed(bridge,handle,case,status,failure=0,ordinal=None):
    rc,values,rows,snapshot=bridge.hooks.observe(bridge,handle)
    assert rc==0
    validate_ledger(values,rows,array_sizes(case),status,failure)
    if ordinal is not None: assert values['call_ordinal']==ordinal
    return values,snapshot


@pytest.mark.parametrize('failure',range(1,19))
def test_every_acquisition_unwinds_then_recovers(bridge,failure):
    case=guard_case(Evaluation(np.ones((5,7,9))))
    before=byte_snapshot(case)
    with bridge.context(gpu_options(),f'fail-{failure}') as handle:
        assert bridge.hooks.configure(bridge,handle,failure)==0
        assert bridge.run(handle,case,f'fail-{failure}')[0]==ALLOCATION_FAILURE
        assert_unchanged(case,before)
        observed(bridge,handle,case,ALLOCATION_FAILURE,failure,1)
        # Consumed control, no second configure needed or allowed as a hidden retry.
        assert bridge.run(handle,case,f'finite-recovery-{failure}')[0]==OK
        values,_=observed(bridge,handle,case,OK,ordinal=2)
        assert values['verified_markers']==case.flags.size
        assert values['first_failure_global_index']==-1
        assert_stats(case)


@pytest.mark.parametrize('corruption',[1,2])
def test_downloaded_marker_or_status_rejected_without_commit(bridge,corruption):
    case=guard_case(Evaluation(np.ones((5,7,9))))
    before=byte_snapshot(case)
    with bridge.context(gpu_options(),'corruption') as handle:
        assert bridge.hooks.configure(bridge,handle,corruption=corruption)==0
        assert bridge.run(handle,case,f'corruption-{corruption}')[0]==BACKEND_UNAVAILABLE
        assert_unchanged(case,before)
        values,_=observed(bridge,handle,case,BACKEND_UNAVAILABLE,ordinal=1)
        assert values['verified_markers']==case.flags.size-(corruption==1)
        assert bridge.run(handle,case,f'corruption-{corruption}-finite-recovery')[0]==OK
        observed(bridge,handle,case,OK,ordinal=2)
        assert_stats(case)


def test_controls_and_preflight_do_not_change_observations(bridge):
    with bridge.context(gpu_options(),'control-preflight') as handle:
        rc,v,rows,initial=bridge.hooks.observe(bridge,handle)
        assert rc==0 and not rows
        expected=[0]*24;expected[0]=1;expected[18]=-1
        assert v==dict(zip(v.keys(),expected))
        assert bridge.hooks.configure(bridge,handle,failure=1)==0
        for failure,corruption in [(-1,0),(19,0),(0,-1),(0,3),(1,1)]:
            assert bridge.hooks.configure(bridge,handle,failure,corruption)==INVALID_ARGUMENT
            assert bridge.hooks.observe(bridge,handle)[3]==initial
        # The common-preflight rejection preserves pending injection and complete snapshot.
        case,_=mutated('halo-nan');before=byte_snapshot(case)
        assert bridge.run(handle,case,'control/preflight-rejected')[0]==INVALID_INPUT
        assert_unchanged(case,before)
        assert bridge.hooks.observe(bridge,handle)[3]==initial
        case=guard_case(Evaluation(np.ones((5,7,9))))
        before=byte_snapshot(case)
        assert bridge.run(handle,case,'control/pending-failure-consumed')[0]==ALLOCATION_FAILURE
        assert_unchanged(case,before)
        observed(bridge,handle,case,ALLOCATION_FAILURE,1,1)
        assert bridge.run(handle,case,'control/next-frozen-normal')[0]==OK
        observed(bridge,handle,case,OK,ordinal=2)


def test_invalid_private_handles_do_not_touch_device(bridge):
    for handle in (None,):
        assert bridge.hooks.configure(bridge,handle)==INVALID_ARGUMENT
        rc,v,rows,_=bridge.hooks.observe(bridge,handle)
        assert rc==INVALID_ARGUMENT and not rows and all(x==0 for x in v.values())
    with bridge.context(options(backend=0),'cpu-no-device') as handle:
        assert bridge.hooks.configure(bridge,handle)==INVALID_ARGUMENT
        rc,v,rows,_=bridge.hooks.observe(bridge,handle)
        assert rc==INVALID_ARGUMENT and not rows and all(x==0 for x in v.values())


@pytest.mark.parametrize('mode',[FULL,DIAGNOSTIC])
def test_per_call_storage_no_retained_capacity(bridge,mode):
    with bridge.context(gpu_options(mode=mode),'no-retained-capacity') as handle:
        for ordinal,shape in enumerate(((5,5,5),(7,9,11),(5,5,5)),1):
            case=guard_case(Evaluation(np.ones(shape),mode=mode))
            assert bridge.run(handle,case,f'storage/{mode}/{shape}/{ordinal}')[0]==OK
            values,_=observed(bridge,handle,case,OK,ordinal=ordinal)
            assert values['verified_markers']==case.flags.size
            assert_stats(case)


@pytest.mark.parametrize('kind',['numeric-failure','all-invalid'])
def test_completed_error_commits_and_keeps_device_diagnosis(bridge,kind):
    rho=np.ones((5,5,5)) if kind=='numeric-failure' else np.full((5,5,5),1e-10)
    if kind=='numeric-failure': rho[2,2,2],rho[3,2,2]=1e-250,2
    case=guard_case(Evaluation(rho))
    wanted=NUMERIC_FAILURE if kind=='numeric-failure' else INVALID_INPUT
    opts=gpu_options(rho_min=1e-260) if kind=='numeric-failure' else gpu_options()
    with bridge.context(opts,kind) as handle:
        status,error=bridge.run(handle,case,kind)
        assert status==wanted
        values,_=observed(bridge,handle,case,wanted,ordinal=1)
    assert values['verified_markers']==125
    assert_stats(case)
    for name in ('rdg','signedrho','lambda2','grad','hess'):
        # Contract requires canonical QNAN, not the distinctive staging poison.
        assert np.all(getattr(case,name).view(np.uint64)==0x7ff8000000000000)
    if kind=='numeric-failure':
        assert (values['first_failure_global_index'],values['first_failure_status'])==(62,6)
        assert 0<=values['first_failure_nrot']<=30
        assert 'point 62' in error and 'non-finite eigenvalue or RDG' in error
        assert case.stats.numeric_failures==1
    else:
        assert (values['first_failure_global_index'],values['first_failure_status'],
                values['first_failure_nrot'])==(-1,0,0)


def test_pending_failure_is_per_context(bridge):
    a=guard_case(Evaluation(np.ones((5,5,5))))
    b=guard_case(Evaluation(np.ones((7,9,11)),mode=FULL))
    with bridge.context(gpu_options(),'isolated-A') as ha:
        with bridge.context(gpu_options(mode=FULL),'isolated-B') as hb:
            assert bridge.hooks.configure(bridge,ha,failure=9)==0
            assert bridge.run(hb,b,'isolation/B-before')[0]==OK
            observed(bridge,hb,b,OK,ordinal=1)
            before=byte_snapshot(a)
            assert bridge.run(ha,a,'isolation/A-failure')[0]==ALLOCATION_FAILURE
            assert_unchanged(a,before)
            observed(bridge,ha,a,ALLOCATION_FAILURE,9,1)
            assert bridge.run(hb,b,'isolation/B-after')[0]==OK
            observed(bridge,hb,b,OK,ordinal=2)


def test_device_failure_index_uses_huge_global_x(bridge):
    rho=np.ones((5,5,5));rho[2,2,2],rho[3,2,2]=1e-250,2
    case=slab(rho,2,1,(True,False,False),jacobian=np.eye(3))
    start=(1<<39)+3
    case.tile.global_n[0]=1<<40
    case.tile.tile_start[0]=start;case.tile.input_origin[0]=start-2
    case=guard_case(case)
    with bridge.context(gpu_options(rho_min=1e-260),'huge-device-failure') as handle:
        status,error=bridge.run(handle,case,'huge-device-failure')
        assert status==NUMERIC_FAILURE,error
        values,_=observed(bridge,handle,case,NUMERIC_FAILURE,ordinal=1)
    global_index=start*25+12
    assert values['first_failure_global_index']==global_index
    assert values['first_failure_status']==6
    assert 0<=values['first_failure_nrot']<=30
    assert f'point {global_index}' in error
    assert_stats(case)
