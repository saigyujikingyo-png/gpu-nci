"""Independent finite call identities/status/layout from the authored test plan.

No candidate output or receipt is read to construct this inventory.
"""
from itertools import product
import struct

COUNTS={'production-shared-library':295,'same-production-objects-test-only-bridge':55,
        'production-cpu-only':0}


def expected_calls(role):
    result={}
    def add(case_id,status=0,mode=1,backend=1,entry=True,diagnostics=None,
            shape=(5,7,9),input_shape=None):
        assert case_id not in result
        result[case_id]=dict(status=status,mode=mode,backend=backend,entry=entry,
            diagnostics=(mode==1,mode==1) if diagnostics is None else diagnostics,
            shape=list(shape),input_shape=list(shape if input_shape is None else input_shape))
    def partition(case_id,nx,ny,nz,start,count,periodic,status,mode=1):
        nin=count+4 if periodic[0] else min(nx,start+count+2)-max(0,start-2)
        add(case_id,status,mode=mode,shape=(count,ny,nz),input_shape=(nin,ny,nz))
    if role=='production-shared-library':
        for mode in (0,1):
            for periodic in product((False,True),repeat=3):
                label=f'matrix/{mode}/{"".join(str(int(p)) for p in periodic)}'
                add(label+'/full',mode=mode,shape=(7,9,11))
                for block in (1,3):
                    for start in range(0,7,block):
                        count=min(block,7-start)
                        empty=not periodic[0] and not any(2<=x<5 for x in range(start,start+count))
                        partition(f'{label}/B{block}/s{start}',7,9,11,start,count,periodic,3 if empty else 0,mode)
        for periodic in ((False,)*3,(True,)*3):
            add(f'nx5/{periodic}/full')
            for block in (1,3):
                for start in range(0,5,block):
                    count=min(block,5-start)
                    empty=not periodic[0] and 2 not in range(start,start+count)
                    partition(f'nx5/{periodic}/B{block}/s{start}',5,7,9,start,count,periodic,3 if empty else 0)
        special=['constant-full','constant-diagnostic']+[
            f'quadratic-{hand}-{sign}' for hand in (0,1) for sign in (0,1)]+[
            'negative-center','negative-corner','near-positive','near-negative',
            'repeat-negative','repeat-positive','condition-999','condition-skew',
            'low-zero','all-invalid','overflow','large-finite','subnormal-constant','subnormal-gradient']
        for kind in special:
            shape=(17,)*3 if kind.startswith('negative') else (9,)*3 if kind.startswith('near') or kind=='low-zero' else (
                (7,9,11) if kind.startswith(('constant','quadratic','repeat')) else (5,)*3)
            add(kind,4 if kind=='overflow' else 3 if kind=='all-invalid' else 0,
                mode=0 if kind=='constant-full' else 1,shape=shape)
        for periodic in ((True,)*3,(False,True,False)):
            for location in ((0,0,0),(3,2,0)):
                label=f'seam/{periodic}/{location}'
                add(label+'/full',shape=(7,9,11))
                for start in (0,3,6):
                    partition(f'{label}/s{start}',7,9,11,start,min(3,7-start),periodic,3 if start==6 and not periodic[0] else 0)
        add('selector-0',backend=0,entry=False,shape=(7,9,11));add('selector-1',shape=(7,9,11))
        add('A-first');add('B-first',mode=0,shape=(7,9,11));add('B-after-A-free-new-input',mode=0,shape=(7,9,11))
        for finite,end in ((False,None),(True,None),(True,'left'),(True,'right')):
            add(f'huge-X/{finite}/{end}',3 if end else 0,shape=(1,9,8),input_shape=(3 if end else 5,9,8))
        mutations=['tile-version','tile-bytes','tile-reserved','capacity-rho','capacity-field',
            'capacity-flags','capacity-grad','capacity-hess','j-singular','j-illconditioned','j-nan',
            'j-inf','dimension','periodic','stride','y-partial','missing-halo','wrong-origin',
            'nan-rho','inf-rho','negative-rho','halo-nan','halo-negative','mapped-object-limit']
        unsupported={'stride','y-partial','missing-halo','wrong-origin','mapped-object-limit'}
        bad_density={'nan-rho','inf-rho','negative-rho','halo-nan','halo-negative'}
        for kind in mutations:
            is_slab=kind in ('missing-halo','wrong-origin','halo-nan','halo-negative')
            add('reject/'+kind,2 if kind in unsupported else 3 if kind in bad_density else 1,entry=False,
                shape=(1,9,11) if is_slab else (5,7,9),input_shape=(5,9,11) if is_slab else None)
        for index in range(11):add(f'null/{index}',1,entry=False)
        for name in ('rdg','signedrho','lambda2','grad','hess','flags','stats','errbuf'):
            add('alias/'+name,1,entry=False,shape=(1,9,11),input_shape=(5,9,11))
        for kind in ('start_min','count_min','origin_min','shape_min','global_overflow',
                     'global_byte_limit','input_overflow','halo_overflow'):
            ny=8 if kind in ('global_overflow','input_overflow') else 5
            add('extreme/'+kind,2 if kind=='origin_min' else 1,entry=False,shape=(1,ny,5),input_shape=(5,ny,5))
        add('mode/full-grad',1,mode=0,entry=False,diagnostics=(True,True))
        add('mode/full-capacity',1,mode=0,entry=False,diagnostics=(False,False))
        add('mode/diagnostic-grad',1,entry=False,diagnostics=(False,True))
        add('mode/diagnostic-hess',1,entry=False,diagnostics=(True,False))
        for kind in ('at-negative-tolerance','just-below-negative-tolerance','negative-zero'):
            rejected=kind=='just-below-negative-tolerance'
            add(kind,3 if rejected else 0,entry=not rejected,shape=(7,9,11))
    elif role=='same-production-objects-test-only-bridge':
        for failure in range(1,19):
            add(f'fail-{failure}',5);add(f'finite-recovery-{failure}')
        for corruption in (1,2):
            add(f'corruption-{corruption}',6);add(f'corruption-{corruption}-finite-recovery')
        add('control/preflight-rejected',3,entry=False,shape=(1,9,11),input_shape=(5,9,11))
        add('control/pending-failure-consumed',5);add('control/next-frozen-normal')
        for mode in (0,1):
            for ordinal,shape in enumerate(((5,5,5),(7,9,11),(5,5,5)),1):
                add(f'storage/{mode}/{shape}/{ordinal}',mode=mode,shape=shape)
        add('numeric-failure',4,shape=(5,)*3);add('all-invalid',3,shape=(5,)*3)
        add('isolation/B-before',mode=0,shape=(7,9,11));add('isolation/A-failure',5,shape=(5,)*3);add('isolation/B-after',mode=0,shape=(7,9,11))
        add('huge-device-failure',4,shape=(1,5,5),input_shape=(5,5,5))
    elif role!='production-cpu-only':
        raise ValueError('unrecognized receipt role')
    assert len(result)==COUNTS[role]
    return result


def expected_rejected_creates(role):
    if role=='production-cpu-only':return {'cpu-only-openacc-selector':6}
    if role=='same-production-objects-test-only-bridge':return {}
    if role!='production-shared-library':raise ValueError('unrecognized receipt role')
    values=[('abi_version',0),('struct_bytes',41),('reserved',1),('backend',99),
        ('output_mode',99),('omp_threads',0),('omp_threads',17),('rho_min',0),
        ('rho_min',float('nan')),('rho_min',float('inf')),('negative_tolerance',-1),
        ('negative_tolerance',float('nan'))]
    return {**{f'option/{field}/{value}':1 for field,value in values},'cuda-unavailable':6}


def options_blob(**updates):
    """Independent little-endian ABI-v1 bytes, including exact FP64 payloads.

    QNAN is an explicit input bit pattern, not an is-NaN equivalence class.
    The finite package targets the frozen Linux x86-64 ABI.
    """
    fields=dict(abi_version=1,struct_bytes=40,backend=1,output_mode=1,
                omp_threads=1,reserved=0,rho_min=1e-8,negative_tolerance=0.)
    assert set(updates)<=set(fields)
    fields.update(updates)
    result=struct.pack('<6i',*(fields[name] for name in ('abi_version','struct_bytes',
        'backend','output_mode','omp_threads','reserved')))
    for name in ('rho_min','negative_tolerance'):
        value=fields[name]
        result+=struct.pack('<Q',0x7ff8000000000000) if value=='QNAN' else struct.pack('<d',value)
    assert len(result)==40
    return result


def expected_options_for_call(case_id,spec):
    """Thresholds are fixed by case purpose, never inferred from a receipt."""
    updates=dict(backend=spec['backend'],output_mode=spec['mode'])
    if case_id in ('overflow','numeric-failure','huge-device-failure'):
        updates['rho_min']=1e-260
    elif case_id=='low-zero':updates['rho_min']=.2
    elif case_id in ('subnormal-constant','subnormal-gradient'):
        updates['rho_min']=struct.unpack('<d',struct.pack('<Q',1))[0]
    if case_id in ('negative-center','negative-corner') or case_id.startswith('seam/'):
        updates['negative_tolerance']=1e-10
    elif case_id in ('at-negative-tolerance','just-below-negative-tolerance','negative-zero'):
        updates['negative_tolerance']=1e-6
    return options_blob(**updates)


def expected_create_options(role):
    """Allowed full option blobs for each independent source context label.

    A repeated label such as mode/storage may allow FULL or DIAGNOSTIC. Each
    later evaluation is additionally bound to its single exact expected blob.
    """
    result={}
    for name,spec in expected_calls(role).items():
        if role=='production-shared-library':
            if name.startswith('matrix/'):context='/'.join(name.split('/')[:3])
            elif name.startswith('nx5/'):context='nx5'
            elif name.startswith('seam/'):context='negative-seam'
            elif name in ('A-first','B-first','B-after-A-free-new-input'):
                context='A' if name=='A-first' else 'B'
            elif name.startswith('huge-X/'):context='huge-X'
            elif name.startswith('reject/'):context=name.split('/')[1]
            elif name.startswith(('null/','alias/','extreme/','mode/')):context=name.split('/')[0]
            else:context=name
        else:
            if name.startswith('finite-recovery-'):context='fail-'+name.removeprefix('finite-recovery-')
            elif name.startswith('corruption-'):context='corruption'
            elif name.startswith('control/'):context='control-preflight'
            elif name.startswith('storage/'):context='no-retained-capacity'
            elif name.startswith('isolation/'):
                context='isolated-'+name.split('/')[1][0]
            else:context=name
        result.setdefault(context,set()).add(expected_options_for_call(name,spec))
    if role=='same-production-objects-test-only-bridge':
        result['cpu-no-device']={options_blob(backend=0)}
    return result


def expected_rejected_options(role):
    result={}
    for case_id in expected_rejected_creates(role):
        if case_id=='cuda-unavailable':result[case_id]=options_blob(backend=2)
        elif case_id=='cpu-only-openacc-selector':result[case_id]=options_blob()
        else:
            _,field,text=case_id.split('/')
            value='QNAN' if text=='nan' else float('inf') if text=='inf' else int(text)
            result[case_id]=options_blob(**{field:value})
    return result
