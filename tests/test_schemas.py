import json
from pathlib import Path
from typing import Any

import pytest

from dataforge.ingestion import Importer
from dataforge.parsers.sql import parse_sql
from dataforge.services import analyze, column_report
from dataforge.store import Store


def test_sql_declared_schema_and_plain_wildcard_eligibility() -> None:
    """Verify that sql declared schema and plain wildcard eligibility."""
    result = parse_sql('CREATE TABLE raw.a (id INT, name VARCHAR(30), PRIMARY KEY (id)); SELECT a.* FROM raw.a a;')
    declaration = result.metadata["declared_schemas"][0]
    assert declaration["table"] == "raw.a"
    assert [(c["name"], c["type"]) for c in declaration["columns"]] == [("id", "INT"), ("name", "VARCHAR(30)")]
    assert declaration["operation_index"] == 0
    assert next(u for u in result.operations[1].usages if u.column == "*").wildcard_safe
    modified = parse_sql('SELECT * EXCEPT (name) FROM raw.a', dialect="bigquery")
    assert all(not u.wildcard_safe for u in modified.operations[0].usages)


def test_schema_expansion_is_direct_and_preserves_both_sources_of_evidence(tmp_path: Path) -> None:
    """Verify that schema expansion is direct and preserves both sources of evidence.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    store = Store(tmp_path)
    try:
        w = store.create_workspace("Declared schema")
        Importer(store, w).files([
            ("schema.sql", b"CREATE TABLE raw.customers (id INT, name TEXT);"),
            ("query.sql", b"CREATE TABLE mart.x AS SELECT c.* FROM raw.customers c;\nSELECT id FROM mart.x;")], {".sql"})
        analyze(store, w)
        asset = next(a for a in store.assets(w) if a["name"] == "raw.customers")
        rows = column_report(store, w, asset["asset_id"])
        assert {r["column_name"] for r in rows} == {"id", "name"}
        assert all(r["relative_path"] == "query.sql" and r["start_line"] == 1 for r in rows)
        assert all(r["status"] == "inferred" and "schema.sql" in r["schema_source"] for r in rows)
        metadata = json.loads(asset["metadata"])
        assert metadata["schema_status"] == "declared"
        evidence = metadata["schema_evidence"][0]
        assert evidence["relative_path"] == "schema.sql" and evidence["source_hash"]
        assert store.rows("SELECT code FROM statements WHERE statement_id=?", [evidence["statement_id"]])[0]["code"].startswith("CREATE TABLE")
        assert analyze(store, w)["cached"] == 2
    finally:
        store.close()


@pytest.mark.parametrize("later", [
    b"CREATE TABLE raw.a (id INT, different TEXT);",
    b"ALTER TABLE raw.a ADD COLUMN extra INT;",
    b"CREATE OR REPLACE TABLE raw.a AS SELECT id FROM raw.b;",
    b"DROP TABLE raw.a;",
])
def test_conflicting_or_changed_schema_does_not_expand_wildcards(tmp_path: Path, later: Any) -> None:
    """Verify that conflicting or changed schema does not expand wildcards.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        later: Later value used by the test case.
    """
    store = Store(tmp_path)
    try:
        w = store.create_workspace("Conflicting schema")
        Importer(store, w).files([("a.sql", b"CREATE TABLE raw.a (id INT, name TEXT);"),
            ("b.sql", later), ("query.sql", b"SELECT * FROM raw.a;")], {".sql"})
        analyze(store, w)
        asset = next(a for a in store.assets(w) if a["name"] == "raw.a")
        rows = column_report(store, w, asset["asset_id"])
        assert {r["column_name"] for r in rows if r["relative_path"] == "query.sql"} == {"*"}
        assert json.loads(asset["metadata"])["schema_status"] == "unresolved"
        assert any("schema" in d["message"].lower() for d in store.diagnostics(w))
    finally:
        store.close()


def test_schema_refresh_reuses_query_cache_but_removes_stale_expansion(tmp_path: Path) -> None:
    """Verify that schema refresh reuses query cache but removes stale expansion.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    store = Store(tmp_path)
    try:
        w = store.create_workspace("Refresh")
        importer = Importer(store, w)
        importer.files([("schema.sql", b"CREATE TABLE raw.a (old INT);"),
                        ("query.sql", b"SELECT * FROM raw.a;")], {".sql"})
        analyze(store, w)
        asset = next(a for a in store.assets(w) if a["name"] == "raw.a")
        assert {r["column_name"] for r in column_report(store, w, asset["asset_id"])} == {"old"}
        importer.files([("schema.sql", b"CREATE TABLE raw.a (fresh INT);")], {".sql"})
        run = analyze(store, w)
        assert run["cached"] == 1
        assert {r["column_name"] for r in column_report(store, w, asset["asset_id"])} == {"fresh"}
        store.set_setting(w, "expand_wildcards", False)
        analyze(store, w)
        assert {r["column_name"] for r in column_report(store, w, asset["asset_id"])} == {"*"}
    finally:
        store.close()


def test_wildcard_modifiers_and_csv_name_matching_never_fabricate_columns(tmp_path: Path) -> None:
    """Verify that wildcard modifiers and csv name matching never fabricate columns.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    store = Store(tmp_path)
    try:
        w = store.create_workspace("Conservative schema")
        store.set_setting(w, "dialect", "bigquery")
        Importer(store, w).files([("schema.sql", b"CREATE TABLE raw.a (id INT, name STRING);"),
            ("a.csv", b"secret,guess\n1,2"),
            ("query.sql", b"SELECT * EXCEPT (name) FROM raw.a; SELECT * FROM unknown.a;")], {".sql", ".csv"})
        analyze(store, w)
        for name in ["raw.a", "unknown.a"]:
            asset = next(a for a in store.assets(w) if a["name"] == name)
            assert {r["column_name"] for r in column_report(store, w, asset["asset_id"])} == {"*"}
    finally:
        store.close()


@pytest.mark.parametrize("ddl", [
    "CREATE TABLE raw.a (id INT, LIKE raw.b INCLUDING ALL);",
    "CREATE TABLE raw.a (id INT) INHERITS(raw.b);",
])
def test_schema_extending_constructs_are_not_treated_as_complete(ddl: str) -> None:
    """Verify that schema extending constructs are not treated as complete.

    Args:
        ddl: Ddl value used by the test case.
    """
    result = parse_sql(ddl, dialect="postgres")
    assert result.metadata["declared_schemas"][0]["columns"] is None


def test_identical_declarations_do_not_conflict_and_join_wildcards_remain_direct(tmp_path: Path) -> None:
    """Verify that identical declarations do not conflict and join wildcards remain direct.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    store = Store(tmp_path)
    try:
        w = store.create_workspace("Matching schemas")
        Importer(store, w).files([
            ("schema.sql", b"CREATE TABLE raw.a (id INT, name TEXT); CREATE TABLE raw.b (id INT, total INT);"),
            ("same.sql", b"CREATE TABLE raw.a (id INT, name TEXT);"),
            ("query.sql", b"SELECT * FROM raw.a a JOIN raw.b b ON a.id=b.id;")], {".sql"})
        analyze(store, w)
        for table, expected in [("raw.a", {"id", "name"}), ("raw.b", {"id", "total"})]:
            asset = next(a for a in store.assets(w) if a["name"] == table)
            assert {r["column_name"] for r in column_report(store, w, asset["asset_id"])} == expected
        first = next(a for a in store.assets(w) if a["name"] == "raw.a")
        assert len(json.loads(first["metadata"])["schema_evidence"]) == 2
    finally:
        store.close()


@pytest.mark.parametrize("second_schema", [False, True])
def test_unqualified_schema_changes_invalidate_possible_qualified_assets(tmp_path: Path, second_schema: bool) -> None:
    """Verify that unqualified schema changes invalidate possible qualified assets.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        second_schema: Second schema value used by the test case.
    """
    store = Store(tmp_path)
    try:
        w = store.create_workspace("Unqualified change")
        files = [("schema.sql", b"CREATE TABLE raw.a (id INT);"),
                 ("alter.sql", b"ALTER TABLE a ADD COLUMN extra INT;"),
                 ("query.sql", b"SELECT * FROM raw.a;")]
        if second_schema:
            files.append(("other.sql", b"CREATE TABLE stage.a (id INT);"))
        Importer(store, w).files(files, {".sql"})
        analyze(store, w)
        for name in ["raw.a", *(["stage.a"] if second_schema else [])]:
            asset = next(a for a in store.assets(w) if a["name"] == name)
            assert json.loads(asset["metadata"])["schema_status"] == "unresolved"
        asset = next(a for a in store.assets(w) if a["name"] == "raw.a")
        assert {r["column_name"] for r in column_report(store, w, asset["asset_id"])} == {"*"}
    finally:
        store.close()


@pytest.mark.parametrize("change", ["ALTER TABLE raw.a SWAP WITH raw.b;",
                                    "ALTER TABLE raw.a RENAME TO raw.b;"])
def test_two_table_schema_changes_invalidate_both_operands(tmp_path: Path, change: str) -> None:
    """Verify that two table schema changes invalidate both operands.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        change: Change value used by the test case.
    """
    store = Store(tmp_path)
    try:
        w = store.create_workspace("Two-table schema change")
        store.set_setting(w, "dialect", "snowflake")
        Importer(store, w).files([("q.sql", (
            "CREATE TABLE raw.a (fresh INT); CREATE TABLE raw.b (old TEXT); " + change +
            " SELECT * FROM raw.b;").encode())], {".sql"})
        analyze(store, w)
        for name in ["raw.a", "raw.b"]:
            asset = next(a for a in store.assets(w) if a["name"] == name)
            assert json.loads(asset["metadata"])["schema_status"] == "unresolved"
    finally:
        store.close()
