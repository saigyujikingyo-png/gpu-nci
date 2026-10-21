"""Invented static ELF names and text fixtures only. Never load a library."""
import pytest

from test_pure import policy, row, log, notice, bundle_fixture, v


def static_policy():
    p = policy()
    p['schema_version'] = 2
    for name in ('static_a', 'static_b'):
        p['sites'][name] = dict(kind='upload', fields=dict(variable='_st_invented_' + name),
                               proof='invented non-executable compiler registration')
    p['static_prefix'] = {stream: [dict(site=name, bytes=144, proof='invented registration and runtime walk')
        for _ in range(modules) for name in ('static_a', 'static_b')]
        for stream, modules in (('python', 2), ('pthread', 1))}
    return p


def prefix(p, stream):
    return ('\n'.join(notice((x['site'], x['bytes']), p) for x in p['static_prefix'][stream]) + '\n').encode()


def test_v2_static_prefix_multiset_preserves_ordinary_order():
    p = static_policy(); rows = [row()]
    for stream in ('python', 'pthread'):
        pre = prefix(p, stream)
        result = v.compare(pre + log(rows, p), rows, p, stream)
        assert result['kinds']['upload'] == 9 + len(p['static_prefix'][stream])
        assert result['upload_bytes'] == sum(v.buffers(rows[0])) + 144 * len(p['static_prefix'][stream])
        shuffled = b'\n'.join(reversed(pre.splitlines())) + b'\n'
        assert v.compare(shuffled + log(rows, p), rows, p, stream) == result
    ordinary = log(rows, p).splitlines()
    with pytest.raises(v.Rejected):
        v.compare(prefix(p, 'python') + b'\n'.join(reversed(ordinary)) + b'\n', rows, p, 'python')


@pytest.mark.parametrize('change', ('missing', 'extra', 'symbol', 'size', 'late', 'after-alloc',
                                  'file', 'key', 'nonupload', 'wrong-stream'))
def test_v2_static_prefix_rejects_unknowns_and_placement(change):
    p = static_policy(); rows = [row()]
    pre = prefix(p, 'python'); ordinary = log(rows, p)
    raw = pre + ordinary
    if change == 'missing': raw = b'\n'.join(pre.splitlines()[1:]) + b'\n' + ordinary
    elif change == 'extra': raw = pre + pre.splitlines()[0] + b'\n' + ordinary
    elif change == 'symbol': raw = raw.replace(b'_st_invented_static_a', b'_st_unreviewed', 1)
    elif change == 'size': raw = raw.replace(b'bytes=144', b'bytes=145', 1)
    elif change == 'late': raw = pre + ordinary + pre.splitlines()[0] + b'\n'
    elif change == 'after-alloc': raw = (notice(('alloc', 512), p) + '\n').encode() + raw
    elif change == 'file': raw = raw.replace(b'bytes=144', b'bytes=144 file=invented', 1)
    elif change == 'key': raw = raw.replace(b'bytes=144', b'bytes=144 unreviewed=1', 1)
    elif change == 'nonupload': raw = raw.replace(b'upload CUDA data', b'download CUDA data', 1)
    elif change == 'wrong-stream': raw = prefix(p, 'pthread') + ordinary
    with pytest.raises(v.Rejected): v.compare(raw, rows, p, 'python')


def bound_v2_fixture(tmp_path):
    path, _, bundle = bundle_fixture(tmp_path)
    p = static_policy()
    old = v.parse_json(path.read_bytes())
    for key in ('state', 'review', 'group_order', 'evidence', 'plan'):
        p[key] = old[key]
    fake = old['evidence']['source']
    p['runtime'] = dict(native_wrapper=fake, libraries={key: fake for key in ('host', 'device', 'notify')})
    return p


def test_v2_exact_runtime_binding_and_schema(tmp_path):
    p = bound_v2_fixture(tmp_path)
    checked = {}
    _, prepared = v.policy_check(p, checked)
    assert prepared and p['runtime']['native_wrapper']['path'] in checked
    p['runtime']['libraries']['host'] = dict(p['runtime']['libraries']['host'], sha256='0' * 64)
    with pytest.raises(v.Rejected): v.policy_check(p, {})


@pytest.mark.parametrize('change', ('duplicate-symbol', 'wrong-size', 'nonupload', 'with-location',
                                  'explicit', 'metadata', 'process', 'extra-runtime', 'wrong-cardinality'))
def test_v2_schema_cannot_place_statics_elsewhere(tmp_path, change):
    p = bound_v2_fixture(tmp_path)
    if change == 'duplicate-symbol': p['static_prefix']['pthread'][1]['site'] = 'static_a'
    elif change == 'wrong-size': p['static_prefix']['python'][0]['bytes'] = 145
    elif change == 'nonupload': p['sites']['static_a']['kind'] = 'download'
    elif change == 'with-location': p['sites']['static_a']['fields']['file'] = 'invented'
    elif change == 'explicit': p['explicit']['upload'][0] = 'static_a'
    elif change == 'metadata': p['metadata'] = [dict(p['static_prefix']['pthread'][0], gap=0)]
    elif change == 'process': p['process_notices']['python']['suffix'] = [p['static_prefix']['pthread'][0]]
    elif change == 'extra-runtime': p['runtime']['libraries']['unknown'] = p['runtime']['native_wrapper']
    elif change == 'wrong-cardinality': p['static_prefix']['python'].pop()
    with pytest.raises(v.Rejected): v.policy_check(p, {})
