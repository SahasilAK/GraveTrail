"""Nested query repairs and deliberately bounded PostgreSQL writes."""
import json
from contextlib import closing

import pytest

from dataforge.ingestion import Importer
from dataforge.parsers.sql import parse_sql
from dataforge.services import analyze
from dataforge.store import Store
from dataforge.transformations import trace_columns


def records(sql, dialect="", *, named=False):
    return [d for op in parse_sql(sql, dialect).operations for d in op.derivations
            if not named or d['target_column'] != '*']


@pytest.mark.parametrize('dialect,alias,reference,status', [
    ('postgres', '"X"', 'x', 'unresolved'),
    ('postgres', 'MiXeD', '"mixed"', 'verified'),
    ('snowflake', 'mixed', '"MIXED"', 'verified'),
    ('snowflake', '"mixed"', 'mixed', 'unresolved'),
])
@pytest.mark.parametrize('source', ['src AS {alias}', '(SELECT a FROM src) AS {alias}'])
def test_transformation_aliases_follow_dialect_quoting(dialect, alias, reference, status, source):
    sql = f'CREATE TABLE dst AS SELECT {reference}.a FROM {source.format(alias=alias)}'
    output = next(d for d in records(sql, dialect) if d['target_table'] == 'dst')
    assert output['status'] == status
    assert bool(output['inputs']) == (status == 'verified')


def test_colliding_normalized_aliases_do_not_verify_or_drop_sources():
    output = records('CREATE TABLE dst AS SELECT x.a FROM src AS x '
                     'JOIN other AS X ON x.id = X.id', 'postgres')[-1]
    assert output['status'] == 'unresolved'
    assert {i['table'] for i in output['inputs'] if i['role'] == 'rowset'} == {'src', 'other'}
    assert not any(i['role'] == 'value' for i in output['inputs'])


@pytest.mark.parametrize('alias,reference,status', [
    ('mixed', '"MIXED"', 'verified'),
    ('"mixed"', 'mixed', 'unresolved'),
])
def test_intermediate_columns_follow_snowflake_quoting(alias, reference, status):
    sql = f'CREATE TABLE dst AS WITH c AS (SELECT a AS {alias} FROM src) SELECT {reference} FROM c'
    output = records(sql, 'snowflake')[-1]
    assert output['status'] == status
    if status == 'verified':
        assert output['inputs'][0]['column'] == alias
    else:
        assert not output['inputs']


def test_snowflake_intermediate_quote_matching_preserves_trace_identity(tmp_path):
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('Quoted intermediate')
        store.set_setting(workspace, 'dialect', 'snowflake')
        Importer(store, workspace).files([('quoted.sql', b'CREATE TABLE dst AS '
            b'WITH c AS (SELECT a AS mixed FROM src) SELECT "MIXED" FROM c')], {'.sql'})
        analyze(store, workspace)
        target = next(a['asset_id'] for a in store.assets(workspace) if a['name'] == 'dst')
        result = trace_columns(store, workspace, target, '"MIXED"')
        assert result['complete'] and len(result['derivations']) == 2
        assert any(i['table'] == 'src' and i['column_name'] == 'a'
                   for d in result['derivations'] for i in d['inputs'])


@pytest.mark.parametrize("modifier,dialect", [("LIMIT 1", ""), ("OFFSET 1", ""),
                                             ("USING SAMPLE 1 ROWS", "duckdb")])
@pytest.mark.parametrize("side", ["left", "right"])
def test_nested_set_modifier_never_silently_verifies(modifier, dialect, side):
    nested = f"(SELECT a FROM src UNION ALL SELECT a FROM other {modifier})"
    if dialect == 'duckdb':
        nested = f"((SELECT a FROM src UNION ALL SELECT a FROM other) {modifier})"
    query = f"{nested} UNION ALL SELECT a FROM third" if side == "left" else f"SELECT a FROM third UNION ALL {nested}"
    result = records(f"CREATE TABLE dst AS {query}", dialect)
    affected = [d for d in result if any(i['table'] in {'src', 'other'} for i in d['inputs'])]
    assert len(affected) == 2
    assert all(d['status'] == 'unresolved' and d['coverage'] for d in affected)
    unaffected = next(d for d in result if any(i['table'] == 'third' for i in d['inputs']))
    assert unaffected['status'] == 'verified'


@pytest.mark.parametrize("nested", [
    "unused AS (SELECT a FROM hidden UNION SELECT a FROM hidden2)",
    "unused AS (WITH inner_unused AS (SELECT a FROM hidden UNION SELECT a FROM hidden2) SELECT a FROM hidden3)",
])
def test_unused_union_cte_does_not_stop_trace(tmp_path, nested):
    sql = f"CREATE TABLE dst AS WITH {nested} SELECT a FROM src; CREATE TABLE fin AS SELECT a FROM dst"
    assert all(d['status'] == 'verified' for d in records(sql))
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('nested')
        Importer(store, workspace).files([('nested.sql', sql.encode())], {'.sql'})
        analyze(store, workspace)
        assert not any(a['name'].startswith('hidden') for a in store.assets(workspace))
        source = next(a['asset_id'] for a in store.assets(workspace) if a['name'] == 'src')
        result = trace_columns(store, workspace, source, 'a', direction='downstream')
        assert {d['target']['table'] for d in result['derivations']} == {'dst', 'fin'}
        assert result['complete']


def test_reachable_distinct_union_and_parenthesized_leaf_controls():
    distinct = records('CREATE TABLE dst AS (SELECT a FROM src UNION SELECT a FROM other) UNION ALL SELECT a FROM third')
    assert [d['status'] for d in distinct] == ['unresolved', 'unresolved', 'verified']
    leaf = records('CREATE TABLE dst AS (SELECT a FROM src LIMIT 1) UNION ALL SELECT a FROM other')
    assert [d['status'] for d in leaf] == ['unresolved', 'verified']


@pytest.mark.parametrize('query,expected', [
    ('SELECT a FROM src UNION ALL SELECT a FROM other', ['verified', 'verified']),
    ('SELECT a FROM src UNION SELECT a FROM other', ['unresolved', 'unresolved']),
    ('SELECT DISTINCT a, SUM(b) AS s FROM src GROUP BY 1 LIMIT 1', ['unresolved', 'unresolved']),
    ('SELECT DISTINCT a, SUM(b) AS s FROM src GROUP BY 1', ['verified', 'verified']),
])
def test_used_cte_keeps_own_context_and_ignores_nested_unused_union(query, expected):
    sql = f'''CREATE TABLE dst AS WITH used AS (
        WITH unused AS (SELECT a FROM hidden UNION SELECT a FROM hidden2)
        {query}) SELECT a FROM used'''
    result = records(sql)
    assert not any(i['table'].startswith('hidden') for d in result for i in d['inputs'])
    assert [d['status'] for d in result if d['scope']] == expected
    assert result[-1]['target_table'] == 'dst' and result[-1]['status'] == 'verified'
    assert all(len(d['coverage']) == len(set(d['coverage'])) for d in result)


def test_unused_union_cte_dbt_materialization(tmp_path):
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('dbt nested')
        Importer(store, workspace).files([
            ('demo/dbt_project.yml', b'name: demo\n'),
            ('demo/models/dst.sql', b'WITH unused AS (SELECT a FROM hidden UNION SELECT a FROM hidden2) SELECT a FROM src'),
            ('demo/models/fin.sql', b"SELECT a FROM {{ ref('dst') }}"),
        ], set(), source_kind='dbt')
        analyze(store, workspace)
        source = next(a['asset_id'] for a in store.assets(workspace) if a['name'] == 'src')
        result = trace_columns(store, workspace, source, 'a', direction='downstream')
        assert {d['target']['table'] for d in result['derivations']} == {'dst', 'fin'}
        assert result['complete']


def test_update_assignments_use_simultaneous_operation_prior_values():
    result = records('UPDATE t SET a = b, b = a WHERE active=1', 'postgres', named=True)
    assert [d['target_column'] for d in result] == ['a', 'b']
    assert [d['expression'] for d in result] == ['a = b', 'b = a']
    assert [[i['column'] for i in d['inputs'] if i['role'] == 'value'] for d in result] == [['b'], ['a']]
    for d in result:
        assert d['status'] == 'unresolved' and d['coverage']
        assert all(i['scope'] == 'update:prior' and i['version'] == 'prior' for i in d['inputs'])
        assert {i['column'] for i in d['inputs'] if i['role'] == 'row_filter'} == {'active'}
        assert {i['column'] for i in d['inputs'] if i['role'] == 'rowset'} == {''}


def test_update_literal_and_simple_arithmetic_keep_exact_evidence():
    result = records('UPDATE t AS x SET a = -12, b = (x.c /* old */ + 2)', 'postgres', named=True)
    assert [d['target_column'] for d in result] == ['a', 'b']
    assert [d['expression'] for d in result] == ['a = -12', 'b = (x.c /* old */ + 2)']
    assert result[0]['category'] == 'constant'
    assert result[1]['inputs'][0]['column'] == 'c'


@pytest.mark.parametrize('sql,dialect', [
    ('UPDATE t SET a=b FROM other', 'postgres'),
    ('UPDATE t SET a=(SELECT b FROM other)', 'postgres'),
    ('UPDATE t SET a=b RETURNING a', 'postgres'),
    ('UPDATE t SET (a,b)=(b,a)', 'postgres'),
    ('UPDATE t SET a=DEFAULT', 'postgres'),
    ('UPDATE t SET a=unknown(b)', 'postgres'),
    ('UPDATE t SET a=b, a=c', 'postgres'),
    ('UPDATE t SET a=other.b', 'postgres'),
    ('UPDATE t SET a=b', 'mysql'),
])
def test_unsupported_updates_remain_explicit_whole_statement_boundaries(sql, dialect):
    result = records(sql, dialect)
    assert len(result) == 1 and result[0]['target_column'] == '*'
    assert result[0]['status'] == 'unresolved' and result[0]['coverage']
    assert result[0]['inputs'] == []


def test_insert_single_literal_row_maps_explicit_order_and_exact_spans():
    sql = 'INSERT INTO t ("B", a, c, d) VALUES (NULL, \'a,b\', -12.5, TRUE)'
    result = records(sql, 'postgres', named=True)
    assert [d['target_column'] for d in result] == ['"B"', 'a', 'c', 'd']
    assert [d['expression'] for d in result] == ['NULL', "'a,b'", '-12.5', 'TRUE']
    assert all(d['category'] == 'constant' and d['inputs'] == [] for d in result)
    assert all(d['status'] == 'unresolved' and any('prior' in c.lower() for c in d['coverage']) for d in result)
    assert all(sql[d['_expression_offset']:].startswith(d['expression']) for d in result)


@pytest.mark.parametrize('sql', [
    'INSERT INTO t(a) VALUES (1),(2)',
    'INSERT INTO t VALUES (1)',
    'INSERT INTO t(a,a) VALUES (1,2)',
    'INSERT INTO t(a,b) VALUES (1)',
    'INSERT INTO t(a) VALUES (DEFAULT)',
    'INSERT INTO t(a) VALUES (1+2)',
    'INSERT INTO t(a) VALUES (random())',
    'INSERT INTO t(a) VALUES ((SELECT a FROM src))',
    'INSERT INTO t(a) VALUES (1) ON CONFLICT DO NOTHING',
    'INSERT INTO t(a) VALUES (1) RETURNING a',
])
def test_unsupported_values_never_gain_verified_or_named_mapping(sql):
    result = records(sql, 'postgres')
    assert len(result) == 1 and result[0]['target_column'] == '*'
    assert result[0]['status'] == 'unresolved' and result[0]['coverage']


def test_values_other_dialect_retains_unsupported_boundary():
    result = records('INSERT INTO t(a) VALUES(1)', 'mysql')
    assert len(result) == 1 and result[0]['target_column'] == '*'
    assert result[0]['status'] == 'unresolved'


@pytest.mark.parametrize('modifier,dialect', [('LIMIT 1', ''), ('OFFSET 1', ''),
                                            ('USING SAMPLE 1 ROWS', 'duckdb')])
def test_nested_modifiers_stay_incomplete_after_persistence(tmp_path, modifier, dialect):
    nested = f'(SELECT a FROM src UNION ALL SELECT a FROM other {modifier})'
    if dialect == 'duckdb':
        nested = f'((SELECT a FROM src UNION ALL SELECT a FROM other) {modifier})'
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('persist modifiers')
        store.set_setting(workspace, 'dialect', dialect)
        Importer(store, workspace).files([('nested.sql', f'CREATE TABLE dst AS {nested} UNION ALL SELECT a FROM third'.encode())], {'.sql'})
        analyze(store, workspace)
        target = next(a['asset_id'] for a in store.assets(workspace) if a['name'] == 'dst')
        result = trace_columns(store, workspace, target, 'a')
        assert not result['complete']
        assert sum(d['status'] == 'unresolved' for d in result['derivations']) == 2


def test_mutation_prior_values_are_isolated_across_operations_and_reopen(tmp_path):
    path = tmp_path / 'home'
    with closing(Store(path)) as store:
        workspace = store.create_workspace('writes')
        store.set_setting(workspace, 'dialect', 'postgres')
        sql = 'UPDATE t SET a=b, b=a WHERE active=1; UPDATE t SET a=c; INSERT INTO t(a) VALUES (5)'
        Importer(store, workspace).files([('writes.sql', sql.encode())], {'.sql'})
        analyze(store, workspace)
        target = next(a['asset_id'] for a in store.assets(workspace) if a['name'] == 't')
        result = trace_columns(store, workspace, target, 'a', include_source=True)
        assert not result['complete'] and len(result['derivations']) == 3
        assert any(c['reason'] == 'multiple_writers' for c in result['coverage'])
        targets = {d['target']['column_id'] for d in result['derivations']}
        prior = [i for d in result['derivations'] for i in d['inputs']]
        assert all(i['column_id'] not in targets and i['scope'] == 'update:prior' and i['version'] == 'prior' for i in prior)
        assert len({i['column_id'] for i in prior if i['role'] == 'rowset'}) == 2
        prior_trace = trace_columns(store, workspace, target, prior[0]['column_id'])
        assert not prior_trace['complete']
        assert any(c['reason'] == 'unresolved_scope' for c in prior_trace['coverage'])
        assert all(sql.find(d['expression']) >= 0 and d['evidence']['source_hash'] for d in result['derivations'])
        assert not any(c['reason'] == 'cycle' for c in result['coverage'])
        assert not trace_columns(store, workspace, target, 'untouched')['complete']
        identities = {d['derivation_id'] for d in result['derivations']}
        assert analyze(store, workspace)['analyzed'] == 0
    with closing(Store(path)) as store:
        reopened = trace_columns(store, workspace, target, 'a', include_source=True)
        assert {d['derivation_id'] for d in reopened['derivations']} == identities
        analyze(store, workspace, force=True)
        assert {d['derivation_id'] for d in trace_columns(store, workspace, target, 'a')['derivations']} == identities


def test_previous_parser_cache_reanalysis_publishes_literal_targets(tmp_path, monkeypatch):
    from dataforge import services

    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('parser upgrade')
        store.set_setting(workspace, 'dialect', 'postgres')
        Importer(store, workspace).files([('row.sql', b'INSERT INTO t(a) VALUES (NULL)')], {'.sql'})
        with monkeypatch.context() as previous:
            previous.setattr(services, 'PARSER_VERSION', '16')
            analyze(store, workspace)
        target = next(a['asset_id'] for a in store.assets(workspace) if a['name'] == 't')
        stale = trace_columns(store, workspace, target, 'a')
        assert any(c['reason'] == 'reanalysis_required' for c in stale['coverage'])
        refreshed = analyze(store, workspace)
        assert refreshed['analyzed'] == 1 and refreshed['cached'] == 0
        result = trace_columns(store, workspace, target, 'a')
        assert len(result['derivations']) == 1 and result['derivations'][0]['expression'] == 'NULL'
        assert not result['complete']
        assert not any(c['reason'] == 'reanalysis_required' for c in result['coverage'])


def test_bounded_mutations_preserve_scene_evidence_and_agent_redaction(tmp_path):
    from dataforge.agent.service import AgentService
    from dataforge.column_evidence import load_column_evidence
    from dataforge.column_graph import build_column_scene

    sql = "UPDATE t SET a=b WHERE active=1; INSERT INTO t(a) VALUES ('PRIVATE_LITERAL_415')"
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('mutation boundaries')
        store.set_setting(workspace, 'dialect', 'postgres')
        Importer(store, workspace).files([('writes.sql', sql.encode())], {'.sql'})
        analyze(store, workspace)
        target = next(a['asset_id'] for a in store.assets(workspace) if a['name'] == 't')
        result = trace_columns(store, workspace, target, 'a')
        scene = build_column_scene(result, result['derivations'][0]['target'])
        assert not scene['trace_complete']
        assert {n['derivation_id'] for n in scene['nodes'] if n['kind'] == 'transformation'} == {
            d['derivation_id'] for d in result['derivations']}
        assert 'PRIVATE_LITERAL_415' not in json.dumps(scene)
        columns = [n['id'] for n in scene['nodes'] if n['kind'] == 'column']
        assert len(columns) == len(set(columns)) == 4
        for derivation in result['derivations']:
            detail = load_column_evidence(store, workspace, result['run_id'], derivation['derivation_id'], include_file=True)
            assert detail['expression'] == derivation['expression']
            assert detail['file']['raw_content'] == sql
            assert detail['file']['content_hash'] == derivation['evidence']['source_hash']
        with closing(AgentService(store)) as service:
            store.set_setting(workspace, 'agent_access', {'allow_source': False})
            summary = service.call('column_lineage', workspace, asset='t', column='a')
            assert len(summary['items']) == 2
            assert all('expression' not in d and 'code' not in d['evidence'] for d in summary['items'])
            assert 'PRIVATE_LITERAL_415' not in json.dumps(summary)


@pytest.mark.parametrize('write', ['UPDATE t SET a=b', 'INSERT INTO t(a) VALUES (1)'])
def test_unassigned_known_target_columns_keep_prior_row_boundary(tmp_path, write):
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('unassigned column')
        store.set_setting(workspace, 'dialect', 'postgres')
        Importer(store, workspace).files([('partial.sql', f'{write}; CREATE TABLE fin AS SELECT untouched FROM t'.encode())], {'.sql'})
        analyze(store, workspace)
        target = next(a['asset_id'] for a in store.assets(workspace) if a['name'] == 't')
        result = trace_columns(store, workspace, target, 'untouched')
        assert not result['complete']
        assert any(c['reason'] == 'unresolved_scope' for c in result['coverage'])
