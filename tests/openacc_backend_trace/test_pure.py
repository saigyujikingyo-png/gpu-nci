"""Invented notices and non-executable files only; no GPU/native acceptance."""
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('trace_verify', Path(__file__).with_name('verify.py'))
v = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v)


def policy():
    sites = {}
    explicit = dict(upload=[], launch='kernel', download=[])
    for kind, names in [('upload', ['rho', 'tx', 'ty', 'tz', 'fields', 'flags', 'status', 'nrot', 'marker']),
                        ('launch', ['kernel']),
                        ('download', ['fields', 'flags', 'status', 'nrot', 'marker'])]:
        for index, name in enumerate(names):
            key = kind + '_' + name if kind != 'launch' else name
            fields = dict(file='/invented non-executable/source.f90', function=key, line=str(100 + index))
            if kind != 'launch':
                fields['variable'] = 'x'
            else:
                fields.update(num_gangs=None, num_workers='1', vector_length='128', grid=None, block='128')
            sites[key] = dict(kind=kind, fields=fields, proof='invented source/report only')
            if kind != 'launch':
                explicit[kind].append(key)
    sites['metadata'] = dict(kind='upload', fields=dict(file='/invented non-executable/source.f90',
        function='fixed_descriptor', line='777', variable='descriptor'), proof='invented compiler report')
    return dict(sites=sites, explicit=explicit, metadata=[], process_notices={
        key:dict(prefix=[], suffix=[]) for key in ('python', 'pthread')})


def row(name='invented', status=0, entry=True, mode=1):
    return dict(case_id=name, mode=mode, backend=1, shape=[1, 7, 9], input_shape=[5, 7, 9], status=status, entry=entry)


def notice(item, p):
    site, size = item; rule = p['sites'][site]; kind = rule['kind']
    fields = {key: ('2' if value is None else value) for key, value in rule['fields'].items()}
    fields.update(device='0', threadid='97')
    if kind != 'launch':
        fields['bytes'] = str(size)
    prefix = 'launch CUDA kernel' if kind == 'launch' else kind + ' CUDA data'
    return prefix + ' ' + ' '.join(f'{key}={value}' for key, value in fields.items())


def log(rows, p):
    return ('\n'.join(notice(event, p) for r in rows for event in v.call_events(r, p)) + '\n').encode()


def test_independent_buffer_formula_and_serial_order():
    p = policy(); rows = [row(mode=0), row(mode=1), row(status=6)]
    assert v.buffers(rows[0]) == [2520, 40, 280, 360, 1512, 63, 252, 252, 252]
    result = v.compare(log(rows, p), rows, p, 'python')
    assert result['kinds'] == dict(upload=27, launch=3, download=15)
    assert v.call_events(row(status=5), p) == []
    assert v.call_events(row(status=3, entry=False), p) == []
    assert len(v.call_events(row(status=3), p)) == 15


@pytest.mark.parametrize('change', ['drop', 'extra', 'device', 'bytes', 'function', 'file', 'line',
    'variable', 'unknown', 'nul', 'utf8', 'cap', 'key', 'duplicate', 'blank', 'threadid', 'launch-bytes'])
def test_fail_closed_notifications(change):
    p = policy(); rows = [row()]; raw = log(rows, p)
    lines = raw.decode().splitlines()
    if change == 'drop': raw = ('\n'.join(lines[:-1]) + '\n').encode()
    elif change == 'extra': raw += (lines[9] + '\n').encode()
    elif change == 'device': raw = raw.replace(b'device=0', b'device=1', 1)
    elif change == 'bytes': raw = raw.replace(b'bytes=2520', b'bytes=2521', 1)
    elif change == 'function': raw = raw.replace(b'function=upload_rho', b'function=evil', 1)
    elif change == 'file': raw = raw.replace(b'source.f90', b'wrong.f90', 1)
    elif change == 'line': raw = raw.replace(b'line=100', b'line=999', 1)
    elif change == 'variable': raw = raw.replace(b'variable=x', b'variable=y', 1)
    elif change == 'unknown': raw += b'alloc CUDA data bytes=8\n'
    elif change == 'nul': raw += b'\x00'
    elif change == 'utf8': raw += b'\xff'
    elif change == 'cap': raw = b'x' * (v.CAP + 1)
    elif change == 'key': raw = raw.replace(b'bytes=2520', b'bytes=2520 unreviewed=1', 1)
    elif change == 'duplicate': raw = raw.replace(b'device=0', b'device=0 device=0', 1)
    elif change == 'blank': raw += b'\n'
    elif change == 'threadid': raw = raw.replace(b'threadid=97', b'threadid=097', 1)
    elif change == 'launch-bytes': raw = raw.replace(b'block=128', b'block=128 bytes=8', 1)
    with pytest.raises((v.Rejected, UnicodeError)):
        v.compare(raw, rows, p, 'python')


def test_interleaving_has_only_aggregate_scope():
    p = policy(); rows = [row(mode=0), row(mode=1)]
    events = list(reversed([event for r in rows for event in v.call_events(r, p)]))
    raw = ('\n'.join(notice(event, p) for event in events) + '\n').encode()
    assert v.compare(raw, rows, p, 'pthread')['kinds']['launch'] == 2
    with pytest.raises(v.Rejected):
        v.compare(raw, rows, p, 'python')


def test_metadata_must_be_explicit_counted_and_at_proven_site():
    p = policy(); rows = [row()]
    raw = log(rows, p)
    with pytest.raises(v.Rejected):
        v.compare((notice(('metadata', 128), p) + '\n').encode() + raw, rows, p, 'python')
    p['metadata'] = [dict(gap=9, site='metadata', bytes=128, proof='invented fixed compiler metadata')]
    assert v.compare(log(rows, p), rows, p, 'python')['notices'] == 16
    wrong = log(rows, p).replace(b'bytes=128', b'bytes=129')
    with pytest.raises(v.Rejected):
        v.compare(wrong, rows, p, 'python')


@pytest.mark.parametrize('raw', [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":"\x00"}', b'\xff'])
def test_json_rejects_ambiguous_inputs(raw):
    with pytest.raises((v.Rejected, ValueError)):
        v.parse_json(raw)


def write_json(path, data):
    path.write_text(json.dumps(data), encoding='utf-8')
    return v.fingerprint(path)


def rebind_capture(bundle_path, policy_ref=None, receipt_ref=None):
    """Keep transport hashes coherent, so semantic tamper tests reach that gate."""
    bundle = json.loads(bundle_path.read_text())
    capture_path = Path(bundle['controller_capture']['path'])
    capture = json.loads(capture_path.read_text())
    for key, value in [('policy', policy_ref), ('receipt_check', receipt_ref)]:
        if value is not None:
            bundle[key] = capture[key] = value
    bundle['controller_capture'] = write_json(capture_path, capture)
    write_json(bundle_path, bundle)


def bundle_fixture(tmp_path):
    """Every artifact is invented and expressly non-executable."""
    p = policy()
    placeholder = tmp_path / 'non-executable-placeholder.txt'
    placeholder.write_text('INVENTED no native binary, no compiler, no GPU\n')
    fake = v.fingerprint(placeholder)
    p.update(schema_version=1, state='PREPARED', review='invented parser preparation only',
             group_order=['public', 'private'], evidence={name:fake for name in (
        'source', 'compiler_report', 'build_manifest', 'input_plan_source', 'receipt_verifier',
        'thread_verifier', 'controller', 'library', 'bridge', 'thread_binary', 'corpus', 'case_ids')})
    p['evidence']['trace_verifier'] = v.fingerprint(v.__file__)
    plan = dict(schema_version=1, public=[row('public-invented')], private=[row('private-invented', status=6)])
    p['plan'] = write_json(tmp_path / 'plan.json', plan)
    policy_ref = write_json(tmp_path / 'policy.json', p)
    artifacts = [fake]
    for group in ('public', 'private'):
        directory = tmp_path / group; directory.mkdir()
        options = directory / 'options.bin'
        options.write_bytes(b'\x01\0\0\0' + (40).to_bytes(4, 'little') + b'\x01\0\0\0' * 2 + bytes(24))
        optref = v.fingerprint(options)
        artifacts += [optref, write_json(directory / '0001.json', dict(kind='create', ordinal=1,
            library=fake, artifacts=dict(options=optref)))]
        spec = plan[group][0]
        artifacts.append(write_json(directory / '0002.json', dict(kind='evaluate', ordinal=2,
            case_id=spec['case_id'], shape=spec['shape'], input_shape=spec['input_shape'],
            status=spec['status'], context_id=1, library=fake)))
    receipt_ref = write_json(tmp_path / 'receipt-check.json', dict(schema_version=1, state='PASS', artifacts=artifacts))
    ids = [('concurrent', j, r) for j in (0, 1) for r in (0, 1)] + [('migration-new-thread', 0, 0), ('migration-main-thread', 0, 0)]
    calls = [dict(phase=phase, job=job, repeat=repeat, output_sha256='0'*64) for phase, job, repeat in ids]
    thread_rows = [dict(backend=1, entry=True, status=0, mode=int(job==0),
        shape=[7,5,9] if job else [5,7,9], input_shape=[7,5,9] if job else [5,7,9]) for _,job,_ in ids]
    pyerr = tmp_path / 'python.stderr'; pyerr.write_bytes(log(plan['public']+plan['private'], p))
    therr = tmp_path / 'pthread.stderr'; therr.write_bytes(log(thread_rows, p))
    pyref, thref = v.fingerprint(pyerr), v.fingerprint(therr)
    thread_ref = write_json(tmp_path / 'thread-check.json', dict(schema_version=1, state='PASS',
        artifacts=dict(stderr=thref, binary=fake, library=fake, stdout=fake), calls=calls))
    capture = dict(schema_version=1, state='COMPLETED', policy=policy_ref, controller=fake,
        receipt_check=receipt_ref, thread_check=thread_ref, python_stderr=pyref, thread_stderr=thref,
        capture_no=True, plugin_autoload_disabled=True, group_order=['public','private'],
        python_exit=0, thread_exit=0, timed_out=False)
    capture_ref = write_json(tmp_path / 'capture.json', capture)
    bundle = {key:capture[key] for key in ('schema_version','policy','receipt_check','thread_check','python_stderr','thread_stderr')}
    bundle['controller_capture'] = capture_ref
    write_json(tmp_path / 'bundle.json', bundle)
    return tmp_path / 'policy.json', policy_ref['sha256'], tmp_path / 'bundle.json'


def test_full_compare_prepared_never_claims_pass(tmp_path):
    args = bundle_fixture(tmp_path)
    report = v.verify(*args)
    assert report['state'] == 'PREPARED'
    assert report['python']['kinds']['launch'] == 2
    assert report['pthread']['kinds']['launch'] == 6


@pytest.mark.parametrize('change', ['policy-hash', 'source-hash', 'upstream-missing', 'not-tested',
    'raw-hash', 'capture', 'mode', 'shape', 'field-entry', 'frozen-too-small'])
def test_bundle_rejects_unbound_or_incomplete_inputs(tmp_path, change):
    policy_path, digest, bundle_path = bundle_fixture(tmp_path)
    p = json.loads(policy_path.read_text()); b = json.loads(bundle_path.read_text())
    if change == 'policy-hash': digest = '0'*64
    elif change == 'source-hash':
        Path(p['evidence']['source']['path']).write_text('changed')
    elif change == 'upstream-missing': b.pop('receipt_check'); write_json(bundle_path, b)
    elif change == 'not-tested':
        path = Path(b['receipt_check']['path']); report = json.loads(path.read_text()); report['state']='NOT_TESTED'
        rebind_capture(bundle_path, receipt_ref=write_json(path, report))
    elif change == 'raw-hash': Path(b['python_stderr']['path']).write_bytes(b'changed')
    elif change == 'capture':
        path=Path(b['controller_capture']['path']); data=json.loads(path.read_text()); data['capture_no']=False
        b['controller_capture']=write_json(path,data); write_json(bundle_path,b)
    else:
        plan_path=Path(p['plan']['path']); plan=json.loads(plan_path.read_text())
        if change == 'mode': plan['public'][0]['mode']=0
        elif change == 'shape': plan['public'][0]['shape']=[1,7,8]
        elif change == 'field-entry': plan['public'][0]['entry']=False
        elif change == 'frozen-too-small': p['state']='FROZEN'
        p['plan']=write_json(plan_path,plan); policy_ref=write_json(policy_path,p); digest=policy_ref['sha256']
        rebind_capture(bundle_path, policy_ref=policy_ref)
    with pytest.raises((v.Rejected, ValueError)):
        v.verify(policy_path, digest, bundle_path)


@pytest.mark.parametrize('change', ['bool-schema', 'extra-key', 'missing-proof', 'dynamic-function',
    'missing-source-site', 'extra-kernel', 'missing-metadata-proof', 'metadata-bytes-zero'])
def test_policy_exact_schema_and_review_requirements(tmp_path, change):
    policy_path, digest, bundle_path = bundle_fixture(tmp_path)
    p = json.loads(policy_path.read_text())
    if change == 'bool-schema': p['schema_version']=True
    elif change == 'extra-key': p['ignore_unknown']=True
    elif change == 'missing-proof': p['sites']['kernel']['proof']=''
    elif change == 'dynamic-function': p['sites']['kernel']['fields']['function']=None
    elif change == 'missing-source-site': p['sites']['kernel']['fields'].pop('line')
    elif change == 'extra-kernel': p['explicit']['launch']=['kernel','kernel']
    else:
        p['metadata']=[dict(gap=9,site='metadata',bytes=0 if change=='metadata-bytes-zero' else 128,
                            proof='' if change=='missing-metadata-proof' else 'invented')]
    ref=write_json(policy_path,p); rebind_capture(bundle_path,policy_ref=ref)
    with pytest.raises((v.Rejected, ValueError, TypeError)):
        v.verify(policy_path,ref['sha256'],bundle_path)


def test_frozen_inventory_has_exact_350_evaluations_272_regions():
    def make(count, active):
        return [row(str(i),entry=i<active) for i in range(count)]
    plan=dict(schema_version=1, public=make(295,238),private=make(55,34))
    v.plan_rows(plan, False)
    plan['public'][238]['entry']=True
    with pytest.raises(v.Rejected):
        v.plan_rows(plan,False)


def test_cli_creates_exclusive_prepared_report(tmp_path):
    policy_path, digest, bundle_path = bundle_fixture(tmp_path)
    out = tmp_path / 'result.json'
    args = ['--policy', str(policy_path), '--policy-sha256', digest, '--bundle', str(bundle_path), '--report', str(out)]
    assert v.main(args) == 2
    assert json.loads(out.read_text())['state'] == 'PREPARED'
    with pytest.raises(FileExistsError):
        v.main(args)
