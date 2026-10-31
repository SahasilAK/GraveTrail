"""Column scenes preserve trace facts while bounding only their display."""
import copy
import json

import pytest

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


@pytest.mark.parametrize('direction', ['upstream', 'downstream'])
def test_expression_arrows_follow_data_for_both_directions(direction):
    source, target = ref('source'), ref('target')
    result = scene(trace([step('sum', target, [source | {'role': 'value'}])], direction=direction),
                   target if direction == 'upstream' else source)
    assert {(e['source'], e['target']) for e in result['edges']} == {
        ('column:source', 'derivation:sum'), ('derivation:sum', 'column:target')}
    assert {n['kind'] for n in result['nodes']} == {'column', 'transformation'}
    assert all(e['effects'] == ['value'] for e in result['edges'])
    assert all(e['path'].startswith('M ') for e in result['edges'])
    assert result['trace_complete'] and not result['display_truncated']
    assert_closed(result)


def test_constant_has_no_fabricated_input_and_rowset_is_labeled():
    constant = scene(trace([step('constant', ref('target'), category='constant')]), ref('target'))
    assert len(constant['nodes']) == 2 and len(constant['edges']) == 1
    rowset = scene(trace([step('count', ref('target'), [ref('rows', name='') | {'role': 'rowset'}])]),
                   ref('target'))
    row_node = next(n for n in rowset['nodes'] if n['id'] == 'column:rows')
    assert 'rowset' in row_node['label'].lower()
    assert next(e for e in rowset['edges'] if e['source'] == row_node['id'])['roles'] == ['rowset']


def test_mixed_roles_and_effects_are_preserved_on_one_dependency_edge():
    paths = [dict(derivation_id='d', column_id='out', parent_column_id='in', depth=1, effect=effect)
             for effect in ('value', 'row_selection')]
    result = scene(trace([step('d', ref('out'), [ref('in') | {'role': role}
                                              for role in ('value', 'row_filter', 'value')])],
                         direction='downstream', paths=paths), ref('in'))
    dependency = next(e for e in result['edges'] if e['source'] == 'column:in')
    assert dependency['roles'] == ['row_filter', 'value']
    assert dependency['effects'] == ['row_selection', 'value']
    assert not dependency['context_only']
    assert len(result['edges']) == 2


def test_downstream_sibling_is_context_without_inventing_effects():
    result = scene(trace([step('d', ref('out'), [ref('in') | {'role': 'value'},
                                               ref('sibling') | {'role': 'join'}])],
                         direction='downstream'), ref('in'))
    sibling = next(e for e in result['edges'] if e['source'] == 'column:sibling')
    assert sibling['context_only'] and sibling['effects'] == []
    assert sibling['roles'] == ['join']
    assert len(result['nodes']) == 4


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


def test_cycles_keep_distinct_nodes_back_edges_and_deterministic_layout():
    steps = [step('first', ref('b'), [ref('a') | {'role': 'value'}]),
             step('second', ref('a'), [ref('b') | {'role': 'value'}]),
             step('exit', ref('c'), [ref('b') | {'role': 'value'}])]
    data = trace(steps)
    result = scene(data, ref('a'))
    assert len(result['edges']) == 6
    assert any(n['cycle'] for n in result['nodes'])
    assert any(e['cycle'] for e in result['edges'])
    assert len({(n['x'], n['y']) for n in result['nodes']}) == len(result['nodes'])
    assert result == scene(copy.deepcopy(data), ref('a'))
    assert_closed(result)


@pytest.mark.parametrize(('fan_in', 'caps'), [(1300, {}), (650, {}),
                                                  (4, {'max_nodes': 5}),
                                                  (4, {'max_edges': 4})])
def test_scene_caps_keep_whole_derivations(fan_in, caps):
    root = ref('root')
    steps = [step('a-small', root, [ref('small') | {'role': 'value'}]),
             step('z-big', root, [ref(f'input-{i}') | {'role': 'value'} for i in range(fan_in)])]
    result = scene(trace(steps), root, **caps)
    assert {n['id'] for n in result['nodes']} == {'column:root', 'column:small', 'derivation:a-small'}
    assert len(result['edges']) == 2
    assert result['display_truncated'] and result['trace_complete']
    assert result['omitted_derivations'] == 1
    assert result['omitted_nodes'] == fan_in + 1
    assert result['omitted_edges'] == fan_in + 1
    assert_closed(result)


def test_single_oversized_unit_keeps_only_root_and_unknown_root_is_empty():
    root = ref('root')
    result = scene(trace([step('large', root, [ref('a') | {'role': 'value'}])]), root, max_nodes=1)
    assert [n['id'] for n in result['nodes']] == ['column:root']
    assert result['edges'] == [] and result['omitted_nodes'] == 2
    empty = scene(trace(), None)
    assert empty['nodes'] == [] and empty['edges'] == []
    assert not empty['display_truncated']
    assert empty['bounds']['width'] > 0 and empty['bounds']['height'] > 0


def test_edge_cap_applies_when_shared_columns_fit_the_node_cap():
    root = ref('root')
    shared = [ref(f'input-{i}') | {'role': 'value'} for i in range(6)]
    result = scene(trace([step(f'd-{i:03}', root, shared) for i in range(200)]), root)
    assert len(result['nodes']) == 178
    assert len(result['edges']) == 1197
    assert result['omitted_derivations'] == result['omitted_nodes'] == 29
    assert result['omitted_edges'] == 203
    assert result['display_truncated'] and result['trace_complete']
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


def test_status_change_invalidates_identical_scene():
    data, root = trace([step('d', ref('root'))]), ref('root')
    all_status = scene(data, root, status='all')
    filtered = scene(data, root, status='verified')
    assert all_status['trace_key'] != filtered['trace_key']
    assert all_status['nodes'] == filtered['nodes'] and all_status['edges'] == filtered['edges']
    for field, value in [('workspace_id', 'other'), ('run_id', 'new'), ('depth', 4),
                         ('direction', 'downstream'), ('column', 'other')]:
        assert scene(data | {field: value}, root)['trace_key'] != all_status['trace_key']
    assert scene(data, root, max_nodes=10)['trace_key'] != all_status['trace_key']


def test_input_is_not_mutated_and_independent_components_do_not_overlap():
    data = trace([step('one', ref('a')), step('two', ref('b'))])
    before = copy.deepcopy(data)
    result = scene(data, ref('a'))
    assert data == before
    for i, node in enumerate(result['nodes']):
        for other in result['nodes'][i + 1:]:
            assert (node['x'] + node['width'] <= other['x'] or
                    other['x'] + other['width'] <= node['x'] or
                    node['y'] + node['height'] <= other['y'] or
                    other['y'] + other['height'] <= node['y'])


@pytest.mark.parametrize('kwargs', [{'status': 'bad'}, {'max_nodes': 0}, {'max_nodes': True},
                                  {'max_edges': -1}, {'max_edges': 2.5}])
def test_invalid_controls_are_rejected(kwargs):
    with pytest.raises(ValueError):
        build_column_scene(trace(), None, **kwargs)
