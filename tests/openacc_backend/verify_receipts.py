"""Compare-only binding of raw Python receipts and mandatory native JUnit cases.

The manual controller must additionally verify source/build/provenance, exits,
timeouts, resource caps and original runtime notices. This program never launches
pytest, Git, a compiler or any candidate and does not turn receipts alone into
GPU/scientific acceptance.
"""
import argparse
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

if __package__:
    from .support import fingerprint,json_new
    from .verify_threads import strict_json
else:
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    from support import fingerprint,json_new
    from verify_threads import strict_json

HERE=Path(__file__).resolve().parent
CAP=128*1024*1024


def group(directory,library,expected_evals,role):
    directory=Path(directory).resolve(strict=True)
    receipt=fingerprint(library)
    metadata=strict_json((directory/'library.json').read_text(encoding='utf-8'))
    assert type(metadata['schema_version']) is int
    assert metadata==dict(schema_version=1,role=role,library=receipt,abi_sizes=[40,280,88])
    files=sorted(p for p in directory.glob('*.json') if re.fullmatch(r'[0-9]{4}\.json',p.name))
    evaluations=0;checked=[];seen=set()
    for ordinal,file in enumerate(files,1):
        assert file.name==f'{ordinal:04d}.json'
        record=strict_json(file.read_text(encoding='utf-8'))
        assert type(record['schema_version']) is int and record['schema_version']==1
        assert type(record['ordinal']) is int and record['ordinal']==ordinal
        assert type(record['status']) is int and 0<=record['status']<=6
        assert isinstance(record['case_id'],str) and record['case_id']
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
        if record['kind']=='evaluate':
            evaluations+=1
            assert {'input-rho','tile','stats-before','stats-after','errbuf'}<=set(record['artifacts'])
            assert record['artifacts']['tile']['bytes']==280
            assert record['artifacts']['stats-before']['bytes']==record['artifacts']['stats-after']['bytes']==88
    assert evaluations==expected_evals
    if expected_evals:
        end=strict_json((directory/'end.json').read_text(encoding='utf-8'))
        assert type(end['evaluations']) is int and type(end['live_contexts']) is int
        assert end==dict(evaluations=expected_evals,live_contexts=0,
              native_acceptance='requires external complete pytest/trace/receipt verification')
        checked.append(fingerprint(directory/'end.json'))
    else:
        assert len(files)==1
        record=strict_json(files[0].read_text(encoding='utf-8'))
        assert record['kind']=='create-rejected' and record['status']==6
    expected_files={directory/'library.json',*files,*seen}
    if expected_evals:expected_files.add(directory/'end.json')
    assert set(directory.iterdir())==expected_files,'unbound or missing raw receipt file'
    checked.extend([fingerprint(directory/'library.json'),receipt])
    assert sum(x['bytes'] for x in checked)<=CAP
    return checked


def verify(root,junit,library,bridge,cpu_library):
    corpus=strict_json((HERE/'corpus.json').read_text(encoding='utf-8'))
    cases=strict_json((HERE/'case_ids.json').read_text(encoding='utf-8'))
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
        report=dict(schema_version=1,state='PASS',scope='receipt and mandatory-case binding only; runtime/source/controller review still required',
                    artifacts=checked,public_evaluations=295,private_evaluations=55)
        code=0
    except (AssertionError,OSError,ValueError,KeyError,TypeError,ET.ParseError) as error:
        report=dict(schema_version=1,state='FAILED',error=str(error));code=1
    json_new(args.report,report)
    return code


if __name__=='__main__':sys.exit(main())
