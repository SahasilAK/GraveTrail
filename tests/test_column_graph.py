"""Column scenes preserve trace facts while bounding only their display."""
import json

from dataforge.column_graph import build_column_scene


def ref(cid, *, table='table', name='id', scope='', version='', **extra):
    return dict(column_id=cid, asset_id=f'asset-{table}', table=table,
                column_name=name, scope=scope, version=version, **extra)


def step(did, target, inputs=(), *, category='expression', status='verified', **extra):
    return dict(derivation_id=did, target=target, inputs=list(inputs), category=category,
                status=status, expression='PRIVATE_EXPRESSION', coverage=[], **extra)


def trace(steps=(), *, direction='upstream', paths=None, **extra):
    if paths is None:
        paths = [dict(derivation_id=s['derivation_id'], column_id=s['target']['column_id'],
                      parent_column_id=(s['target']['column_id'] if direction == 'upstream'
                                        else s['inputs'][0]['column_id']), depth=1, effect='value')
                 for s in steps if direction == 'upstream' or s['inputs']]
    return dict(workspace_id='workspace', run_id='run', asset_id='asset', column='root',
                direction=direction, depth=5, complete=True, coverage=[], truncated=False,
                derivations=list(steps), paths=paths, **extra)


def scene(result, root, **kwargs):
    return build_column_scene(result, root, **kwargs)


def assert_closed(result):
    nodes = {n['id'] for n in result['nodes']}
    assert len(nodes) == len(result['nodes'])
    assert len({e['id'] for e in result['edges']}) == len(result['edges'])
    assert all(e['source'] in nodes and e['target'] in nodes for e in result['edges'])


def test_branch_scope_version_and_writer_identity_never_merge():
    target = ref('target')
    references = [ref('branch-a', scope='cte:first'), ref('branch-b', scope='cte:second'),
                  ref('sas-before', version='1'), ref('sas-after', version='2')]
    steps = [step(f'writer-{i}', target, [r | {'role': 'value'}], branch=i)
             for i, r in enumerate(references)]
    result = scene(trace(steps), target)
    assert len(result['nodes']) == 9 and len(result['edges']) == 8
    assert len({n['label'] for n in result['nodes'] if n['kind'] == 'column'}) == 5
    assert len([n for n in result['nodes'] if n['kind'] == 'transformation']) == 4
    assert_closed(result)


def test_scene_contains_no_source_text_and_preserves_coverage():
    data = trace([step('d', ref('root'), [ref('a') | {'role': 'value'}],
                       evidence={'code': 'PRIVATE_CODE', 'raw_content': 'PRIVATE_RAW'})])
    data['coverage'] = [{'reason': 'input_limit', 'derivation_id': 'd'}]
    data['complete'] = False
    result = scene(data, ref('root'))
    serialized = json.dumps(result)
    assert not any(secret in serialized for secret in ('PRIVATE_EXPRESSION', 'PRIVATE_CODE', 'PRIVATE_RAW'))
    assert all(f'"{key}":' not in serialized for key in ('expression', 'code', 'raw_content'))
    assert result['coverage'] == data['coverage'] and not result['trace_complete']
    assert not result['display_truncated']
