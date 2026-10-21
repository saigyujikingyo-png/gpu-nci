"""Compare original NVHPC notices with a pre-run policy; never execute candidates."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import sys

CAP = 16 * 1024 * 1024
TOTAL_CAP = 256 * 1024 * 1024
CONSTRUCTS = ('update', 'enter_data', 'compute', 'exit_data')
TRANSFER_KINDS = ('upload', 'download', 'alloc', 'delete', 'free')
NOTICE_KINDS = TRANSFER_KINDS + ('launch', 'wait') + tuple(
    direction + '_' + construct for direction in ('enter', 'leave') for construct in CONSTRUCTS)
FAILURE_PLAN = {**{f'fail-{n}': n for n in range(1, 19)},
                'control/pending-failure-consumed': 1, 'isolation/A-failure': 9}
SCOPE = ('Raw runtime notice comparison only; upstream receipt checks and trusted '
         'controller provenance are prerequisites. No scientific or performance acceptance; '
         'pthread notices are aggregate counts/byte multisets, not Linux-thread attribution. '
         'Physical alloc/free bytes and addresses are observations only, not allocator, '
         'private-buffer ownership, net balance or VRAM acceptance.')


class Rejected(ValueError):
    pass


def need(ok, message):
    if not ok:
        raise Rejected(message)


def keys(obj, expected, label):
    need(type(obj) is dict and set(obj) == set(expected), label + ': exact keys required')


def integer(value, low=0, high=(1 << 63) - 1):
    need(type(value) is int and low <= value <= high, 'integer out of range or boolean')
    return value


def read(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(CAP + 1)
    need(len(raw) <= CAP, 'parsed artifact exceeds 16 MiB')
    return raw


def utf8(raw):
    need(len(raw) <= CAP, 'parsed artifact exceeds 16 MiB')
    text = raw.decode('utf-8', errors='strict')
    need(not any(ord(c) < 32 and c not in '\t\r\n' for c in text), 'forbidden control character')
    need('\x7f' not in text, 'forbidden DEL character')
    return text


def parse_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    def constant(value):
        raise Rejected('nonfinite JSON constant: ' + value)
    return json.loads(utf8(raw), object_pairs_hook=pairs, parse_constant=constant)


def fingerprint(path):
    path = Path(path).resolve(strict=True)
    digest, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
            size += len(block)
            need(size <= TOTAL_CAP, 'artifact exceeds 256 MiB')
    return dict(path=str(path), sha256=digest.hexdigest(), bytes=size)


def receipt(item, checked):
    keys(item, ('path', 'sha256', 'bytes'), 'artifact')
    need(type(item['path']) is str and Path(item['path']).is_absolute(), 'absolute artifact path required')
    need(type(item['sha256']) is str and re.fullmatch('[0-9a-f]{64}', item['sha256']), 'SHA256 required')
    integer(item['bytes'])
    need(fingerprint(item['path']) == item, 'artifact path/hash/size mismatch: ' + item['path'])
    checked[item['path']] = item
    need(sum(x['bytes'] for x in checked.values()) <= TOTAL_CAP, 'total artifact cap')
    return Path(item['path'])


def shape(value):
    need(type(value) is list and len(value) == 3, 'three-dimensional shape required')
    for n in value:
        integer(n, 1, 17)
    return value


def plan_rows(plan, prepared):
    keys(plan, ('schema_version', 'public', 'private'), 'input plan')
    need(type(plan['schema_version']) is int and plan['schema_version'] == 1, 'plan schema')
    for group, total, regions in (('public', 295, 238), ('private', 55, 34)):
        rows = plan[group]
        need(type(rows) is list and rows, 'input plan list required')
        seen, active = set(), 0
        for row in rows:
            keys(row, ('case_id', 'mode', 'backend', 'shape', 'input_shape', 'status', 'entry', 'failure_at'), 'planned call')
            need(type(row['case_id']) is str and row['case_id'] and row['case_id'] not in seen, 'duplicate/empty case')
            seen.add(row['case_id'])
            integer(row['mode'], 0, 1); integer(row['backend'], 0, 1); integer(row['status'], 0, 6)
            shape(row['shape']); shape(row['input_shape'])
            need(type(row['entry']) is bool, 'entry boolean required')
            integer(row['failure_at'], 0, 18)
            need((row['failure_at'] > 0) == (row['status'] == 5), 'failure injection/status plan mismatch')
            if row['failure_at']:
                need(group == 'private' and row['entry'] and row['backend'] == 1, 'failure injection outside bridge entry')
            if not prepared:
                need(row['failure_at'] == (FAILURE_PLAN.get(row['case_id'], 0) if group == 'private' else 0), 'failure_at differs from independent configure plan')
            if row['entry'] and row['backend'] == 1:
                need(row['status'] in (0, 3, 4, 5, 6), 'unexpected backend-entry status')
            active += field_region(row)
        if not prepared:
            need(len(rows) == total and active == regions, 'finite input inventory/count mismatch')
            if group=='private':
                need({r['case_id'] for r in rows if r['failure_at']} == set(FAILURE_PLAN), 'finite configure-plan cases missing/extra')


def field_region(row):
    return row['backend'] == 1 and row['entry'] and row['failure_at'] == 0


def device_acquisitions(row):
    if row['backend'] != 1 or not row['entry']:
        return 0
    return 9 if row['failure_at'] == 0 else max(row['failure_at'] - 10, 0)


def buffers(row):
    b, ny, nz = row['shape']
    n, nin = b * ny * nz, math.prod(row['input_shape'])
    return [8 * nin, 40 * b, 40 * ny, 40 * nz,
            (24 + 72 * row['mode']) * n, n, 4 * n, 4 * n, 4 * n]


def policy_check(policy, checked):
    keys(policy, ('schema_version', 'state', 'evidence', 'plan', 'group_order', 'sites',
                  'explicit', 'metadata', 'process_notices', 'review'), 'policy')
    need(type(policy['schema_version']) is int and policy['schema_version'] == 1, 'policy schema')
    need(policy['state'] in ('PREPARED', 'FROZEN'), 'policy state')
    prepared = policy['state'] != 'FROZEN'
    evidence = policy['evidence']
    keys(evidence, ('source', 'compiler_report', 'build_manifest', 'input_plan_source', 'control_plan_source',
                    'receipt_verifier', 'thread_verifier', 'trace_verifier', 'controller',
                    'library', 'bridge', 'thread_binary', 'corpus', 'case_ids'), 'policy evidence')
    for item in evidence.values():
        receipt(item, checked)
    need(evidence['trace_verifier'] == fingerprint(__file__), 'policy must bind this verifier')
    need(type(policy['review']) is str and policy['review'].strip(), 'independent source/compiler review required')
    need(policy['group_order'] == ['public', 'private'], 'only frozen public-then-private capture supported')
    plan_path = receipt(policy['plan'], checked)
    plan = parse_json(read(plan_path)); plan_rows(plan, prepared)
    sites = policy['sites']
    need(type(sites) is dict and sites, 'explicit runtime sites required')
    for name, site in sites.items():
        need(type(name) is str and name, 'site name')
        keys(site, ('kind', 'fields', 'proof'), 'site')
        need(site['kind'] in NOTICE_KINDS, 'site kind')
        need(type(site['proof']) is str and site['proof'].strip(), 'source/report site proof required')
        fields = site['fields']
        need(type(fields) is dict and {'file', 'function', 'line'} <= set(fields), 'site/source fields required')
        need(not {'device', 'threadid', 'bytes', 'devaddr'} & set(fields), 'reserved site fields')
        for key, value in fields.items():
            need(re.fullmatch('[a-z_][a-z0-9_]*', key), 'invalid notification key')
            if value is None:
                need(site['kind'] == 'launch' and key in ('num_gangs', 'num_workers', 'vector_length', 'grid', 'block'), 'unbounded dynamic metadata forbidden')
            else:
                need(type(value) is str and value and '\n' not in value and '\r' not in value and '\x00' not in value, 'fixed field value required')
        need(re.fullmatch('[1-9][0-9]*', fields['line'] or ''), 'positive source line required')
        if site['kind'] in ('alloc', 'delete'):
            need(fields == dict(file='(OpenACC API)', function='acc_malloc' if site['kind']=='alloc' else 'acc_free', line='1'), 'known allocation API fields required')
    need(sum(site['kind']=='delete' for site in sites.values()) == 1, 'exactly one logical acc_free delete site required')
    explicit = policy['explicit']
    keys(explicit, ('upload', 'launch', 'download'), 'explicit sites')
    need(type(explicit['upload']) is list and len(explicit['upload']) == 9, 'nine upload sites')
    need(type(explicit['download']) is list and len(explicit['download']) == 5, 'five download sites')
    for kind in explicit:
        names = [explicit[kind]] if kind == 'launch' else explicit[kind]
        for name in names:
            need(name in sites and sites[name]['kind'] == kind, 'explicit site kind/name')
    metadata = policy['metadata']
    need(type(metadata) is list, 'metadata list required, empty only after source/report review')
    for item in metadata:
        keys(item, ('gap', 'site', 'bytes', 'proof'), 'metadata')
        integer(item['gap'], 0, 15); integer(item['bytes'], 0, (1 << 31) - 1)
        need(item['site'] in sites and sites[item['site']]['kind'] not in ('launch','alloc','delete','free'), 'metadata/construct site')
        need((item['bytes'] > 0) == (sites[item['site']]['kind'] in ('upload','download')), 'metadata/construct byte shape')
        need(type(item['proof']) is str and item['proof'].strip(), 'metadata source/report proof required')
    keys(policy['process_notices'], ('python', 'pthread'), 'process notices')
    for stream in ('python', 'pthread'):
        keys(policy['process_notices'][stream], ('prefix', 'suffix'), 'process notice positions')
        for rows in policy['process_notices'][stream].values():
            need(type(rows) is list, 'process notice list')
            for item in rows:
                keys(item, ('site', 'bytes', 'proof'), 'process notice')
                need(item['site'] in sites and sites[item['site']]['kind'] not in ('launch','alloc','delete','free'), 'process notice site')
                integer(item['bytes'], 0, (1 << 31) - 1)
                need((item['bytes'] > 0) == (sites[item['site']]['kind'] in ('upload','download')), 'process notice bytes')
                need(type(item['proof']) is str and item['proof'].strip(), 'process notice proof')
    return plan, prepared


def payload(line):
    """NVHPC uses padded horizontal whitespace and positional Leave locations."""
    match = re.fullmatch(r'(upload|download|alloc|delete|free)[ \t]+CUDA[ \t]+data[ \t]+(.+)', line)
    if match:
        return match[1], match[2]
    match = re.fullmatch(r'launch[ \t]+CUDA[ \t]+kernel[ \t]+(.+)', line)
    if match:
        return 'launch', match[1]
    match = re.fullmatch(r'Implicit[ \t]+wait[ \t]+(.+)', line)
    if match:
        return 'wait', match[1]
    match = re.fullmatch(r'Enter[ \t]+(update[ \t]+construct|enter[ \t]+data[ \t]+construct|compute[ \t]+region|exit[ \t]+data[ \t]+construct)[ \t]+(.+)', line)
    if match:
        construct = '_'.join(match[1].split()[:-1])
        return 'enter_' + construct, match[2]
    match = re.fullmatch(r'Leave[ \t]+(update|enter[ \t]+data|compute|exit[ \t]+data)[ \t]+(.+)', line)
    if match:
        location = re.fullmatch(r'(.+)[ \t]+([^ \t:]+):([1-9][0-9]*)[ \t]+(.+)', match[2])
        need(location is not None, 'Leave source location grammar')
        return 'leave_' + '_'.join(match[1].split()), (
            f'file={location[1]} function={location[2]} line={location[3]} ' + location[4])
    raise Rejected('unknown runtime notification')


def parse_notice_rows(raw, sites):
    """One full line per notification; reject every unrecognised line/key/site."""
    result = []
    for line in utf8(raw).splitlines():
        need(line and line == line.strip(), 'blank/partial runtime notification')
        kind, tail = payload(line)
        tokens = list(re.finditer(r'(?:^|[ \t]+)([a-z_][a-z0-9_]*)=', tail))
        need(tokens and tokens[0].start() == 0, 'notification key/value grammar')
        fields = {}
        for index, token in enumerate(tokens):
            key = token[1]
            value = tail[token.end():tokens[index + 1].start() if index + 1 < len(tokens) else len(tail)]
            need(key not in fields and value and value == value.strip(), 'duplicate/empty notification field')
            fields[key] = value
        need(fields.pop('device', None) == '0', 'runtime device must be NVIDIA 0')
        tid = fields.pop('threadid', None)
        need(tid is not None and re.fullmatch(r'0|[1-9][0-9]*', tid), 'canonical runtime threadid required')
        size = fields.pop('bytes', None)
        address = fields.pop('devaddr', None)
        if kind in ('alloc', 'delete', 'free'):
            need(address is not None and re.fullmatch(r'0x[0-9a-fA-F]+', address) and 0 < int(address,16) <= (1 << 64)-1, 'nonzero 64-bit device address required')
        else:
            need(address is None, 'unexpected device address')
        if kind in TRANSFER_KINDS:
            need(size is not None and re.fullmatch('[1-9][0-9]*', size), 'canonical transfer byte count required')
            size = integer(int(size), 1)
            if kind in ('upload', 'download'):
                integer(size, 1, (1 << 31)-1)
        else:
            need(size is None, 'non-transfer notice must not carry bytes'); size = 0
        candidates = []
        for name, site in sites.items():
            if site['kind'] != kind or set(fields) != set(site['fields']):
                continue
            good = True
            for key, wanted in site['fields'].items():
                value = fields[key]
                if wanted is None:
                    # NVHPC launch dimensions, at most three canonical positive integers.
                    good &= re.fullmatch(r'[1-9][0-9]*(?:,[1-9][0-9]*){0,2}', value) is not None
                    if good:
                        good &= all(int(n) <= (1 << 31) - 1 for n in value.split(','))
                else:
                    good &= value == wanted
            if good:
                candidates.append(name)
        need(len(candidates) == 1, 'unknown/ambiguous runtime function, file, site or metadata')
        result.append(dict(site=candidates[0], kind=kind, bytes=size, devaddr=address, threadid=tid))
    return result


def parse_notices(raw, sites):
    return [(row['site'], row['bytes']) for row in parse_notice_rows(raw, sites)]


def call_events(row, policy):
    result = []
    if field_region(row):
        sizes = buffers(row); explicit = policy['explicit']
        base = list(zip(explicit['upload'], sizes)) + [(explicit['launch'], 0)] + list(zip(explicit['download'], sizes[4:]))
        for gap in range(16):
            result.extend((item['site'], item['bytes']) for item in policy['metadata'] if item['gap'] == gap)
            if gap < 15:
                result.append(base[gap])
    delete_site = next(name for name,site in policy['sites'].items() if site['kind']=='delete')
    # Source-reviewed logical cleanup count. Raw pooled bytes/address do not
    # identify a private array and are deliberately not substituted here.
    result.extend([(delete_site, 0)] * device_acquisitions(row))
    return result


def process_events(policy, stream, position):
    return [(item['site'], item['bytes']) for item in policy['process_notices'][stream][position]]


def compare(raw, rows, policy, stream):
    parsed = parse_notice_rows(raw, policy['sites'])
    actual = [(r['site'], 0 if r['kind']=='delete' else r['bytes']) for r in parsed if r['kind'] not in ('alloc','free')]
    expected = process_events(policy, stream, 'prefix')
    for row in rows:
        expected.extend(call_events(row, policy))
    expected.extend(process_events(policy, stream, 'suffix'))
    if stream == 'python':
        need(actual == expected, 'serial runtime site/byte sequence differs from verified input order')
    else:
        need(Counter(actual) == Counter(expected), 'pthread runtime aggregate site/count/byte multiset mismatch')
    counts = Counter(r['kind'] for r in parsed)
    observed = {kind:dict(count=sum(r['kind']==kind for r in parsed),
        bytes=sum(r['bytes'] for r in parsed if r['kind']==kind),
        addresses=sorted({r['devaddr'] for r in parsed if r['kind']==kind})) for kind in ('alloc','delete','free')}
    return dict(notices=len(parsed), kinds=dict(counts), runtime_api_observations=observed,
                logical_delete_phase='serial cleanup per planned call' if stream=='python' else 'aggregate only',
                upload_bytes=sum(n for name, n in actual if policy['sites'][name]['kind'] == 'upload'),
                download_bytes=sum(n for name, n in actual if policy['sites'][name]['kind'] == 'download'))


def upstream(item, checked):
    report = parse_json(read(receipt(item, checked)))
    need(type(report) is dict and report.get('state') == 'PASS' and type(report.get('schema_version')) is int and report['schema_version'] == 1, 'upstream result is not PASS')
    artifacts = report.get('artifacts')
    need(type(artifacts) in (list, dict), 'upstream artifacts missing')
    artifacts = list(artifacts.values()) if type(artifacts) is dict else artifacts
    need(artifacts, 'empty upstream artifacts')
    for record in artifacts:
        receipt(record, checked)
    return report, {record['path']: record for record in artifacts}


def bind_python(plan, paths, policy, checked):
    result = []
    for group in policy['group_order']:
        # Artifacts have already been independently accepted by verify_receipts.
        library = policy['evidence']['library' if group == 'public' else 'bridge']
        wanted = {row['case_id']: row for row in plan[group]}
        records, json_records = [], {}
        for path in paths:
            file = Path(path)
            if file.parent.name == group and re.fullmatch(r'[0-9]{4}\.json', file.name):
                record = parse_json(read(file))
                need(record['ordinal'] not in json_records, 'ambiguous receipt group/ordinal')
                json_records[record['ordinal']] = record
                if record.get('kind') == 'evaluate':
                    records.append(record)
        records.sort(key=lambda row: integer(row['ordinal'], 1))
        need(len(records) == len(wanted), 'upstream evaluated inventory missing/extra')
        actual_failures, pending = {}, {}
        if group == 'private':
            for ordinal,record in sorted(json_records.items()):
                cid = record.get('context_id')
                if record['kind']=='create':
                    pending[ordinal]=0
                elif record['kind']=='private-configure' and record['status']==0:
                    need(cid in pending, 'configure context missing')
                    pending[cid]=record['failure_at']
                elif record['kind']=='evaluate':
                    need(record['case_id'] in wanted, 'unknown evaluated case')
                    if wanted[record['case_id']]['entry']:
                        need(cid in pending, 'evaluation context missing')
                        actual_failures[ordinal]=pending[cid]
                        pending[cid]=0
                    else:
                        actual_failures[ordinal]=0
        seen = set()
        for record in records:
            name = record['case_id']
            need(name in wanted and name not in seen, 'unplanned/duplicate verified case')
            seen.add(name); spec = wanted[name]
            need(spec['failure_at'] == (actual_failures[record['ordinal']] if group=='private' else 0), 'independent failure_at plan differs from verified configure receipts')
            need(record['library'] == library, 'verified evaluation binary differs from policy')
            for key in ('status', 'shape', 'input_shape'):
                need(record[key] == spec[key], 'verified evaluation differs from frozen input plan')
            # The validated create/options record binds backend/mode. Read only its
            # 40-byte ABI bytes; never import ctypes or load a shared library.
            create = json_records.get(record['context_id'])
            need(create is not None and create['kind'] == 'create', 'validated create missing')
            need(create['library'] == library, 'create binary differs from policy')
            options = create['artifacts']['options']
            need(options['path'] in paths and paths[options['path']] == options, 'unbound options')
            data = read(receipt(options, checked)); need(len(data) == 40, 'options ABI bytes')
            # ABI v1 Linux x86_64: version/size/backend/mode are four int32.
            need(int.from_bytes(data[8:12], 'little', signed=True) == spec['backend'] and
                 int.from_bytes(data[12:16], 'little', signed=True) == spec['mode'], 'mode/backend plan mismatch')
            result.append(spec)
    return result


def verify(policy_path, policy_sha256, bundle_path):
    checked = {}
    need(re.fullmatch('[0-9a-f]{64}', policy_sha256 or ''), 'pre-frozen policy SHA256 required')
    raw = read(policy_path)
    need(hashlib.sha256(raw).hexdigest() == policy_sha256, 'frozen policy hash mismatch')
    receipt(fingerprint(policy_path), checked)
    policy = parse_json(raw); plan, prepared = policy_check(policy, checked)
    bundle = parse_json(read(bundle_path)); receipt(fingerprint(bundle_path), checked)
    keys(bundle, ('schema_version', 'policy', 'receipt_check', 'thread_check', 'python_stderr',
                  'thread_stderr', 'controller_capture'), 'capture bundle')
    need(type(bundle['schema_version']) is int and bundle['schema_version'] == 1, 'bundle schema')
    need(bundle['policy'] == fingerprint(policy_path), 'capture policy binding differs')
    _, python_paths = upstream(bundle['receipt_check'], checked)
    thread_report, thread_paths = upstream(bundle['thread_check'], checked)
    for key in ('library', 'bridge', 'corpus', 'case_ids'):
        item = policy['evidence'][key]
        need(python_paths.get(item['path']) == item, 'upstream/policy provenance mismatch: ' + key)
    for key, report_key in (('library', 'library'), ('thread_binary', 'binary')):
        need(thread_report['artifacts'].get(report_key) == policy['evidence'][key], 'thread binary/library policy mismatch')
    need(thread_report['artifacts'].get('stderr') == bundle['thread_stderr'], 'thread stderr not bound upstream')
    for key in ('python_stderr', 'thread_stderr'):
        receipt(bundle[key], checked)
    capture = parse_json(read(receipt(bundle['controller_capture'], checked)))
    keys(capture, ('schema_version', 'state', 'policy', 'controller', 'receipt_check', 'thread_check',
                   'python_stderr', 'thread_stderr', 'capture_no', 'plugin_autoload_disabled',
                   'group_order', 'python_exit', 'thread_exit', 'timed_out'), 'controller capture')
    need(type(capture['schema_version']) is int and capture['schema_version'] == 1 and capture['state'] == 'COMPLETED', 'controller capture incomplete')
    for key in ('policy', 'receipt_check', 'thread_check', 'python_stderr', 'thread_stderr'):
        need(capture[key] == bundle[key], 'controller capture binding mismatch: ' + key)
    need(capture['controller'] == policy['evidence']['controller'], 'controller source mismatch')
    need(capture['capture_no'] is True and capture['plugin_autoload_disabled'] is True and
         capture['timed_out'] is False and capture['group_order'] == policy['group_order'], 'capture ordering/settings not frozen')
    need(type(capture['python_exit']) is int and capture['python_exit'] == 0 and
         type(capture['thread_exit']) is int and capture['thread_exit'] == 0, 'nonzero/missing process exit')
    python_rows = bind_python(plan, python_paths, policy, checked)
    calls = thread_report.get('calls')
    need(type(calls) is list and len(calls) == 6, 'verified pthread calls missing')
    # Accepted pthread fixture: four diagnostic job-0 calls, two FULL job-1 calls.
    identities = {('concurrent', j, r) for j in (0, 1) for r in (0, 1)} | {
        ('migration-new-thread', 0, 0), ('migration-main-thread', 0, 0)}
    need({(c['phase'], c['job'], c['repeat']) for c in calls} == identities, 'pthread fixture identities')
    thread_rows = [dict(backend=1, entry=True, status=0, failure_at=0, mode=int(c['job'] == 0),
                        shape=[7, 5, 9] if c['job'] else [5, 7, 9],
                        input_shape=[7, 5, 9] if c['job'] else [5, 7, 9]) for c in calls]
    python_result = compare(read(bundle['python_stderr']['path']), python_rows, policy, 'python')
    thread_result = compare(read(bundle['thread_stderr']['path']), thread_rows, policy, 'pthread')
    # Rehash after parsing to detect ordinary changes during comparison.
    need(all(fingerprint(path) == item for path, item in checked.items()), 'artifact changed during verification')
    return dict(schema_version=1, state='PREPARED' if prepared else 'PASS', scope=SCOPE,
                policy_state=policy['state'], python=python_result, pthread=thread_result,
                artifacts=list(checked.values()))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('policy', 'bundle', 'report'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--policy-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        report = verify(args.policy, args.policy_sha256, args.bundle)
        code = 0 if report['state'] == 'PASS' else 2
    except (Rejected, OSError, ValueError, KeyError, TypeError, OverflowError, RecursionError) as error:
        report = dict(schema_version=1, state='FAILED', scope=SCOPE, error=str(error)); code = 1
    with args.report.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(report, stream, indent=2, allow_nan=False); stream.write('\n')
    return code


if __name__ == '__main__':
    sys.exit(main())
