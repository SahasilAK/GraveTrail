import json
from pathlib import Path

from dataforge.ingestion import Importer
from dataforge.services import analyze, column_report
from dataforge.store import Store


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


def test_conflicting_or_changed_schema_does_not_expand_wildcards(tmp_path: Path) -> None:
    changes = {
        "raw.conflicted": "CREATE TABLE raw.conflicted (id INT, different TEXT);",
        "raw.altered": "ALTER TABLE raw.altered ADD COLUMN extra INT;",
        "raw.replaced": "CREATE OR REPLACE TABLE raw.replaced AS SELECT id FROM raw.input;",
        "raw.dropped": "DROP TABLE raw.dropped;",
    }
    store = Store(tmp_path)
    try:
        w = store.create_workspace("Conflicting schema")
        Importer(store, w).files([
            ("schema.sql", "\n".join(f"CREATE TABLE {table} (id INT, name TEXT);" for table in changes).encode()),
            ("changes.sql", "\n".join(changes.values()).encode()),
            ("query.sql", "\n".join(f"SELECT * FROM {table};" for table in changes).encode()),
        ], {".sql"})
        analyze(store, w)
        assets = {a["name"]: a for a in store.assets(w)}
        for name in changes:
            asset = assets[name]
            rows = column_report(store, w, asset["asset_id"])
            assert {r["column_name"] for r in rows if r["relative_path"] == "query.sql"} == {"*"}, name
            assert json.loads(asset["metadata"])["schema_status"] == "unresolved", name
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
