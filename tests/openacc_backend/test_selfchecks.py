"""Pure invented-ledger and fixture checks. Never loads a candidate library."""
import ctypes as ct
import importlib.util
import json
import hashlib
import struct
from types import SimpleNamespace
from pathlib import Path

import numpy as np
import pytest
from .support import (guard_case,check_guards,byte_snapshot,assert_unchanged,Recorder,json_new,
                      fingerprint,assert_subtau_uncertain)
from .private import VALUE_NAMES,array_sizes,validate_ledger
from .test_rejections import mutated,MUTATIONS,BAD_OPTIONS
from .verify_threads import strict_json,parse
from .verify_receipts import group,observation,initial_observation,KIND_COUNTS
from .expectations import (expected_calls,expected_rejected_creates,expected_create_options,
                           expected_rejected_options,expected_options_for_call,options_blob)
from reference.abi import Evaluation,options,Options,Tile,Stats
from reference.fields import input_flags
from reference.fields import quadratic,nci,pack_hessian
from slab_cases import slab


def invented_ledger(failure=0,mode=1):
    """Static action schedule from the contract, unrelated to candidate output."""
    case=Evaluation(np.ones((5,7,9)),mode=mode);sizes=array_sizes(case)
    values=dict.fromkeys(VALUE_NAMES,0)
    values.update(schema_version=1,call_ordinal=1,planned_host=sum(sizes.values()),
        planned_device=sum(sizes.values()),output_points=315,
        backend_status=5 if failure else 0,acquisition_attempts=failure or 18,
        first_failure_global_index=-1,verified_markers=0 if failure else 315)
    h=set();d=set();maps=set();rows=[]
    def add(action,buffer=0):
        if action==1:h.add(buffer)
        if action==2:d.add(buffer)
        if action==3:maps.add(buffer)
        if action==7:maps.remove(buffer)
        if action==8:d.remove(buffer)
        if action in (9,11):h.remove(buffer)
        lh=sum(sizes[x] for x in h);ld=sum(sizes[x] for x in d)
        rows.append([len(rows)+1,action,buffer,0 if action==5 else sizes[buffer],lh,ld])
        values['peak_host']=max(values['peak_host'],lh)
        values['peak_device']=max(values['peak_device'],ld)
        values['peak_maps']=max(values['peak_maps'],len(maps))
    for k in range(1,10):
        if failure==k:break
        add(1,k)
    if not failure or failure>9:
        for k in range(1,10):
            if failure==k+9:break
            add(2,k);add(3,k)
    if not failure:
        for k in range(1,10):add(4,k)
        add(5)
        for k in range(5,10):add(6,k)
        values.update(kernels=1,upload_count=9,upload_bytes=sum(sizes.values()),
                      download_count=5,download_bytes=sum(sizes[k] for k in range(5,10)))
    for k in sorted(d,reverse=True):add(7,k);add(8,k)
    for k in sorted(h,reverse=True):
        if failure or k not in (5,6):add(9,k)
    if not failure:
        add(10,5);add(10,6)
        add(11,6);add(11,5)
    values['event_count']=len(rows)
    return values,rows,sizes


@pytest.mark.parametrize('mode',[0,1])
@pytest.mark.parametrize('failure',range(19))
def test_model_accepts_contract_schedules(mode,failure):
    values,rows,sizes=invented_ledger(failure,mode)
    validate_ledger(values,rows,sizes,5 if failure else 0,failure)


@pytest.mark.parametrize('mutation',['sequence','bytes','live','peak','status','count',
                                    'missing-call-free','foreign-map','marker-total'])
def test_model_rejects_malformed_ledger(mutation):
    values,rows,sizes=invented_ledger()
    if mutation=='sequence':rows[0][0]=2
    elif mutation=='bytes':rows[0][3]+=1
    elif mutation=='live':rows[0][4]=0
    elif mutation=='peak':values['peak_device']+=1
    elif mutation=='status':values['backend_status']=4
    elif mutation=='count':values['upload_count']-=1
    elif mutation=='missing-call-free':rows.pop();values['event_count']-=1
    elif mutation=='foreign-map':rows[0][1]=3
    elif mutation=='marker-total':values['final_maps']=1
    with pytest.raises(AssertionError):validate_ledger(values,rows,sizes,0)


def test_guards_and_snapshot_detect_one_byte_change():
    case=guard_case(Evaluation(np.ones((5,5,5))))
    before=byte_snapshot(case);check_guards(case);assert_unchanged(case,before)
    case._guards[0][0]=0
    with pytest.raises(AssertionError):check_guards(case)
    case.stats.total_points=1
    with pytest.raises(AssertionError):assert_unchanged(case,before)


def test_public_layout_and_cpu_default_unchanged():
    assert [ct.sizeof(x) for x in (Options,Tile,Stats)]==[40,280,88]
    assert options().backend==0 and options(backend=1).backend==1


@pytest.mark.parametrize('kind',MUTATIONS)
def test_rejection_fixtures_only_allocate_tiny_backing(kind):
    case,status=mutated(kind)
    assert case.rho.size<=17**3 and case.flags.size<=17**3
    assert status in (1,2,3)
    check_guards(case)


def test_nx5_periodic_duplicate_input_planes_and_accounting():
    rho=np.arange(5*7*9,dtype=float).reshape(5,7,9)
    case=slab(rho,0,1,(True,)*3)
    assert np.array_equal(case.rho[:,0,0],rho[[3,4,0,1,2],0,0])
    sizes=array_sizes(case)
    assert sum(sizes.values())==8*case.rho.size+40*(1+7+9)+109*case.flags.size


@pytest.mark.parametrize('data',['{"a":1,"a":2}','{"a":NaN}','{"a":Infinity}'])
def test_strict_json_rejects_ambiguous_documents(data):
    with pytest.raises(ValueError):strict_json(data)


@pytest.mark.parametrize('data',[b'',b'{}\n',b'{}\n'*24,b'x'*(4*1024*1024+1)])
def test_thread_parser_rejects_incomplete_or_oversize(data):
    with pytest.raises((ValueError,AssertionError,KeyError)):parse(data)


def invented_thread_stdout():
    rows=[dict(kind='library',path='/invented/not-an-executable',main_thread=101,evaluations=6)]
    sequence=0
    def event(phase,job,repeat,kind):
        nonlocal sequence
        sequence+=1
        thread=101 if phase=='migration-main-thread' else 104 if phase=='migration-new-thread' else 102+job
        rows.append(dict(kind=kind,phase=phase,job=job,repeat=repeat,thread=thread,
                         sequence=sequence,monotonic_ns=sequence*100))
    def call(phase,job,repeat):
        shape=(7,5,9) if job else (5,7,9)
        if job:
            rho=np.full(shape,.125);g=np.zeros((*shape,3));h=np.zeros((*shape,3,3))
        else:
            rho,g,h=quadratic(shape,np.eye(3),np.diag([-.5,-.25,.75]),
                               linear=[.125,-.25,.5],origin=[-2]*3,offset=20)
        flags=input_flags(rho);valid=flags==0
        flags[valid]|=64+(32 if job else 0)
        rdg,srho,eigen=nci(rho[valid],g[valid],h[valid])
        arrays=[]
        for source,components in [(rdg,1),(srho,1),(eigen,1)]+([] if job else [(g[valid],3),(pack_hessian(h)[valid],6)]):
            array=np.full((*shape,components),np.nan) if components>1 else np.full(shape,np.nan)
            array[valid]=source
            arrays.append(array)
        stats=[315,int(np.count_nonzero(valid)),int(np.count_nonzero(~valid)),0]
        stats += [int(np.count_nonzero(flags & (1<<b))) for b in range(7)]
        thread=101 if phase=='migration-main-thread' else 104 if phase=='migration-new-thread' else 102+job
        rows.append(dict(kind='call',phase=phase,job=job,repeat=repeat,thread=thread,status=0,check=0,
            diagnostic=int(job==0),shape=list(shape),
            fields=[a.view(np.uint64).astype('>u8').tobytes().hex() for a in arrays],
            flags=flags.tobytes().hex(),stats=stats))
    for repeat in (0,1):
        for job in (0,1):event('concurrent',job,repeat,'ready')
        for job in (0,1):event('concurrent',job,repeat,'begin')
        for job in (0,1):
            event('concurrent',job,repeat,'end');call('concurrent',job,repeat)
    for phase in ('migration-new-thread','migration-main-thread'):
        event(phase,0,0,'begin');event(phase,0,0,'end');call(phase,0,0)
    rows.append(dict(kind='end',evaluations=6,live_contexts=0))
    return rows


def test_compare_only_thread_oracle_accepts_independent_analytic_payload():
    rows=invented_thread_stdout()
    header,hashes=parse(('\n'.join(json.dumps(x) for x in rows)+'\n').encode())
    assert header['path']=='/invented/not-an-executable' and len(hashes)==6


@pytest.mark.parametrize('mutation',['status','raw-zero','duplicate-call','missing-event','stats','poison'])
def test_compare_only_thread_oracle_rejects_changed_payload(mutation):
    rows=invented_thread_stdout()
    call=next(row for row in rows if row['kind']=='call')
    if mutation=='status':call['status']=6
    elif mutation=='raw-zero':call['fields'][0]='0'*len(call['fields'][0])
    elif mutation=='duplicate-call':rows[-2]=call.copy()
    elif mutation=='missing-event':rows.pop(1)
    elif mutation=='stats':call['stats'][1]+=1
    elif mutation=='poison':call['fields'][0]='7ff800000000dead'+call['fields'][0][16:]
    with pytest.raises((AssertionError,ValueError,KeyError)):
        parse(('\n'.join(json.dumps(x) for x in rows)+'\n').encode())


class InventedLibrary:
    """Not a CDLL. Explicitly fake no-math callbacks for recording selfchecks."""
    def __init__(self,path):pass
    def create(self,opts,handle,error,length):handle._obj.value=1234;return 0
    def destroy(self,handle,error,length):return 0
    def evaluate(self,*args):return 1


def invented_receipts(tmp_path,monkeypatch):
    from . import support
    monkeypatch.setattr(support,'Library',InventedLibrary)
    binary=tmp_path/'not-an-executable'
    binary.write_bytes(b'explicitly invented receipt fixture; no native code')
    recorder=Recorder(binary,tmp_path/'invented','invented-no-native-library')
    case=guard_case(Evaluation(np.ones((5,5,5))))
    with recorder.context() as handle:
        assert recorder.run(handle,case,'invented-non-math-rejection')[0]==1
    json_new(recorder.directory/'end.json',dict(evaluations=1,live_contexts=0,
        native_acceptance='requires external complete pytest/trace/receipt verification'))
    return recorder,binary


def test_raw_recorder_receipts_are_bound_without_loading_native_code(tmp_path,monkeypatch):
    recorder,binary=invented_receipts(tmp_path,monkeypatch)
    checked=check_invented(recorder,binary)
    assert len(checked)>10


@pytest.mark.parametrize('mutation',['raw-bytes','extra-file','ordinal-bool','duplicate-key','wrong-library'])
def test_receipt_binding_rejects_mutations(tmp_path,monkeypatch,mutation):
    recorder,binary=invented_receipts(tmp_path,monkeypatch)
    record=recorder.directory/'0002.json'
    if mutation=='raw-bytes':
        (recorder.directory/'0002-rdg.bin').write_bytes(b'changed invented artifact')
    elif mutation=='extra-file':(recorder.directory/'unbound.txt').write_text('extra')
    elif mutation=='wrong-library':binary.write_bytes(b'changed fixture identity')
    elif mutation=='ordinal-bool':
        data=json.loads((recorder.directory/'0001.json').read_text());data['ordinal']=True
        (recorder.directory/'0001.json').write_text(json.dumps(data))
    elif mutation=='duplicate-key':record.write_text('{"ordinal":2,"ordinal":2}')
    with pytest.raises((AssertionError,ValueError,KeyError)):
        check_invented(recorder,binary)


def invented_spec(status=1,entry=False,shape=(5,5,5)):
    return dict(status=status,mode=1,backend=1,entry=entry,
                diagnostics=(True,True),shape=list(shape),input_shape=list(shape))


def check_invented(recorder,binary):
    return group(recorder.directory,binary,1,'invented-no-native-library',
                 inventory={'invented-non-math-rejection':invented_spec()},
                 rejected_inventory={},context_count=1,kind_counts={'create':1,'evaluate':1,'destroy':1})


def rewrite_json(path,value):
    path.write_text(json.dumps(value,allow_nan=False)+'\n')


@pytest.mark.parametrize('mutation',['delete-rdg','delete-signedrho','delete-lambda2','delete-flags',
    'delete-grad','delete-hess','wrong-mode','truncated-rdg','wrong-shape','orphan-context',
    'missing-context','missing-context-id','wrong-eval-ordinal','wrong-eval-link','unknown-kind',
    'missing-destroy','wrong-case-id','out-of-order'])
def test_complete_receipt_binding_rejects_omissions_and_lifecycle(tmp_path,monkeypatch,mutation):
    recorder,binary=invented_receipts(tmp_path,monkeypatch)
    file=recorder.directory/'0002.json'
    record=json.loads(file.read_text())
    if mutation.startswith('delete-'):
        artifact=record['artifacts'].pop(mutation.removeprefix('delete-'))
        Path(artifact['path']).unlink()  # self-created invented fixture only
    elif mutation=='wrong-mode':
        create=recorder.directory/'0001.json';row=json.loads(create.read_text())
        path=Path(row['artifacts']['options']['path'])
        opts=Options.from_buffer_copy(path.read_bytes());opts.output_mode=0
        path.write_bytes(bytes(opts));row['artifacts']['options']=fingerprint(path)
        rewrite_json(create,row)
    elif mutation=='truncated-rdg':
        path=Path(record['artifacts']['rdg']['path']);path.write_bytes(path.read_bytes()[:-8])
        record['artifacts']['rdg']=fingerprint(path)
    elif mutation=='wrong-shape':record['shape']=[1,5,5]
    elif mutation=='orphan-context':record['context_token']=9999
    elif mutation=='missing-context':del record['context_token']
    elif mutation=='missing-context-id':del record['context_id']
    elif mutation=='wrong-eval-ordinal':record['eval_ordinal']=2
    elif mutation=='wrong-eval-link':record['evaluation_record_ordinal']=1
    elif mutation=='unknown-kind':record['kind']='unbound-call'
    elif mutation=='missing-destroy':
        path=recorder.directory/'0003.json';row=json.loads(path.read_text())
        for artifact in row['artifacts'].values():Path(artifact['path']).unlink()
        path.unlink()
    elif mutation=='wrong-case-id':record['case_id']='unplanned-case'
    elif mutation=='out-of-order':
        create=json.loads((recorder.directory/'0001.json').read_text())
        cached=[(row,{name:Path(item['path']).read_bytes() for name,item in row['artifacts'].items()})
                for row in (record,create)]
        for ordinal,(row,blobs) in enumerate(cached,1):
            row['ordinal']=ordinal
            if row['kind']=='evaluate':row['evaluation_record_ordinal']=ordinal
            else:row['context_id']=ordinal
            for name,data in blobs.items():
                path=recorder.directory/f'{ordinal:04d}-{name}.bin';path.write_bytes(data)
                row['artifacts'][name]=fingerprint(path)
            rewrite_json(recorder.directory/f'{ordinal:04d}.json',row)
        with pytest.raises(AssertionError):check_invented(recorder,binary)
        return
    rewrite_json(file,record)
    with pytest.raises((AssertionError,ValueError,KeyError)):
        check_invented(recorder,binary)


@pytest.mark.parametrize('status',[0,3,4])
@pytest.mark.parametrize('buffer',[5,6])
def test_completed_ledger_cannot_replace_staging_move_with_host_free(status,buffer):
    values,rows,sizes=invented_ledger();values['backend_status']=status
    if status==4:values.update(first_failure_global_index=62,first_failure_status=6)
    rows=[row for row in rows if not(row[1]==10 and row[2]==buffer)]
    for seq,row in enumerate(rows,1):
        row[0]=seq
        if row[1]==11 and row[2]==buffer:row[1]=9
    values['event_count']=len(rows)
    with pytest.raises(AssertionError):validate_ledger(values,rows,sizes,status)


def test_validation_failure_can_clean_staging_without_transfer():
    values,rows,sizes=invented_ledger();values['backend_status']=6
    rows=[row for row in rows if row[1]!=10]
    for seq,row in enumerate(rows,1):
        row[0]=seq
        if row[1]==11:row[1]=9
    values['event_count']=len(rows)
    validate_ledger(values,rows,sizes,6)


@pytest.mark.parametrize('status',[0,3,4])
def test_completed_ledger_requires_and_accepts_both_staging_transfers(status):
    values,rows,sizes=invented_ledger();values['backend_status']=status
    if status==4:values.update(first_failure_global_index=62,first_failure_status=6)
    validate_ledger(values,rows,sizes,status)


@pytest.mark.parametrize('phase',['device-live','nonoutput-host-live'])
def test_ledger_rejects_premature_staging_move(phase):
    values,rows,sizes=invented_ledger()
    move=next(row for row in rows if row[1:3]==[10,5])
    rows.remove(move)
    before=next(i for i,row in enumerate(rows) if row[1]==(7 if phase=='device-live' else 9))
    move[4:]=rows[before-1][4:]
    rows.insert(before,move)
    for seq,row in enumerate(rows,1):row[0]=seq
    with pytest.raises(AssertionError):validate_ledger(values,rows,sizes,0)


@pytest.mark.parametrize('sign',[-1,1])
def test_independent_near_zero_requires_bit5(sign):
    case=SimpleNamespace(lambda2=np.array([sign*1e-13]),flags=np.array([64],dtype=np.uint8))
    with pytest.raises(AssertionError):assert_subtau_uncertain(case,np.array([True]))
    case.flags[0]=96
    assert_subtau_uncertain(case,np.array([True]))


def test_independent_finite_call_inventory_not_receipt_counts():
    assert len(expected_calls('production-shared-library'))==295
    assert len(expected_calls('same-production-objects-test-only-bridge'))==55
    assert len(expected_rejected_creates('production-shared-library'))==13
    assert len(expected_rejected_creates('production-cpu-only'))==1
    assert sum(KIND_COUNTS['production-shared-library'].values())==524
    assert sum(KIND_COUNTS['same-production-objects-test-only-bridge'].values())==260
    assert sum(spec['entry'] for spec in expected_calls('production-shared-library').values())==238
    assert sum(spec['entry'] and spec['status']!=5 for spec in expected_calls('same-production-objects-test-only-bridge').values())==34


def test_observer_preflight_preserves_previous_call_ordinal_and_payload():
    previous=initial_observation()
    state=dict(backend=1,backend_ordinal=0,observation=previous,
               last_eval=dict(spec={'entry':False},observed=False))
    record=dict(status=0,observation=previous)
    observation(record,state)
    assert state['last_eval']['observed']
    changed=json.loads(json.dumps(previous));changed['values'][2]=1
    with pytest.raises(AssertionError):observation(dict(status=0,observation=changed),state)


class InventedSuccessLibrary(InventedLibrary):
    def evaluate(self,*args):return 0


class InventedObserver:
    """Explicit synthetic ledger; no device routine or native evaluator."""
    def observe(self,recorder,handle):
        values,rows,_=invented_ledger()
        values['call_ordinal']=recorder.context_reference(handle)['eval_ordinal']
        snapshot=dict(values=list(values.values()),events=rows+[[0]*6 for _ in range(256-len(rows))],n_events=len(rows))
        recorder.retain('private-observe','observe',0,'',observation=snapshot,
                        **recorder.context_reference(handle))
        return snapshot


def invented_private_receipts(tmp_path,monkeypatch):
    from . import support
    monkeypatch.setattr(support,'Library',InventedSuccessLibrary)
    binary=tmp_path/'not-a-private-native-library';binary.write_bytes(b'invented observer fixture only')
    role='same-production-objects-test-only-bridge'
    recorder=Recorder(binary,tmp_path/'invented-private',role)
    recorder.hooks=InventedObserver()
    case=guard_case(Evaluation(np.ones((5,7,9))))
    with recorder.context(case_id='corruption') as handle:
        assert recorder.run(handle,case,'invented-success')[0]==0
        # Automatic observer receipt is durable before run() returns.
        assert (recorder.directory/'0003.json').is_file()
    json_new(recorder.directory/'end.json',dict(evaluations=1,live_contexts=0,
        native_acceptance='requires external complete pytest/trace/receipt verification'))
    return recorder,binary


def check_invented_private(recorder,binary):
    return group(recorder.directory,binary,1,'same-production-objects-test-only-bridge',
        inventory={'invented-success':invented_spec(0,True,(5,7,9))},
        rejected_inventory={},context_count=1,kind_counts={'create':1,'evaluate':1,'private-observe':1,'destroy':1})


def test_complete_private_observer_binding(tmp_path,monkeypatch):
    recorder,binary=invented_private_receipts(tmp_path,monkeypatch)
    check_invented_private(recorder,binary)


@pytest.mark.parametrize('mutation',['missing-observation','missing-observe-record','short-values',
    'short-events','short-event-row','bad-n-events','wrong-backend-ordinal','wrong-context',
    'wrong-eval-link','wrong-eval-ordinal','event-order','nonzero-unused','bool-value'])
def test_private_observer_binding_rejects_incomplete_or_unbound(tmp_path,monkeypatch,mutation):
    recorder,binary=invented_private_receipts(tmp_path,monkeypatch)
    file=recorder.directory/'0003.json';record=json.loads(file.read_text())
    if mutation=='missing-observation':del record['observation']
    elif mutation=='missing-observe-record':
        destroy=json.loads((recorder.directory/'0004.json').read_text());destroy['ordinal']=3
        for name,item in destroy['artifacts'].items():
            old=Path(item['path']);new=recorder.directory/f'0003-{name}.bin'
            new.write_bytes(old.read_bytes());old.unlink();destroy['artifacts'][name]=fingerprint(new)
        rewrite_json(file,destroy);(recorder.directory/'0004.json').unlink()
    elif mutation=='short-values':record['observation']['values'].pop()
    elif mutation=='short-events':record['observation']['events'].pop()
    elif mutation=='short-event-row':record['observation']['events'][0].pop()
    elif mutation=='bad-n-events':record['observation']['n_events']-=1
    elif mutation=='wrong-backend-ordinal':record['observation']['values'][1]+=1
    elif mutation=='wrong-context':record['context_token']=9999
    elif mutation=='wrong-eval-link':record['evaluation_record_ordinal']=1
    elif mutation=='wrong-eval-ordinal':record['eval_ordinal']=2
    elif mutation=='event-order':record['observation']['events'][0][0]=2
    elif mutation=='nonzero-unused':record['observation']['events'][-1][0]=1
    elif mutation=='bool-value':record['observation']['values'][0]=True
    if mutation!='missing-observe-record':rewrite_json(file,record)
    with pytest.raises((AssertionError,ValueError,KeyError)):
        check_invented_private(recorder,binary)


def test_observer_is_retained_before_post_call_guard_failure(tmp_path,monkeypatch):
    from . import support
    monkeypatch.setattr(support,'Library',InventedSuccessLibrary)
    binary=tmp_path/'not-an-executable';binary.write_bytes(b'explicit fake callback')
    recorder=Recorder(binary,tmp_path/'failure-retention','invented-no-native-library')
    recorder.hooks=InventedObserver()
    case=guard_case(Evaluation(np.ones((5,7,9))))
    case._guards[0][0]=0
    with recorder.context() as handle:
        with pytest.raises(AssertionError):recorder.run(handle,case,'invented-guard-failure')
        assert (recorder.directory/'0002.json').is_file() and (recorder.directory/'0003.json').is_file()


def replace_option_bytes(recorder,ordinal,data):
    file=recorder.directory/f'{ordinal:04d}.json';row=json.loads(file.read_text())
    path=Path(row['artifacts']['options']['path']);path.write_bytes(data)
    row['artifacts']['options']=fingerprint(path)
    rewrite_json(file,row)


@pytest.mark.parametrize('field,value',[
    ('omp_threads',0),('omp_threads',17),('rho_min',float('nan')),('rho_min',0),
    ('negative_tolerance',float('nan')),('negative_tolerance',-1),
    ('negative_tolerance',-0.0),('rho_min',.2)])
def test_complete_options_binding_rejects_rehashed_success_mutations(tmp_path,monkeypatch,field,value):
    recorder,binary=invented_receipts(tmp_path,monkeypatch)
    opts=options(backend=1);setattr(opts,field,value)
    replace_option_bytes(recorder,1,bytes(opts))
    with pytest.raises(AssertionError):check_invented(recorder,binary)


def invented_low_zero_receipts(tmp_path,monkeypatch):
    from . import support
    monkeypatch.setattr(support,'Library',InventedSuccessLibrary)
    binary=tmp_path/'not-an-options-native-library';binary.write_bytes(b'explicit low-zero receipt fixture')
    recorder=Recorder(binary,tmp_path/'invented-low-zero','production-shared-library')
    case=guard_case(Evaluation(np.ones((9,9,9))))
    with recorder.context(options(backend=1,rho_min=.2),case_id='low-zero') as handle:
        assert recorder.run(handle,case,'low-zero')[0]==0
    json_new(recorder.directory/'end.json',dict(evaluations=1,live_contexts=0,
        native_acceptance='requires external complete pytest/trace/receipt verification'))
    return recorder,binary


def check_low_zero(recorder,binary):
    return group(recorder.directory,binary,1,'production-shared-library',
        inventory={'low-zero':expected_calls('production-shared-library')['low-zero']},
        rejected_inventory={},context_count=1,kind_counts={'create':1,'evaluate':1,'destroy':1})


def test_low_zero_threshold_is_bound_to_independent_point2(tmp_path,monkeypatch):
    recorder,binary=invented_low_zero_receipts(tmp_path,monkeypatch)
    check_low_zero(recorder,binary)
    replace_option_bytes(recorder,1,bytes(options(backend=1,rho_min=1e-8)))
    with pytest.raises(AssertionError):check_low_zero(recorder,binary)


REJECTED_OPTION_IDS=sorted(expected_rejected_creates('production-shared-library'))+['cpu-only-openacc-selector']


def rejected_options_fixture(tmp_path,monkeypatch,case_id):
    from . import support
    monkeypatch.setattr(support,'Library',InventedLibrary)
    role='production-cpu-only' if case_id=='cpu-only-openacc-selector' else 'production-shared-library'
    status=expected_rejected_creates(role)[case_id]
    if case_id.startswith('option/'):
        opts=options(backend=1)
        match=[(field,value) for field,value in BAD_OPTIONS if f'option/{field}/{value}'==case_id]
        assert len(match)==1
        setattr(opts,*match[0])
    else:opts=options(backend=2 if case_id=='cuda-unavailable' else 1)
    # The source test's ctypes input is compared to separately packed expected bits.
    assert bytes(opts)==expected_rejected_options(role)[case_id]
    binary=tmp_path/'not-a-rejected-native-library';binary.write_bytes(b'rejected-input byte fixture only')
    recorder=Recorder(binary,tmp_path/'invented-rejected',role)
    errbytes=16 if case_id.startswith('option/') else 128 if case_id=='cuda-unavailable' else 512
    recorder.retain('create-rejected',case_id,status,'',dict(options=bytes(opts),errbuf=b'\0'*errbytes),context_token=None)
    return recorder,binary,role,status


def check_rejected_options(recorder,binary,role,case_id,status):
    return group(recorder.directory,binary,0,role,inventory={},
        rejected_inventory={case_id:status},context_count=0,kind_counts={'create-rejected':1})


@pytest.mark.parametrize('case_id',REJECTED_OPTION_IDS)
def test_rejected_options_bind_exact_predefined_mutation(tmp_path,monkeypatch,case_id):
    recorder,binary,role,status=rejected_options_fixture(tmp_path,monkeypatch,case_id)
    check_rejected_options(recorder,binary,role,case_id,status)
    old=Path(json.loads((recorder.directory/'0001.json').read_text())['artifacts']['options']['path']).read_bytes()
    changed=bytes([old[0]^1])+old[1:]
    replace_option_bytes(recorder,1,changed)
    with pytest.raises(AssertionError):check_rejected_options(recorder,binary,role,case_id,status)


@pytest.mark.parametrize('case_id,offset',[('option/rho_min/nan',24),('option/negative_tolerance/nan',32)])
def test_rejected_options_require_nan_payload_bits(tmp_path,monkeypatch,case_id,offset):
    recorder,binary,role,status=rejected_options_fixture(tmp_path,monkeypatch,case_id)
    path=Path(json.loads((recorder.directory/'0001.json').read_text())['artifacts']['options']['path'])
    changed=bytearray(path.read_bytes());changed[offset:offset+8]=struct.pack('<Q',0x7ff8000000000001)
    replace_option_bytes(recorder,1,bytes(changed))
    with pytest.raises(AssertionError):check_rejected_options(recorder,binary,role,case_id,status)


def test_independent_full_options_inventory_covers_all_contexts_and_evaluations():
    for role in ('production-shared-library','same-production-objects-test-only-bridge'):
        table=expected_create_options(role)
        for case_id,spec in expected_calls(role).items():
            blob=expected_options_for_call(case_id,spec)
            assert len(blob)==40 and any(blob in choices for choices in table.values())
            opts=Options.from_buffer_copy(blob)
            assert opts.omp_threads==1 and opts.reserved==0
            assert opts.abi_version==1 and opts.struct_bytes==40
            assert np.isfinite(opts.rho_min) and opts.rho_min>0
            assert np.isfinite(opts.negative_tolerance) and opts.negative_tolerance>=0
    assert options_blob()==bytes(options(backend=1))
    assert expected_options_for_call('low-zero',{'mode':1,'backend':1})==bytes(options(backend=1,rho_min=.2))
    assert expected_options_for_call('subnormal-gradient',{'mode':1,'backend':1})[24:32]==struct.pack('<Q',1)


def test_frozen_corpus_arithmetic_and_case_ids():
    here=Path(__file__).resolve().parent
    corpus=json.loads((here/'corpus.json').read_text())
    cases=json.loads((here/'case_ids.json').read_text())
    assert sum(corpus['public_eval_groups'].values())==295
    assert sum(corpus['private_eval_groups'].values())==55
    assert 295+55+6==corpus['total_evaluations']==356<=512
    assert len(cases['nodeids'])==len(set(cases['nodeids']))==corpus['native_pytest_cases']==148
    assert corpus['python_receipt_records']=={'public':524,'private':260,'cpu-selector':1}
    assert corpus['private_configure_calls']==29 and corpus['private_observe_calls']==118


def test_frozen_expectation_sources_unchanged():
    here=Path(__file__).resolve().parent
    manifest=json.loads((here/'expectation_sources.json').read_text())
    root=here.parents[1]
    for item in manifest['sources']:
        data=(root/item['path']).read_bytes()
        assert len(data)==item['bytes'] and hashlib.sha256(data).hexdigest()==item['sha256']
