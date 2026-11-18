from pathlib import Path
from typing import Any

import pytest

from dataforge.ingestion import Importer
from dataforge.models import ParseResult
from dataforge.services import analyze
from dataforge.store import Store
from dataforge.transformations import trace_columns


def populate(tmp_path: Path, sql: str, *, dialect: str | None = None) -> tuple[Any, ...]:
    """Populate the test inputs required by the scenario.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        sql: SQL source text for the test case.

    Returns:
        Value produced for the test scenario.
    """
    store = Store(tmp_path / 'home')
    workspace = store.create_workspace('Columns')
    Importer(store, workspace).files([('a.sql', sql.encode())], {'.sql'}, sql_dialect=dialect)
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


@pytest.mark.parametrize('dialect, statement, kinds', [
    ('postgres', """UPDATE mart AS t SET amount = t.amount + x.amount
        FROM (SELECT id, MAX(amount) AS amount FROM raw GROUP BY id) x WHERE t.id = x.id""", {'sql_update'}),
    ('databricks', """MERGE INTO mart AS t
        USING (SELECT id, MAX(amount) AS amount FROM raw GROUP BY id) x ON t.id = x.id
        WHEN MATCHED THEN UPDATE SET amount = x.amount
        WHEN NOT MATCHED THEN INSERT (id, amount) VALUES (x.id, x.amount)""", {'sql_merge_update', 'sql_merge_insert'}),
])
def test_sql_write_traces_value_and_match_keys_through_derived_source(tmp_path, dialect, statement, kinds):
    sql = 'CREATE TABLE mart AS SELECT id, amount FROM base;\n' + statement + ';'
    store, w = populate(tmp_path, sql, dialect=dialect)
    try:
        trace = trace_columns(store, w, asset_id(store, w, 'mart'), 'amount', include_source=True)
        writes = [d for d in trace['derivations'] if d['category'] in kinds and d['target']['column_name'] == 'amount']
        assert {d['category'] for d in writes} == kinds
        for d in writes:
            assert d['evidence']['code'] in sql
            assert {i['column_name'] for i in d['inputs'] if i['role'] == 'join'} == {'id'}
            assert {i['column_name'] for i in d['inputs'] if i['role'] == 'value'} == {'amount'}
        value_steps = {p['derivation_id'] for p in trace['paths'] if p['effect'] == 'value'}
        origins = {(i['table'], i['column_name']) for d in trace['derivations'] if d['derivation_id'] in value_steps
                   for i in d['inputs']
                   if i['role'] == 'value' and not i['scope']}
        assert {('base', 'amount'), ('raw', 'amount')} <= origins
        assert ('raw', 'id') not in origins
        assert not any(c['reason'] == 'cycle' for c in trace['coverage'])
    finally:
        store.close()


@pytest.mark.parametrize(("declarations", "columns"), [("CREATE TABLE src (id INT, s STRUCT<ph DOUBLE, `a.b` INT>); "
     "CREATE TABLE dst (x DOUBLE, y INT, z INT);", {"x", "y", "z"}), ("CREATE TABLE dst (x DOUBLE, y INT, z INT);", {"*"})])
def test_databricks_struct_star_and_insert_require_trusted_layouts(tmp_path, declarations, columns):
    from dataforge.transformations import column_catalog, trace_columns

    sql = declarations + " INSERT INTO dst SELECT f.s.*, f.id AS ignored FROM src f;"
    store, w = populate(tmp_path, sql, dialect="databricks")
    try:
        target = asset_id(store, w, "dst")
        assert len(store.edges(w)) == 1
        assert {c["column_name"] for c in column_catalog(store, w, target)} == columns
        if columns == {"*"}:
            records = trace_columns(store, w, target, "*", include_source=True)["derivations"]
            assert all(r["status"] == "unresolved" and r["coverage"] for r in records)
        else:
            for output, input_name in [("x", "s.ph"), ("y", 's."a.b"'), ("z", "id")]:
                record = trace_columns(store, w, target, output, include_source=True)["derivations"][0]
                assert [(i["table"], i["column_name"]) for i in record["inputs"]] == [("src", input_name)]
                assert "INSERT INTO dst SELECT f.s.*" in record["evidence"]["code"]
    finally:
        store.close()


def test_databricks_by_name_and_lateral_alias_with_declared_input(tmp_path):
    from dataforge.transformations import trace_columns

    sql = """CREATE TABLE src (x INT, a INT);
    CREATE TABLE dst (b INT, a INT);
    INSERT INTO dst BY NAME SELECT x AS a, a+1 AS b FROM src;
    CREATE TABLE absent (x INT);
    CREATE TABLE fallback AS SELECT x AS a, a+1 AS b FROM absent;
    CREATE TABLE unknown AS SELECT x AS a, a+1 AS b FROM undeclared;
    """
    store, w = populate(tmp_path, sql, dialect="databricks")
    try:
        for table, source, input_name in [("dst", "src", "a"), ("fallback", "absent", "x")]:
            record = trace_columns(store, w, asset_id(store, w, table), "b")["derivations"][0]
            assert {(i["table"], i["column_name"]) for i in record["inputs"]} == {(source, input_name)}
        record = trace_columns(store, w, asset_id(store, w, "unknown"), "b")["derivations"][0]
        assert record["status"] == "unresolved" and not record["inputs"]
    finally:
        store.close()


def test_databricks_recursive_trace_terminates_with_evidence(tmp_path):
    from dataforge.transformations import trace_columns

    sql = """CREATE TABLE dst AS WITH RECURSIVE q(n) AS (
        SELECT id FROM anchor UNION ALL SELECT q.n + step.delta
        FROM q JOIN step ON q.n=step.id WHERE q.n < 10
    ) SELECT * FROM q;"""
    store, w = populate(tmp_path, sql, dialect="databricks")
    try:
        trace = trace_columns(store, w, asset_id(store, w, "dst"), "n", depth=30, include_source=True)
        assert {a["name"] for a in store.assets(w)} == {"anchor", "step", "dst"}
        assert any(item["reason"] == "cycle" for item in trace["coverage"])
        assert {(i["table"], i["column_name"]) for d in trace["derivations"]
                for i in d["inputs"] if i["role"] == "value" and not i["scope"]} == {
            ("anchor", "id"), ("step", "delta"),
        }
    finally:
        store.close()


def test_downstream_preserves_value_and_filter_effects(tmp_path):
    from dataforge.transformations import trace_columns

    store, w = populate(tmp_path, '''CREATE TABLE dst AS SELECT s.a FROM src s WHERE s.a > 0;
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


def test_databricks_pivot_star_uses_trusted_grouping_columns(tmp_path):
    from dataforge.transformations import column_catalog, trace_columns

    sql = """CREATE TABLE sales (store INT, region STRING, amount INT);
        CREATE TABLE dst AS SELECT p.* FROM sales
        PIVOT (SUM(amount) FOR region IN ('east', 'west')) AS p;"""
    store, w = populate(tmp_path, sql, dialect="databricks")
    try:
        target = asset_id(store, w, "dst")
        assert {c["column_name"] for c in column_catalog(store, w, target)} == {"store", "east", "west"}
        trace = trace_columns(store, w, target, "east")["derivations"][0]
        assert trace["status"] == "inferred"
        assert {(i["column_name"], i["role"]) for i in trace["inputs"]} == {
            ("amount", "value"), ("region", "value_selection"), ("store", "value_selection"), ("", "rowset"),
        }
    finally:
        store.close()


@pytest.mark.parametrize("declared", [False, True])
def test_databricks_cdc_star_exclusions_need_trusted_schema(tmp_path, declared):
    from dataforge.transformations import column_catalog, trace_columns

    declaration = "CREATE TABLE feed (id INT, amount DOUBLE, stamp BIGINT);" if declared else ""
    sql = declaration + """CREATE STREAMING TABLE dst;
        CREATE FLOW update_dst AS AUTO CDC INTO dst FROM STREAM(feed)
        KEYS (id) SEQUENCE BY stamp COLUMNS * EXCEPT (stamp)
        STORED AS SCD TYPE 2 TRACK HISTORY ON * EXCEPT (id);"""
    store, w = populate(tmp_path, sql, dialect="databricks")
    try:
        target = asset_id(store, w, "dst")
        assert len(store.edges(w)) == 1
        assert {c["column_name"] for c in column_catalog(store, w, target)} == (
            {"id", "amount"} if declared else {"*"})
        d = trace_columns(store, w, target, "amount" if declared else "*")["derivations"][0]
        assert {(i["column_name"], i["role"]) for i in d["inputs"]} == (
            {("amount", "value"), ("id", "match_key"), ("stamp", "sequence"),
             ("amount", "history")} if declared else
            {("*", "value"), ("id", "match_key"), ("stamp", "sequence")})
        if not declared:
            assert d["status"] == "unresolved"
    finally:
        store.close()


def test_sql_trace_crosses_files_ctes_and_physical_stars(tmp_path):
    from dataforge.transformations import trace_columns

    files = [
        ("schema.sql", "CREATE TABLE raw.orders (id INT, qty INT, price INT, active INT); "
                       "CREATE TABLE stage.orders (id INT, gross INT); "
                       "CREATE TABLE mart.orders (order_id INT, net INT, source_system INT);"),
        ("stage.sql", "INSERT INTO stage.orders (id, gross) WITH base AS (SELECT * FROM raw.orders), "
                      "calc AS (SELECT base.id, base.qty * base.price AS gross FROM base "
                      "WHERE base.active = 1) SELECT * FROM calc;"),
        ("load.sql", "INSERT INTO mart.orders SELECT stage.*, 10 AS source_system FROM stage.orders stage;"),
        ("report.sql", "CREATE TABLE report.totals AS SELECT SUM(net) AS sales FROM mart.orders WHERE net > 0;"),
    ]
    store = Store(tmp_path)
    try:
        w = store.create_workspace("SQL traces")
        Importer(store, w).files([(name, sql.encode()) for name, sql in files], {".sql"}, sql_dialect="postgres")
        analyze(store, w)
        assets = {a["asset_id"]: a["name"] for a in store.assets(w)}
        assert {(assets[e["source_id"]], assets[e["target_id"]]) for e in store.edges(w)} == {
            ("raw.orders", "stage.orders"), ("stage.orders", "mart.orders"), ("mart.orders", "report.totals"),
        }
        upstream = trace_columns(store, w, asset_id(store, w, "report.totals"), "sales", depth=15, include_source=True)
        assert {d["evidence"]["relative_path"] for d in upstream["derivations"]} == {
            "stage.sql", "load.sql", "report.sql",
        }
        gross = next(d for d in upstream["derivations"] if d["expression"] == "base.qty * base.price AS gross")
        assert {(i["column_name"], i["role"]) for i in gross["inputs"]} == {
            ("qty", "value"), ("price", "value"), ("active", "row_filter"),
        }
        assert {i["column_name"] for d in upstream["derivations"] for i in d["inputs"]
                if i["table"] == "raw.orders" and not i["scope"]} == {"qty", "price", "active"}
        downstream = trace_columns(store, w, asset_id(store, w, "raw.orders"), "qty", direction="downstream", depth=15)
        assert any(d["target"]["table"] == "report.totals" and d["target"]["column_name"] == "sales"
                   for d in downstream["derivations"])
        impact = trace_columns(store, w, asset_id(store, w, "raw.orders"), "active", direction="downstream", depth=15)
        report = next(d["derivation_id"] for d in impact["derivations"] if d["target"]["table"] == "report.totals")
        assert {p["effect"] for p in impact["paths"] if p["derivation_id"] == report} == {"row_selection"}
    finally:
        store.close()


def test_repaired_roles_survive_reopen_cache_and_failed_publication(tmp_path):
    from dataforge.transformations import trace_columns

    store, w = populate(tmp_path, '''CREATE TABLE dst AS SELECT a, SUM(b) AS s FROM src WHERE a>0 GROUP BY 1;
        CREATE TABLE fin AS SELECT a FROM dst;''')
    source = asset_id(store, w, 'src')
    before = trace_columns(store, w, source, 'a', direction='downstream')
    assert {d['target']['column_name'] for d in before['derivations']} == {'a', 's'}
    assert {p['effect'] for p in before['paths']} == {'value', 'row_selection'}
    store.close()
    store = Store(tmp_path / 'home')
    try:
        assert trace_columns(store, w, source, 'a', direction='downstream') == before
        assert analyze(store, w)['analyzed'] == 0
        cached = trace_columns(store, w, source, 'a', direction='downstream')
        # A cached parse is republished under a fresh analysis run.
        assert [{k: v for k, v in d.items() if k != 'run_id'} for d in cached['derivations']] == [
            {k: v for k, v in d.items() if k != 'run_id'} for d in before['derivations']]
        assert cached['paths'] == before['paths']
        with pytest.raises(InterruptedError):
            analyze(store, w, force=True, cancelled=lambda: True)
        assert trace_columns(store, w, source, 'a', direction='downstream') == cached
    finally:
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


def test_unmapped_insert_wildcards_do_not_invent_targets(tmp_path: Path) -> None:
    """Verify that unmapped insert wildcards do not invent targets.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        target_ddl: Target ddl value used by the test case.
        projection: Projection value used by the test case.
    """
    target_ddl, projection = ('', '*')
    from dataforge.transformations import column_catalog, trace_columns

    store, w = populate(tmp_path, f'''CREATE TABLE src (a INT, b INT); {target_ddl}
        INSERT INTO dst SELECT {projection} FROM src s;''')
    target = asset_id(store, w, 'dst')
    assert {c['column_name'] for c in column_catalog(store, w, target)} == {'*'}
    trace = trace_columns(store, w, target, 'x')
    assert trace['state'] == 'unresolved' and not trace['complete']
    assert any(c['reason'] == 'unresolved_scope' for c in trace['coverage'])
    store.close()


def test_quoted_special_names_do_not_share_wildcard_or_rowset_identity() -> None:
    """Verify that quoted special names do not share wildcard or rowset identity."""
    from dataforge.models import column_key

    assert column_key('"*"') != column_key('*')
    assert column_key('""') != column_key('')
    assert column_key('"column:a"') != column_key('a')
