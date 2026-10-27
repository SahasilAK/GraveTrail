import json
from pathlib import Path
from typing import Any

import pytest

from dataforge.ingestion import Importer
from dataforge.models import AssetRef, Operation, ParseResult
from dataforge.services import analyze
from dataforge.store import Store


def populate(tmp_path: Path, sql: str) -> tuple[Any, ...]:
    """Populate the test inputs required by the scenario.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        sql: SQL source text for the test case.

    Returns:
        Value produced for the test scenario.
    """
    store = Store(tmp_path / 'home')
    workspace = store.create_workspace('Columns')
    Importer(store, workspace).files([('a.sql', sql.encode())], {'.sql'})
    analyze(store, workspace)
    return store, workspace


def asset_id(store: Any, workspace: Any, name: str) -> Any:
    """Return asset id for the test scenario.

    Args:
        store: Store instance exercised by the test.
        workspace: Workspace used by the test.
        name: Name value used by the test case.

    Returns:
        Value produced for the test scenario.
    """
    return next(a['asset_id'] for a in store.assets(workspace) if a['name'] == name)


def test_group_by_ordinal_downstream_and_parser_upgrade(tmp_path, monkeypatch):
    from dataforge import services
    from dataforge.transformations import trace_columns

    store, w = populate(tmp_path, 'CREATE TABLE dst AS SELECT a, SUM(b) AS s FROM src GROUP BY 1')
    try:
        result = trace_columns(store, w, asset_id(store, w, 'src'), 'a', direction='downstream')
        assert {d['target']['column_name'] for d in result['derivations']} == {'a', 's'}
        assert analyze(store, w)['analyzed'] == 0
        monkeypatch.setattr(services, 'PARSER_VERSION', 'future-parser')
        assert any(c['reason'] == 'reanalysis_required' for c in trace_columns(
            store, w, asset_id(store, w, 'src'), 'a')['coverage'])
        assert analyze(store, w)['analyzed'] == 1
        assert not any(c['reason'] == 'reanalysis_required' for c in trace_columns(
            store, w, asset_id(store, w, 'src'), 'a')['coverage'])
    finally:
        store.close()


@pytest.mark.parametrize('context', ['WHERE s.a > 0', 'JOIN other o ON s.a=o.a'])
def test_downstream_preserves_value_and_filter_effects(tmp_path, context):
    from dataforge.transformations import trace_columns

    store, w = populate(tmp_path, f'''CREATE TABLE dst AS SELECT s.a FROM src s {context};
        CREATE TABLE fin AS SELECT a FROM dst;''')
    try:
        result = trace_columns(store, w, asset_id(store, w, 'src'), 'a', direction='downstream')
        assert len(result['derivations']) == 2
        for step in result['derivations']:
            assert {p['effect'] for p in result['paths'] if p['derivation_id'] == step['derivation_id']} == {
                'value', 'row_selection'}
        limited = trace_columns(store, w, asset_id(store, w, 'src'), 'a', direction='downstream', limit=1)
        assert limited['truncated'] and not limited['complete']
    finally:
        store.close()


def test_derivation_parser_cache_roundtrip() -> None:
    """Verify that derivation parser cache roundtrip."""
    derivation = {'target_table': 'b', 'target_column': 'id', 'expression': 'id',
                  'inputs': [{'table': 'a', 'column': 'id', 'role': 'value'}]}
    parsed = ParseResult(operations=[Operation('CREATE', [AssetRef('a')], [AssetRef('b')],
                                               'CREATE TABLE b AS SELECT id FROM a', 1, 1,
                                               derivations=[derivation])])
    assert ParseResult.from_dict(json.loads(json.dumps(parsed.to_dict()))).operations[0].derivations == [derivation]
    legacy = parsed.to_dict()
    del legacy['operations'][0]['derivations']
    assert ParseResult.from_dict(legacy).operations[0].derivations == []


def test_value_context_constant_and_transitive_paths(tmp_path: Path) -> None:
    """Verify that value context constant and transitive paths.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.transformations import column_catalog, trace_columns

    store, w = populate(tmp_path, '''CREATE TABLE stage AS
        SELECT o.quantity * o.price AS gross, 42 AS answer
        FROM orders o JOIN discounts d ON o.id=d.id WHERE o.status='COMPLETE';
        CREATE TABLE mart AS SELECT gross + 1 AS total FROM stage;''')
    target = asset_id(store, w, 'stage')
    result = trace_columns(store, w, target, 'gross')
    direct = result['derivations'][0]
    assert {(i['table'], i['column_name']) for i in direct['inputs'] if i['role'] == 'value'} == {
        ('orders', 'quantity'), ('orders', 'price')}
    assert {'row_filter', 'join'} <= {i['role'] for i in direct['inputs']}
    constant = trace_columns(store, w, target, 'answer')
    assert constant['state'] == 'constant'
    assert not [i for i in constant['derivations'][0]['inputs'] if i['role'] == 'value']
    total = trace_columns(store, w, asset_id(store, w, 'mart'), 'total', depth=5)
    assert {d['target']['column_name'] for d in total['derivations']} >= {'total', 'gross'}
    assert all(d['run_id'] == total['run_id'] for d in total['derivations'])
    assert all(d['evidence']['source_hash'] == store.files(w)[0]['content_hash'] for d in total['derivations'])
    assert 'code' not in total['derivations'][0]['evidence']
    assert {c['column_name'] for c in column_catalog(store, w, target)} >= {'gross', 'answer'}
    impact = trace_columns(store, w, asset_id(store, w, 'orders'), 'status', direction='downstream')
    assert impact['paths'] and all(p['effect'] == 'row_selection' for p in impact['paths'])
    store.close()


def test_limits_cycles_multiwriter_and_workspace_isolation(tmp_path: Path) -> None:
    """Verify that limits cycles multiwriter and workspace isolation.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.transformations import trace_columns

    store, w = populate(tmp_path, '''CREATE TABLE b AS SELECT id FROM a;
        CREATE TABLE c AS SELECT id FROM b; CREATE TABLE a AS SELECT id FROM c;''')
    result = trace_columns(store, w, asset_id(store, w, 'c'), 'id', depth=10)
    assert any(c['reason'] == 'cycle' for c in result['coverage'])
    limited = trace_columns(store, w, asset_id(store, w, 'c'), 'id', depth=1)
    assert limited['truncated'] and any(c['reason'] == 'depth_limit' for c in limited['coverage'])
    with pytest.raises(ValueError):
        trace_columns(store, store.create_workspace('Other'), asset_id(store, w, 'c'), 'id')
    with pytest.raises(ValueError):
        trace_columns(store, w, asset_id(store, w, 'c'), 'id', depth=31)
    store.close()


def test_reanalysis_failed_parse_preserves_committed_derivations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that reanalysis failed parse preserves committed derivations.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    from dataforge import services
    from dataforge.models import Diagnostic
    from dataforge.transformations import trace_columns

    store, w = populate(tmp_path, 'CREATE TABLE b AS SELECT id FROM a;')
    target = asset_id(store, w, 'b')
    before = trace_columns(store, w, target, 'id')
    monkeypatch.setattr(services, '_parse_inventory', lambda *args: ParseResult(
        diagnostics=[Diagnostic('SQL parse failed', severity='error')]))
    with pytest.raises(ValueError, match='previous'):
        analyze(store, w, force=True)
    assert trace_columns(store, w, target, 'id')['derivations'] == before['derivations']
    store.close()


def test_cleanup_backup_restore_and_additive_migration(tmp_path: Path) -> None:
    """Verify that cleanup backup restore and additive migration.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.cleanup import apply_cleanup, cleanup_plan
    from dataforge.database_maintenance import backup, inspect_database, restore_backup
    from dataforge.transformations import trace_columns

    store, w = populate(tmp_path, 'CREATE TABLE b AS SELECT id FROM a;')
    target = asset_id(store, w, 'b')
    before = trace_columns(store, w, target, 'id')
    assert inspect_database(store)['ok']
    destination = tmp_path / 'restored'
    restore_backup(backup(store), destination)
    restored = Store(destination)
    assert trace_columns(restored, w, target, 'id')['derivations'] == before['derivations']
    restored.close()
    plan = cleanup_plan(store, w, 'columns')
    assert plan['records']['column_derivations']
    apply_cleanup(store, plan, 'Columns')
    assert not store.rows('SELECT * FROM column_references WHERE workspace_id=?', [w])
    assert inspect_database(store)['ok']
    assert trace_columns(store, w, target, 'id')['state'] == 'not_analyzed'
    store.close()


def test_declared_wildcard_and_insert_mapping_keep_uncertainty(tmp_path: Path) -> None:
    """Verify that declared wildcard and insert mapping keep uncertainty.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.transformations import trace_columns

    store, w = populate(tmp_path, '''CREATE TABLE src (a INT, b INT);
        CREATE TABLE dst (first INT, second INT);
        CREATE TABLE expanded AS SELECT * FROM src;
        INSERT INTO dst SELECT a, mystery(b) FROM src;''')
    result = trace_columns(store, w, asset_id(store, w, 'expanded'), 'a')
    assert result['derivations'][0]['status'] == 'inferred'
    assert result['derivations'][0]['inputs'][0]['column_name'] == 'a'
    first = trace_columns(store, w, asset_id(store, w, 'dst'), 'first')
    assert first['derivations'][0]['status'] == 'inferred'
    second = trace_columns(store, w, asset_id(store, w, 'dst'), 'second')
    assert second['derivations'][0]['status'] == 'unresolved'
    assert any('function' in c.get('message', '').lower() for c in second['coverage'])
    store.close()


def test_legacy_home_and_backup_upgrade_without_reanalysis(tmp_path: Path) -> None:
    """Verify that legacy home and backup upgrade without reanalysis.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.database_maintenance import backup, restore_backup
    from dataforge.store import COLUMN_TABLES
    from dataforge.transformations import trace_columns

    store, w = populate(tmp_path, 'CREATE TABLE b AS SELECT id FROM a;')
    target = asset_id(store, w, 'b')
    for table in COLUMN_TABLES:
        store.execute(f'DROP TABLE {table}')
    store.execute('DELETE FROM schema_migrations WHERE version=5')
    archive = backup(store)
    store.close()
    restore_backup(archive, tmp_path / 'legacy-restored')
    restored = Store(tmp_path / 'legacy-restored')
    assert restored.edges(w)
    assert trace_columns(restored, w, target, 'id')['state'] == 'not_analyzed'
    analyze(restored, w)
    assert trace_columns(restored, w, target, 'id')['state'] == 'known'
    restored.close()


def test_multiple_writers_and_source_replacement_do_not_mix_versions(tmp_path: Path) -> None:
    """Verify that multiple writers and source replacement do not mix versions.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.transformations import trace_columns

    store, w = populate(tmp_path, '''CREATE TABLE b AS SELECT id FROM a;
        INSERT INTO b (id) SELECT id FROM other;
        CREATE TABLE c AS SELECT id FROM b;''')
    target = asset_id(store, w, 'c')
    result = trace_columns(store, w, target, 'id')
    assert any(c['reason'] == 'multiple_writers' for c in result['coverage'])
    impact = trace_columns(store, w, asset_id(store, w, 'a'), 'id', direction='downstream')
    assert any(c['reason'] == 'multiple_writers' for c in impact['coverage'])
    assert {d['target']['table'] for d in impact['derivations']} == {'b'}
    before = result['run_id']
    Importer(store, w).files([('a.sql', b'CREATE TABLE b AS SELECT new_id AS id FROM changed; CREATE TABLE c AS SELECT id FROM b;')], {'.sql'})
    stale = trace_columns(store, w, target, 'id')
    assert any(c['reason'] == 'analysis_stale' for c in stale['coverage'])
    assert {d['run_id'] for d in stale['derivations']} == {before}
    analyze(store, w)
    fresh = trace_columns(store, w, target, 'id')
    assert fresh['run_id'] != before
    assert {i['table'] for d in fresh['derivations'] for i in d['inputs']} == {'b', 'changed'}
    store.close()


def test_known_derivation_does_not_hide_unsupported_writes(tmp_path: Path) -> None:
    """Verify that known derivation does not hide unsupported writes.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.transformations import trace_columns

    store, w = populate(tmp_path, '''CREATE TABLE dst AS SELECT a FROM src;
        UPDATE dst SET a=2; CREATE TABLE consumer AS SELECT a FROM dst;''')
    result = trace_columns(store, w, asset_id(store, w, 'dst'), 'a')
    assert not result['complete'] and result['state'] == 'unresolved'
    assert any(c['reason'] == 'unresolved_scope' for c in result['coverage'])
    impact = trace_columns(store, w, asset_id(store, w, 'src'), 'a', direction='downstream')
    assert not impact['complete']
    assert {d['target']['table'] for d in impact['derivations']} == {'dst'}
    store.close()


def test_converging_cycle_is_visible_with_bounded_state_traversal(tmp_path: Path) -> None:
    """Verify that converging cycle is visible with bounded state traversal.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.transformations import trace_columns

    store, w = populate(tmp_path, '''CREATE TABLE root AS SELECT a.x+b.x AS x FROM a CROSS JOIN b;
        CREATE TABLE a AS SELECT x FROM b; CREATE TABLE b AS SELECT x FROM a;''')
    result = trace_columns(store, w, asset_id(store, w, 'root'), 'x', depth=10)
    assert any(c['reason'] == 'cycle' for c in result['coverage'])
    assert not result['complete']
    store.close()


def test_trace_uses_identity_rules_of_committed_analysis(tmp_path: Path) -> None:
    """Verify that trace uses identity rules of committed analysis.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.transformations import trace_columns

    store = Store(tmp_path)
    w = store.create_workspace('Case sensitive')
    store.set_setting(w, 'case_sensitive', True)
    Importer(store, w).files([('a.sql', b'CREATE TABLE dst AS SELECT high AS A FROM src;')], {'.sql'})
    analyze(store, w)
    target = asset_id(store, w, 'dst')
    store.set_setting(w, 'case_sensitive', False)
    result = trace_columns(store, w, target, 'A')
    assert result['derivations'][0]['inputs'][0]['column_name'] == 'high'
    assert any(c['reason'] == 'analysis_settings_changed' for c in result['coverage'])
    assert not result['complete']
    store.close()


def test_path_output_cap_is_explicit_on_convergent_impact(tmp_path: Path) -> None:
    """Verify that path output cap is explicit on convergent impact.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.transformations import trace_columns

    code = 'CREATE TABLE st AS SELECT ' + ','.join(f'x AS a{i}' for i in range(6)) + ' FROM raw;'
    code += 'CREATE TABLE mid AS SELECT ' + ','.join(
        '+'.join(f'a{i}' for i in range(6)) + f' AS b{j}' for j in range(6)) + ' FROM st;'
    code += 'CREATE TABLE fin AS SELECT ' + '+'.join(f'b{i}' for i in range(6)) + ' AS c FROM mid;'
    store, w = populate(tmp_path, code)
    result = trace_columns(store, w, asset_id(store, w, 'raw'), 'x', direction='downstream', depth=10, limit=20)
    assert len(result['derivations']) == 13 and len(result['paths']) == 40
    assert result['truncated'] and not result['complete']
    assert any(c['reason'] == 'path_limit' for c in result['coverage'])
    store.close()


@pytest.mark.parametrize('case_sensitive', [False, True])
@pytest.mark.parametrize('sql', [
    'CREATE TABLE mid AS SELECT amount AS a FROM raw; CREATE TABLE dst AS SELECT "a" AS result FROM mid;',
    'CREATE TABLE dst AS WITH mid AS (SELECT amount AS a FROM raw) SELECT "a" AS result FROM mid;',
    'CREATE TABLE dst AS SELECT "a" AS result FROM (SELECT amount AS a FROM raw) mid;',
])
def test_equivalent_quoted_names_keep_complete_transitive_paths(tmp_path: Path, case_sensitive: bool, sql: str) -> None:
    """Verify that equivalent quoted names keep complete transitive paths.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        case_sensitive: Case sensitive value used by the test case.
        sql: SQL source text for the test case.
    """
    from dataforge.transformations import trace_columns

    store = Store(tmp_path)
    w = store.create_workspace('Quoted columns')
    store.set_setting(w, 'dialect', 'postgres')
    store.set_setting(w, 'case_sensitive', case_sensitive)
    Importer(store, w).files([('a.sql', sql.encode())], {'.sql'})
    analyze(store, w)
    trace = trace_columns(store, w, asset_id(store, w, 'dst'), 'result')
    assert {d['target']['table'] for d in trace['derivations']} == {'dst', 'mid'}
    assert trace['complete']
    reverse = trace_columns(store, w, asset_id(store, w, 'raw'), 'amount', direction='downstream')
    assert {d['target']['table'] for d in reverse['derivations']} == {'mid', 'dst'}
    store.close()


def test_quoted_case_is_preserved_through_declared_wildcards(tmp_path: Path) -> None:
    """Verify that quoted case is preserved through declared wildcards.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.transformations import trace_columns

    store, w = populate(tmp_path, '''CREATE TABLE src ("X" INT, "a" INT);
        CREATE TABLE mid AS SELECT * FROM src;
        CREATE TABLE dst AS SELECT "X" AS upper_value, a AS lower_value FROM mid;''')
    target = asset_id(store, w, 'dst')
    for column in ('upper_value', 'lower_value'):
        trace = trace_columns(store, w, target, column)
        assert {d['target']['table'] for d in trace['derivations']} == {'mid', 'dst'}
        assert next(d for d in trace['derivations'] if d['target']['table'] == 'mid')['status'] == 'inferred'
    assert trace_columns(store, w, asset_id(store, w, 'mid'), 'x')['state'] == 'no_known_dependency'
    store.close()


@pytest.mark.parametrize('condition', ['WHERE s.flag=1', 'JOIN other o ON s.flag=o.flag'])
def test_input_limits_do_not_change_downstream_effects(tmp_path: Path, condition: str) -> None:
    """Verify that input limits do not change downstream effects.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        condition: Condition value used by the test case.
    """
    from dataforge.transformations import trace_columns

    store, w = populate(tmp_path, f'CREATE TABLE dst AS SELECT s.x+s.y AS v FROM src s {condition};')
    source = asset_id(store, w, 'src')
    trace = trace_columns(store, w, source, 'flag', direction='downstream', limit=1)
    assert trace['paths'] and all(p['effect'] == 'row_selection' for p in trace['paths'])
    assert len(trace['derivations'][0]['inputs']) == 1 and trace['truncated']
    assert any(c['reason'] == 'input_limit' for c in trace['coverage'])
    value = trace_columns(store, w, source, 'x', direction='downstream', limit=1)
    assert value['paths'] and all(p['effect'] == 'value' for p in value['paths'])
    store.close()


def test_insert_wildcard_maps_expanded_positions_to_declared_targets(tmp_path: Path) -> None:
    """Verify that insert wildcard maps expanded positions to declared targets.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.transformations import column_catalog, trace_columns

    store, w = populate(tmp_path, '''CREATE TABLE src (a INT, b INT);
        CREATE TABLE dst (x INT, y INT); INSERT INTO dst SELECT * FROM src;''')
    target = asset_id(store, w, 'dst')
    assert {c['column_name'] for c in column_catalog(store, w, target)} == {'x', 'y'}
    for output, input_ in [('x', 'a'), ('y', 'b')]:
        trace = trace_columns(store, w, target, output)
        assert trace['state'] == 'known'
        step = trace['derivations'][0]
        assert step['status'] == 'inferred' and step['target']['column_name'] == output
        assert {(i['table'], i['column_name']) for i in step['inputs'] if i['role'] == 'value'} == {('src', input_)}
    store.close()


@pytest.mark.parametrize('target_ddl,projection', [
    ('', '*'),
    ('CREATE TABLE dst (x INT);', '*'),
    ('CREATE TABLE dst (x INT, y INT);', 's.*, 99 AS extra'),
])
def test_unmapped_insert_wildcards_do_not_invent_targets(tmp_path: Path, target_ddl: str, projection: str) -> None:
    """Verify that unmapped insert wildcards do not invent targets.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        target_ddl: Target ddl value used by the test case.
        projection: Projection value used by the test case.
    """
    from dataforge.transformations import column_catalog, trace_columns

    store, w = populate(tmp_path, f'''CREATE TABLE src (a INT, b INT); {target_ddl}
        INSERT INTO dst SELECT {projection} FROM src s;''')
    target = asset_id(store, w, 'dst')
    assert {c['column_name'] for c in column_catalog(store, w, target)} == {'*'}
    trace = trace_columns(store, w, target, 'x')
    assert trace['state'] == 'unresolved' and not trace['complete']
    assert any(c['reason'] == 'unresolved_scope' for c in trace['coverage'])
    store.close()


@pytest.mark.parametrize('spelling,expected', [
    ('a', 'a'), ('"a"', 'a'), ('`a`', 'a'), ('[a]', 'a'),
    ('A', 'a'), ('"A"', 'A'), ('"a""b"', 'a"b'), ('[a]]b]', 'a]b'),
])
def test_column_identity_unquotes_without_merging_distinct_case(spelling: str, expected: str) -> None:
    """Verify that column identity unquotes without merging distinct case.

    Args:
        spelling: Spelling value used by the test case.
        expected: Expected result for the test case.
    """
    from dataforge.models import column_key

    assert column_key(spelling) == 'column:' + expected
    assert column_key('A', case_sensitive=True) == 'column:A'


def test_previous_parser_cache_requires_refresh_and_is_replaced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that previous parser cache requires refresh and is replaced.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    from dataforge import services
    from dataforge.transformations import trace_columns

    with monkeypatch.context() as previous:
        previous.setattr(services, 'PARSER_VERSION', '10')
        store, w = populate(tmp_path, 'CREATE TABLE dst AS SELECT a FROM src;')
    target = asset_id(store, w, 'dst')
    old = trace_columns(store, w, target, 'a')
    assert not old['complete'] and any(c['reason'] == 'reanalysis_required' for c in old['coverage'])
    refresh = analyze(store, w)
    assert refresh['analyzed'] == 1 and refresh['cached'] == 0
    assert trace_columns(store, w, target, 'a')['complete']
    store.close()


def test_quoted_special_names_do_not_share_wildcard_or_rowset_identity() -> None:
    """Verify that quoted special names do not share wildcard or rowset identity."""
    from dataforge.models import column_key

    assert column_key('"*"') != column_key('*')
    assert column_key('""') != column_key('')
    assert column_key('"column:a"') != column_key('a')
