"""Pure invented-ledger and fixture checks. Never loads a candidate library."""
import ctypes as ct
import importlib.util
import json
import hashlib
from pathlib import Path

import numpy as np
import pytest
from .support import guard_case,check_guards,byte_snapshot,assert_unchanged,Recorder,json_new
from .private import VALUE_NAMES,array_sizes,validate_ledger
from .test_rejections import mutated,MUTATIONS
from .verify_threads import strict_json,parse
from .verify_receipts import group
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
    checked=group(recorder.directory,binary,1,'invented-no-native-library')
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
        group(recorder.directory,binary,1,'invented-no-native-library')


def test_frozen_corpus_arithmetic_and_case_ids():
    here=Path(__file__).resolve().parent
    corpus=json.loads((here/'corpus.json').read_text())
    cases=json.loads((here/'case_ids.json').read_text())
    assert sum(corpus['public_eval_groups'].values())==295
    assert sum(corpus['private_eval_groups'].values())==55
    assert 295+55+6==corpus['total_evaluations']==356<=512
    assert len(cases['nodeids'])==len(set(cases['nodeids']))==corpus['native_pytest_cases']==148


def test_frozen_expectation_sources_unchanged():
    here=Path(__file__).resolve().parent
    manifest=json.loads((here/'expectation_sources.json').read_text())
    root=here.parents[1]
    for item in manifest['sources']:
        data=(root/item['path']).read_bytes()
        assert len(data)==item['bytes'] and hashlib.sha256(data).hexdigest()==item['sha256']
