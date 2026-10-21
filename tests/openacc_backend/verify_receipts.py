"""Compare-only binding of raw Python receipts and mandatory native JUnit cases.

The manual controller must additionally verify source/build/provenance, exits,
timeouts, resource caps and original runtime notices. This program never launches
pytest, Git, a compiler or any candidate and does not turn receipts alone into
GPU/scientific acceptance.
"""
import argparse
import ctypes as ct
from collections import Counter
import json
import math
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

if __package__:
    from .support import fingerprint,json_new
    from .verify_threads import strict_json
    from .expectations import COUNTS,expected_calls,expected_rejected_creates
    from .private import VALUE_NAMES,validate_ledger
else:
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    from support import fingerprint,json_new
    from verify_threads import strict_json
    from expectations import COUNTS,expected_calls,expected_rejected_creates
    from private import VALUE_NAMES,validate_ledger
from reference.abi import Options,Tile

HERE=Path(__file__).resolve().parent
CAP=128*1024*1024


BASE={'schema_version','kind','case_id','ordinal','library','status','error','artifacts'}
REF={'context_token','context_id','eval_ordinal','evaluation_record_ordinal'}
EXTRA={'create':{'backend','context_token','context_id'},'destroy':REF,
       'evaluate':REF|{'shape','input_shape','tile_start','mutations'},
       'create-rejected':{'context_token'},'private-observe':REF|{'observation'},
       'private-configure':REF|{'failure_at','corruption'}}
CONTEXT_COUNTS={'production-shared-library':108,'same-production-objects-test-only-bridge':29,
                'production-cpu-only':0}
KIND_COUNTS={'production-shared-library':{'create':108,'destroy':108,'evaluate':295,'create-rejected':13},
    'same-production-objects-test-only-bridge':{'create':29,'destroy':29,'evaluate':55,
        'private-configure':29,'private-observe':118},'production-cpu-only':{'create-rejected':1}}


def integer(value,lo=0,hi=(1<<63)-1):
    assert type(value) is int and lo<=value<=hi
    return value


def initial_observation():
    values=[0]*24;values[0]=1;values[18]=-1
    return dict(values=values,events=[[0]*6 for _ in range(256)],n_events=0)


def observation(record,state):
    snapshot=record['observation']
    assert set(snapshot)=={'values','events','n_events'}
    values,events,n=snapshot['values'],snapshot['events'],snapshot['n_events']
    assert type(values) is list and len(values)==24
    assert type(events) is list and len(events)==256
    for value in values:integer(value,-(1<<63))
    for row in events:
        assert type(row) is list and len(row)==6
        for value in row:integer(value,-(1<<63))
    integer(n,0,256)
    assert all(row==[0]*6 for row in events[n:])
    if state is None or state['backend']==0:
        assert record['status']==1 and n==0 and values==[0]*24
        return
    assert record['status']==0 and values[0]==1 and values[23]==n
    assert values[1]==state['backend_ordinal']
    pending=state['last_eval']
    if pending is None or not pending['spec']['entry']:
        assert snapshot==state['observation'],'preflight changed private observations'
    elif pending['observed']:
        assert snapshot==state['observation'],'same evaluation observation changed'
    else:
        v=dict(zip(VALUE_NAMES,values))
        validate_ledger(v,events[:n],pending['sizes'],record_status:=pending['status'],pending['failure'])
        if pending['corruption']:
            assert record_status==6
            assert v['verified_markers']==pending['sizes'][6]-(pending['corruption']==1)
        state['observation']=snapshot
    if pending is not None:pending['observed']=True


def group(directory,library,expected_evals,role,*,inventory=None,rejected_inventory=None,context_count=None,kind_counts=None):
    directory=Path(directory).resolve(strict=True)
    inventory=expected_calls(role) if inventory is None else inventory
    rejected_inventory=expected_rejected_creates(role) if rejected_inventory is None else rejected_inventory
    context_count=CONTEXT_COUNTS[role] if context_count is None else context_count
    kind_counts=KIND_COUNTS[role] if kind_counts is None else kind_counts
    assert expected_evals==len(inventory)
    receipt=fingerprint(library)
    metadata=strict_json((directory/'library.json').read_text(encoding='utf-8'))
    assert type(metadata['schema_version']) is int
    assert metadata==dict(schema_version=1,role=role,library=receipt,abi_sizes=[40,280,88])
    files=sorted(p for p in directory.glob('*.json') if re.fullmatch(r'[0-9]{4}\.json',p.name))
    evaluations=0;checked=[];seen=set();live={};context_ids=set();evaluated=set();rejected=set();creates=0;actual_kinds=Counter()
    private=role=='same-production-objects-test-only-bridge'
    for ordinal,file in enumerate(files,1):
        assert file.name==f'{ordinal:04d}.json'
        record=strict_json(file.read_text(encoding='utf-8'))
        kind=record['kind']
        actual_kinds[kind]+=1
        assert kind in EXTRA and set(record)==BASE|EXTRA[kind], 'unknown kind or incomplete record schema'
        assert type(record['schema_version']) is int and record['schema_version']==1
        assert type(record['ordinal']) is int and record['ordinal']==ordinal
        assert type(record['status']) is int and 0<=record['status']<=6
        assert isinstance(record['case_id'],str) and record['case_id']
        assert isinstance(record['error'],str)
        assert record['library']==receipt
        assert type(record['artifacts']) is dict
        checked.append(fingerprint(file))
        for artifact in record['artifacts'].values():
            assert set(artifact)=={'path','sha256','bytes'}
            path=Path(artifact['path']).resolve(strict=True)
            assert path.parent==directory and path not in seen
            assert type(artifact['bytes']) is int and artifact['bytes']>=0
            assert fingerprint(path)==artifact
            seen.add(path);checked.append(artifact)
        artifacts=record['artifacts']
        for name,artifact in artifacts.items():
            assert Path(artifact['path']).resolve().name==f'{ordinal:04d}-{name}.bin'
        def sizes(required):
            assert set(artifacts)==set(required),'missing or extra field artifact'
            for name,size in required.items():assert artifacts[name]['bytes']==size,(name,size)
        def blob(name):return Path(artifacts[name]['path']).read_bytes()
        if kind=='create-rejected':
            name=record['case_id']
            assert name in rejected_inventory and name not in rejected
            rejected.add(name)
            assert record['status']==rejected_inventory[name] and record['context_token'] is None
            sizes({'options':40,'errbuf':16 if name.startswith('option/') else 128 if name=='cuda-unavailable' else 512})
        elif kind=='create':
            sizes({'options':40,'errbuf':512})
            assert record['status']==0
            opts=Options.from_buffer_copy(blob('options'))
            assert opts.abi_version==1 and opts.struct_bytes==40 and opts.reserved==0
            assert opts.output_mode in (0,1) and opts.backend in (0,1)
            assert integer(record['backend'],0,1)==opts.backend
            token=integer(record['context_token'],1,(1<<64)-1)
            cid=integer(record['context_id'],1)
            assert cid==ordinal and cid not in context_ids and token not in live and len(live)<2
            context_ids.add(cid);creates+=1
            live[token]=dict(context_id=cid,mode=int(opts.output_mode),backend=int(opts.backend),
                eval_ordinal=0,evaluation_record_ordinal=None,backend_ordinal=0,
                observation=initial_observation(),last_eval=None,pending=(0,0))
        else:
            token=record['context_token'];state=None
            if token is not None:
                integer(token,1,(1<<64)-1)
                assert token in live,'call before create or after destroy'
                state=live[token]
            if state is None:
                assert kind in ('private-observe','private-configure') and private
                assert record['context_id'] is None and integer(record['eval_ordinal'])==0 and record['evaluation_record_ordinal'] is None
            else:
                assert integer(record['context_id'],1)==state['context_id']
            if kind=='evaluate':
                assert state is not None
                if private and state['last_eval'] is not None:assert state['last_eval']['observed']
                state['eval_ordinal']+=1;state['evaluation_record_ordinal']=ordinal
            if state is not None:
                assert integer(record['eval_ordinal'])==state['eval_ordinal']
                assert record['evaluation_record_ordinal']==state['evaluation_record_ordinal']
                if record['evaluation_record_ordinal'] is not None:integer(record['evaluation_record_ordinal'],1)
            if kind=='destroy':
                sizes({'errbuf':512});assert record['status']==0 and state is not None
                if private and state['last_eval'] is not None:assert state['last_eval']['observed']
                assert state['eval_ordinal']>0 or (private and state['backend']==0)
                del live[token]
            elif kind=='private-configure':
                assert private and artifacts=={}
                f=integer(record['failure_at'],-(1<<31),(1<<31)-1)
                c=integer(record['corruption'],-(1<<31),(1<<31)-1)
                assert record['case_id']==f'configure/{f}/{c}'
                valid=state is not None and state['backend']==1 and 0<=f<=18 and 0<=c<=2 and not(f and c)
                assert record['status']==(0 if valid else 1)
                if valid:state['pending']=(f,c)
            elif kind=='private-observe':
                assert private and artifacts=={}
                assert record['case_id']=='observe'
                observation(record,state)
        if kind=='evaluate':
            evaluations+=1
            name=record['case_id']
            assert name in inventory and name not in evaluated
            evaluated.add(name);spec=inventory[name]
            assert record['status']==spec['status']
            assert (state['mode'],state['backend'])==(spec['mode'],spec['backend'])
            for key in ('shape','input_shape'):
                assert type(record[key]) is list and len(record[key])==3
                for dimension in record[key]:integer(dimension,1,17)
                assert record[key]==spec[key],'physical backing shape differs from finite input plan'
            assert type(record['tile_start']) is list and len(record['tile_start'])==3
            for x in record['tile_start']:integer(x,-(1<<63))
            n=math.prod(record['shape']);nin=math.prod(record['input_shape'])
            required={'input-rho':8*nin,'tile':280,'stats-before':88,'stats-after':88,'errbuf':512,
                      'rdg':8*n,'signedrho':8*n,'lambda2':8*n,'flags':n}
            for present,field,width in zip(spec['diagnostics'],('grad','hess'),(24,48)):
                if present:required[field]=width*n
            sizes(required)
            tile=Tile.from_buffer_copy(blob('tile'))
            assert list(tile.tile_start)==record['tile_start']
            if spec['entry'] or record['status']==0:
                assert list(tile.tile_count)==record['shape'] and list(tile.input_shape)==record['input_shape']
            mutations=record['mutations']
            assert type(mutations) is list and all(type(x) is int for x in mutations)
            wanted_mutations=[]
            if name.startswith('null/'):wanted_mutations=[int(name.split('/')[1])]
            elif name.startswith('alias/'):
                wanted_mutations=[{'rdg':3,'signedrho':4,'lambda2':5,'grad':6,'hess':7,
                                   'flags':8,'stats':9,'errbuf':10}[name.split('/')[1]]]
            assert mutations==wanted_mutations
            if private:
                f,c=state['pending'] if spec['entry'] else (0,0)
                if spec['entry']:
                    assert (f>0)==(record['status']==5) and (c>0)==(record['status']==6)
                    state['pending']=(0,0);state['backend_ordinal']+=1
                    b,ny,nz=map(int,tile.tile_count)
                    assert [b,ny,nz]==record['shape'] and list(tile.input_shape)==record['input_shape']
                    array_sizes={1:8*nin,2:40*b,3:40*ny,4:40*nz,5:(24+72*state['mode'])*n,
                                 6:n,7:4*n,8:4*n,9:4*n}
                else:array_sizes=None
                state['last_eval']=dict(spec=spec,status=record['status'],sizes=array_sizes,
                                       failure=f,corruption=c,observed=False)
    assert evaluations==expected_evals and evaluated==set(inventory)
    assert rejected==set(rejected_inventory) and creates==context_count and not live
    assert dict(actual_kinds)==kind_counts,'call-kind inventory differs from frozen source plan'
    if inventory:
        end=strict_json((directory/'end.json').read_text(encoding='utf-8'))
        assert type(end['evaluations']) is int and type(end['live_contexts']) is int
        assert end==dict(evaluations=expected_evals,live_contexts=0,
              native_acceptance='requires external complete pytest/trace/receipt verification')
        checked.append(fingerprint(directory/'end.json'))
    expected_files={directory/'library.json',*files,*seen}
    if inventory:expected_files.add(directory/'end.json')
    assert set(directory.iterdir())==expected_files,'unbound or missing raw receipt file'
    checked.extend([fingerprint(directory/'library.json'),receipt])
    assert sum(x['bytes'] for x in checked)<=CAP
    return checked


def verify(root,junit,library,bridge,cpu_library):
    corpus=strict_json((HERE/'corpus.json').read_text(encoding='utf-8'))
    cases=strict_json((HERE/'case_ids.json').read_text(encoding='utf-8'))
    assert corpus['native_pytest_cases']==148 and len(cases['nodeids'])==148
    assert corpus['public_shared_evaluations']==COUNTS['production-shared-library']==295
    assert corpus['private_bridge_evaluations']==COUNTS['same-production-objects-test-only-bridge']==55
    data=Path(junit).read_bytes()
    assert len(data)<=4*1024*1024
    tree=ET.fromstring(data)
    items=list(tree.iter('testcase'))
    assert len(items)==corpus['native_pytest_cases']
    names=[]
    for item in items:
        assert not any(item.find(kind) is not None for kind in ('failure','error','skipped'))
        names.append(item.attrib['classname'].split('.')[-1]+'.py::'+item.attrib['name'])
    assert len(names)==len(set(names))
    assert sorted(names)==cases['nodeids']
    checked=[fingerprint(junit),fingerprint(HERE/'corpus.json'),fingerprint(HERE/'case_ids.json')]
    for name,path,count,role in [('public',library,corpus['public_shared_evaluations'],'production-shared-library'),
        ('private',bridge,corpus['private_bridge_evaluations'],'same-production-objects-test-only-bridge'),
        ('cpu-selector',cpu_library,0,'production-cpu-only')]:
        checked+=group(Path(root)/name,path,count,role)
    assert sum(x['bytes'] for x in checked if x['path'] not in (str(Path(library).resolve()),
        str(Path(bridge).resolve()),str(Path(cpu_library).resolve())))<=CAP
    assert all(fingerprint(item['path'])==item for item in checked)
    return checked


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('root','junit','library','bridge','cpu-library','report'):
        parser.add_argument('--'+name,required=True,type=Path)
    args=parser.parse_args(argv)
    try:
        checked=verify(args.root,args.junit,args.library,args.bridge,args.cpu_library)
        report=dict(schema_version=1,state='PASS',scope='complete receipt/lifecycle/finite-call binding only; not mathematical, GPU-runtime or scientific acceptance',
                    artifacts=checked,public_evaluations=295,private_evaluations=55)
        code=0
    except (AssertionError,OSError,ValueError,KeyError,TypeError,ET.ParseError) as error:
        report=dict(schema_version=1,state='FAILED',error=str(error));code=1
    json_new(args.report,report)
    return code


if __name__=='__main__':sys.exit(main())
