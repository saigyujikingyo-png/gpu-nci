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
    for kind,function in [('alloc','acc_malloc'),('delete','acc_free')]:
        sites[kind]=dict(kind=kind,fields=dict(file='(OpenACC API)',function=function,line='1'),proof='invented API source proof')
    sites['free']=dict(kind='free',fields=dict(file='/invented non-executable/source.f90',function='download_int32',line='999',queue='0'),proof='invented last runtime site proof')
    return dict(sites=sites, explicit=explicit, metadata=[], process_notices={
        key:dict(prefix=[], suffix=[]) for key in ('python', 'pthread')})


def row(name='invented', status=0, entry=True, mode=1, failure_at=0):
    return dict(case_id=name, mode=mode, backend=1, shape=[1, 7, 9], input_shape=[5, 7, 9], status=status, entry=entry,failure_at=failure_at)


def notice(item, p):
    site, size = item; rule = p['sites'][site]; kind = rule['kind']
    fields = {key: ('2' if value is None else value) for key, value in rule['fields'].items()}
    fields.update(device='0', threadid='97')
    if kind in v.TRANSFER_KINDS:
        fields['bytes'] = str(max(size,512) if kind in ('alloc','delete','free') else size)
    if kind in ('alloc','delete','free'):
        fields['devaddr']='0x1000'
    if kind.startswith('leave_'):
        construct=kind[6:].replace('_',' ')
        location=f"{fields.pop('file')} {fields.pop('function')}:{fields.pop('line')}"
        return 'Leave '+construct+' '+location+' '+' '.join(f'{key}={value}' for key,value in fields.items())
    if kind.startswith('enter_'):
        construct=kind[6:].replace('_',' ')
        prefix='Enter '+construct+(' region' if construct=='compute' else ' construct')
        return prefix+' '+' '.join(f'{key}={value}' for key,value in fields.items())
    if kind=='wait':
        return 'Implicit wait  '+' '.join(f'{key}={value}' for key,value in fields.items())
    prefix = 'launch CUDA kernel' if kind == 'launch' else kind + ' CUDA data'
    return prefix + ' ' + ' '.join(f'{key}={value}' for key, value in fields.items())


def log(rows, p):
    return ('\n'.join(notice(event, p) for r in rows for event in v.call_events(r, p)) + '\n').encode()


def test_independent_buffer_formula_and_serial_order():
    p = policy(); rows = [row(mode=0), row(mode=1), row(status=6)]
    assert v.buffers(rows[0]) == [2520, 40, 280, 360, 1512, 63, 252, 252, 252]
    result = v.compare(log(rows, p), rows, p, 'python')
    assert result['kinds'] == dict(upload=27, launch=3, download=15, delete=27)
    assert v.call_events(row(status=5,failure_at=1), p) == []
    assert v.call_events(row(status=3, entry=False), p) == []
    assert len(v.call_events(row(status=3), p)) == 24


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
    assert v.compare(log(rows, p), rows, p, 'python')['notices'] == 25
    wrong = log(rows, p).replace(b'bytes=128', b'bytes=129')
    with pytest.raises(v.Rejected):
        v.compare(wrong, rows, p, 'python')


def test_existing_m3b0_format_replay_is_not_m3b1_acceptance():
    """Deidentified formats read from accepted M3B0 logs; not an M3B1 run."""
    source='/invented archived M3B0/source.f90'
    examples=[
        ('alloc',f'alloc  CUDA data  devaddr=0x1000 bytes=512 file=(OpenACC API) function=acc_malloc line=1 device=0 threadid=1',
         dict(file='(OpenACC API)',function='acc_malloc',line='1')),
        ('delete',f'delete CUDA data  devaddr=0x1000 bytes=512 file=(OpenACC API) function=acc_free line=1 device=0 threadid=1',
         dict(file='(OpenACC API)',function='acc_free',line='1')),
        ('free',f'free   CUDA data  devaddr=0x1000 bytes=512 file={source} function=download_marker line=570 device=0 threadid=1 queue=0',
         dict(file=source,function='download_marker',line='570',queue='0')),
        ('enter_update',f'Enter update construct file={source} function=upload_real line=552 device=0 threadid=1 queue=0',
         dict(file=source,function='upload_real',line='552',queue='0')),
        ('upload',f'upload CUDA data  file={source} function=upload_real line=552 device=0 threadid=1 variable=values(:) bytes=136',
         dict(file=source,function='upload_real',line='552',variable='values(:)')),
        ('wait',f'Implicit wait  file={source} function=upload_real line=552 device=0 threadid=1 queue=acc_async_sync',
         dict(file=source,function='upload_real',line='552',queue='acc_async_sync')),
        ('leave_update',f'Leave update {source} upload_real:552 device=0 threadid=1',
         dict(file=source,function='upload_real',line='552')),
        ('enter_enter_data',f'Enter enter data construct file={source} function=add_one line=582 device=0 threadid=1 queue=0',
         dict(file=source,function='add_one',line='582',queue='0')),
        ('leave_enter_data',f'Leave enter data {source} add_one:582 device=0 threadid=1',
         dict(file=source,function='add_one',line='582')),
        ('enter_compute',f'Enter compute region file={source} function=add_one line=582 device=0 threadid=1',
         dict(file=source,function='add_one',line='582')),
        ('launch',f'launch CUDA kernel  file={source} function=add_one line=582 device=0 threadid=1 num_gangs=1 num_workers=1 vector_length=128 grid=1 block=128',
         dict(file=source,function='add_one',line='582',num_gangs='1',num_workers='1',vector_length='128',grid='1',block='128')),
        ('leave_compute',f'Leave compute {source} add_one:582 device=0 threadid=1',
         dict(file=source,function='add_one',line='582')),
        ('enter_exit_data',f'Enter exit data construct file={source} function=add_one line=582 device=0 threadid=1',
         dict(file=source,function='add_one',line='582')),
        ('leave_exit_data',f'Leave exit data {source} add_one:587 device=0 threadid=1',
         dict(file=source,function='add_one',line='587')),
        ('download',f'download CUDA data  file={source} function=download_real line=564 device=0 threadid=1 variable=values(:) bytes=136',
         dict(file=source,function='download_real',line='564',variable='values(:)'))]
    sites={str(i):dict(kind=kind,fields=fields,proof='deidentified old M3B0 format replay only')
           for i,(kind,_,fields) in enumerate(examples)}
    raw=('\n'.join(line for _,line,_ in examples)+'\n').encode()
    rows=v.parse_notice_rows(raw,sites)
    assert [row['kind'] for row in rows]==[kind for kind,_,_ in examples]
    assert rows[0]['devaddr']=='0x1000' and rows[0]['bytes']==512
    assert rows[4]['bytes']==136 and rows[10]['bytes']==0
    with pytest.raises(v.Rejected):
        v.parse_notice_rows(raw.replace(b'queue=0',b'queue=99',1),sites)
    with pytest.raises(v.Rejected):
        v.parse_notice_rows(raw.replace(b'0x1000',b'0x0',1),sites)


def test_construct_waits_and_distinct_leave_lines_have_exact_sequence():
    p=policy(); fields=dict(p['sites']['upload_rho']['fields']); fields.pop('variable')
    for kind in ('enter_update','wait','leave_update'):
        sitefields=dict(fields)
        if kind=='enter_update':sitefields['queue']='0'
        if kind=='wait':sitefields['queue']='acc_async_sync'
        if kind=='leave_update':sitefields['line']='101'
        p['sites'][kind]=dict(kind=kind,fields=sitefields,proof='invented compiler/source construct proof')
    p['metadata']=[dict(gap=gap,site=kind,bytes=0,proof='invented fixed construct')
                   for gap,kind in [(0,'enter_update'),(1,'wait'),(1,'leave_update')]]
    raw=log([row()],p)
    assert v.compare(raw,[row()],p,'python')['kinds']['wait']==1
    with pytest.raises(v.Rejected):
        v.compare(raw.replace(b'upload_rho:101',b'upload_rho:100'),[row()],p,'python')


def test_logical_cleanup_counts_and_phase_from_preplanned_failure():
    p=policy()
    for failure in range(1,19):
        r=row(f'fail-{failure}',status=5,failure_at=failure)
        assert len(v.call_events(r,p))==max(failure-10,0)
        raw=log([r],p) if failure>10 else b''
        assert v.compare(raw,[r],p,'python')['runtime_api_observations']['delete']['count']==max(failure-10,0)
    raw=log([row()],p); lines=raw.splitlines()
    wrong=b'\n'.join([lines[-1],*lines[:-1]])+b'\n'
    with pytest.raises(v.Rejected):v.compare(wrong,[row()],p,'python')
    with pytest.raises(v.Rejected):v.compare(raw+b'\n'.join(lines[-1:])+b'\n',[row()],p,'python')


def test_physical_api_observed_only_without_allocator_or_int32_assumptions():
    p=policy(); raw=log([row()],p)
    # Deliberately unmatched addresses and >INT32 bytes: no pooling/rounding or
    # address-to-private-array claim is made by this observation boundary.
    alloc=notice(('alloc',1<<33),p).replace('0x1000','0x2000')
    free=notice(('free',1<<34),p).replace('0x1000','0x3000')
    result=v.compare((alloc+'\n').encode()+raw+(free+'\n').encode(),[row()],p,'python')
    assert result['runtime_api_observations']['alloc']==dict(count=1,bytes=1<<33,addresses=['0x2000'])
    assert result['runtime_api_observations']['free']['bytes']==1<<34
    for bad in [b'devaddr=0x0',b'devaddr=bogus',b'devaddr=0x10000000000000000']:
        with pytest.raises(v.Rejected):
            v.compare((alloc+'\n').encode().replace(b'devaddr=0x2000',bad)+raw,[row()],p,'python')


@pytest.mark.parametrize('padding',['  ','\t',' \t '])
def test_cuda_notices_accept_horizontal_padding(padding):
    p=policy(); raw=log([row()],p)
    raw=raw.replace(b' CUDA ',padding.encode()+b'CUDA'+padding.encode())
    raw=raw.replace(b'data file',b'data'+padding.encode()+b'file')
    raw=raw.replace(b'kernel file',b'kernel'+padding.encode()+b'file')
    assert v.compare(raw,[row()],p,'python')['notices']==24


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
        'source', 'compiler_report', 'build_manifest', 'input_plan_source', 'control_plan_source', 'receipt_verifier',
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
    thread_rows = [dict(backend=1, entry=True, status=0, failure_at=0, mode=int(job==0),
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


def test_failure_plan_must_match_verified_configure_receipts(tmp_path):
    policy_path,digest,bundle_path=bundle_fixture(tmp_path)
    bundle=json.loads(bundle_path.read_text()); path=Path(bundle['receipt_check']['path'])
    report=json.loads(path.read_text()); directory=tmp_path/'private'
    evaluate_path=directory/'0002.json'; evaluation=json.loads(evaluate_path.read_text())
    evaluation['ordinal']=3
    configure=dict(kind='private-configure',ordinal=2,status=0,context_id=1,failure_at=1)
    report['artifacts']=[item for item in report['artifacts'] if item['path']!=str(evaluate_path)]
    report['artifacts'] += [write_json(evaluate_path,configure),write_json(directory/'0003.json',evaluation)]
    rebind_capture(bundle_path,receipt_ref=write_json(path,report))
    with pytest.raises(v.Rejected,match='independent failure_at plan'):
        v.verify(policy_path,digest,bundle_path)


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
    private=make(34,34)+[row(name,status=5,failure_at=n) for name,n in v.FAILURE_PLAN.items()]+[row('preflight',entry=False)]
    plan=dict(schema_version=1, public=make(295,238),private=private)
    v.plan_rows(plan, False)
    assert sum(v.device_acquisitions(r) for group in ('public','private') for r in plan[group])==2484
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
