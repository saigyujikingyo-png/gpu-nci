"""Compare-only verifier for the six-call public pthread executable. Never launches it."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

import numpy as np
from numpy.testing import assert_array_equal
if __package__:
    from .support import fingerprint,json_new
else:
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    from support import fingerprint,json_new
from reference.abi import Evaluation
from reference.fields import quadratic
from slab_cases import assert_reference

CAP=4*1024*1024
HEX=re.compile(r'[0-9a-f]+\Z')


def strict_json(text):
    def pairs(items):
        out={}
        for key,value in items:
            if key in out: raise ValueError('duplicate JSON key')
            out[key]=value
        return out
    def reject(text): raise ValueError('nonfinite JSON constant '+text)
    return json.loads(text,object_pairs_hook=pairs,parse_constant=reject)


def parse(data):
    if len(data)>CAP: raise ValueError('thread stdout cap')
    rows=[strict_json(line) for line in data.decode('utf-8').splitlines()]
    if len(rows)!=24: raise ValueError('expected 1 header,16 causal events,6 calls,1 end')
    header,end=rows[0],rows[-1]
    assert set(header)=={'kind','path','main_thread','evaluations'} and header['kind']=='library' and header['evaluations']==6
    assert type(header['main_thread']) is int and header['main_thread']>0
    assert end==dict(kind='end',evaluations=6,live_contexts=0)
    calls=[r for r in rows[1:-1] if r.get('kind')=='call']
    events=[r for r in rows[1:-1] if r.get('kind')!='call']
    assert len(calls)==6 and len(events)==16
    wanted={('concurrent',j,r) for j in (0,1) for r in (0,1)}|{
        ('migration-new-thread',0,0),('migration-main-thread',0,0)}
    actual=set()
    hashes=[]
    for call in calls:
        assert set(call)=={'kind','phase','job','repeat','thread','status','check','diagnostic','shape','fields','flags','stats'}
        for key in ('job','repeat','thread','status','check','diagnostic'):
            assert type(call[key]) is int
        key=(call['phase'],call['job'],call['repeat'])
        assert key in wanted and key not in actual
        actual.add(key)
        assert call['status']==call['check']==0
        j=call['job'];shape=(7,5,9) if j else (5,7,9)
        assert call['shape']==list(shape) and call['diagnostic']==int(j==0)
        if j:
            rho=np.full(shape,.125);g=np.zeros((*shape,3));h=np.zeros((*shape,3,3))
        else:
            rho,g,h=quadratic(shape,np.eye(3),np.diag([-.5,-.25,.75]),
                               linear=[.125,-.25,.5],origin=[-2]*3,offset=20)
        case=Evaluation(rho,mode=0 if j else 1)
        names=('rdg','signedrho','lambda2') if j else ('rdg','signedrho','lambda2','grad','hess')
        assert len(call['fields'])==len(names)
        raw=[]
        for name,text in zip(names,call['fields']):
            target=getattr(case,name)
            assert isinstance(text,str) and len(text)==target.size*16 and HEX.fullmatch(text)
            encoded=bytes.fromhex(text);raw.append(encoded)
            target[...]=np.frombuffer(encoded,dtype='>u8').astype(np.uint64).view(np.float64).reshape(target.shape)
        text=call['flags']
        assert isinstance(text,str) and len(text)==630 and HEX.fullmatch(text)
        encoded=bytes.fromhex(text);raw.append(encoded)
        case.flags[...]=np.frombuffer(encoded,dtype=np.uint8).reshape(shape)
        assert len(call['stats'])==11 and all(type(x) is int and x>=0 for x in call['stats'])
        case.stats.total_points,case.stats.valid_points,case.stats.invalid_points,case.stats.numeric_failures=call['stats'][:4]
        case.stats.bit_counts[:]=call['stats'][4:]
        assert_reference(case,rho,g,h,(False,)*3)
        invalid=(case.flags&31)!=0
        for name in names:
            assert np.all(getattr(case,name)[invalid].view(np.uint64)==0x7ff8000000000000)
        hashes.append(dict(phase=key[0],job=key[1],repeat=key[2],
            output_sha256=hashlib.sha256(b''.join(raw)+bytes(case.stats)).hexdigest()))
    assert actual==wanted
    causal={key:{} for key in wanted}
    for seq,event in enumerate(events,1):
        assert set(event)=={'kind','sequence','phase','job','repeat','thread','monotonic_ns'}
        assert type(event['sequence']) is int and event['sequence']==seq
        assert type(event['monotonic_ns']) is int and event['monotonic_ns']>=0
        key=(event['phase'],event['job'],event['repeat'])
        assert type(event['thread']) is int and event['thread']>0
        assert key in causal and event['kind'] in ('ready','begin','end')
        assert event['kind'] not in causal[key]
        causal[key][event['kind']]=(seq,event['monotonic_ns'],event['thread'])
    for key,item in causal.items():
        assert set(item)==({'ready','begin','end'} if key[0]=='concurrent' else {'begin','end'})
        assert item['begin'][0]<item['end'][0] and item['begin'][1]<=item['end'][1]
        if key[0]=='concurrent': assert item['ready'][0]<item['begin'][0]
        assert len({entry[2] for entry in item.values()})==1
        expected_call=next(c for c in calls if (c['phase'],c['job'],c['repeat'])==key)
        assert expected_call['thread']==item['begin'][2]
    for repeat in (0,1):
        pair=[causal[('concurrent',j,repeat)] for j in (0,1)]
        assert max(x['ready'][0] for x in pair)<min(x['begin'][0] for x in pair)
        assert pair[0]['begin'][2]!=pair[1]['begin'][2]
    for job in (0,1):
        assert causal[('concurrent',job,0)]['begin'][2]==causal[('concurrent',job,1)]['begin'][2]
        assert causal[('concurrent',job,0)]['begin'][2]!=header['main_thread']
    assert causal[('migration-new-thread',0,0)]['begin'][2]!=header['main_thread']
    assert causal[('migration-main-thread',0,0)]['begin'][2]==header['main_thread']
    return header,hashes


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('stdout','stderr','binary','library','report'):
        parser.add_argument('--'+name,required=True,type=Path)
    args=parser.parse_args(argv)
    artifacts={key:fingerprint(getattr(args,key)) for key in ('stdout','stderr','binary','library')}
    try:
        header,calls=parse(args.stdout.read_bytes())
        assert fingerprint(header['path'])==artifacts['library']
        assert all(fingerprint(item['path'])==item for item in artifacts.values())
        report=dict(schema_version=1,state='PASS',scope='finite synthetic public pthread outputs only',
                    artifacts=artifacts,calls=calls)
        code=0
    except (AssertionError,ValueError,KeyError,TypeError,OSError) as error:
        report=dict(schema_version=1,state='FAILED',error=str(error),artifacts=artifacts);code=1
    json_new(args.report,report)
    return code


if __name__=='__main__': sys.exit(main())
