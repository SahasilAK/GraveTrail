"""Copyable summaries must not confuse filtered-out columns with unused columns."""
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from dataforge.ingestion import Importer
from dataforge.services import analyze
from ui.common import get_store


def test_column_lists_and_comma_filter_use_complete_direct_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that column lists and comma filter use complete direct report.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path))
    store = get_store(str(tmp_path))
    w = store.create_workspace("Column QOL")
    Importer(store, w).files([
        ("schema.sql", b"create table raw.a (id int, name text, unused text);"),
        ("query.sql", b"select id, name from raw.a where id > 0;")], {".sql"})
    analyze(store, w)
    asset = next(a["asset_id"] for a in store.assets(w) if a["name"] == "raw.a")
    app = AppTest.from_file(Path("app.py").resolve(), default_timeout=20).run()
    app.switch_page("ui/pages/columns.py").run()
    next(s for s in app.selectbox if s.label == "Choose an exact asset").set_value(asset).run()
    assert not app.exception
    assert any("Distinct used columns" in s.value for s in app.subheader)
    assert any(p.label == "Unused columns (1)" for p in app.expander)
    next(s for s in app.text_input if s.label == "Filter columns").set_value("id, NAME").run()
    assert not app.exception
    assert set(app.dataframe[0].value["column_name"]) == {"id", "name"}
    next(s for s in app.text_input if s.label == "Filter columns").set_value("not_present").run()
    assert any(p.label == "Unused columns (1)" for p in app.expander)
    import streamlit as st
    st.cache_resource.clear()


@pytest.mark.parametrize(("rows", "metadata", "used", "unused"), [
    ([{"column_name": "id"}, {"column_name": "id"}],
     {"schema_status": "declared", "columns": [{"name": "id"}, {"name": "name"}]}, ["id"], ["name"]),
    ([{"column_name": "*"}, {"column_name": "id"}],
     {"schema_status": "declared", "columns": [{"name": "id"}, {"name": "name"}]}, ["id"], None),
    ([], {}, [], None),
    ([], {"schema_status": "unresolved", "columns": [{"name": "id"}]}, [], None),
    ([], {"schema_status": "declared", "columns": [{"name": "id"}]}, [], ["id"]),
    ([{"column_name": "id"}], {"schema_status": "declared", "columns": [{"name": "id"}]}, ["id"], []),
])
def test_column_name_summary_preserves_unknown_coverage(rows: list[Any], metadata: dict[str, Any], used: list[Any], unused: Any) -> None:
    """Verify that column name summary preserves unknown coverage.

    Args:
        rows: Rows value used by the test case.
        metadata: Metadata value used by the test case.
        used: Used value used by the test case.
        unused: Unused value used by the test case.
    """
    from dataforge.services import column_names

    assert column_names(rows, metadata, coverage_complete=True) == (used, unused)


def test_column_summary_requires_explicit_coverage():
    from dataforge.services import column_names

    metadata = {'schema_status': 'declared', 'columns': [{'name': 'a'}, {'name': 'b'}]}
    assert column_names([{'column_name': 'a'}], metadata) == (['a'], None)


@pytest.mark.parametrize('problem', ['ambiguous', 'parse_failure', 'pending', 'settings', 'wildcard', 'parser_version'])
def test_unused_columns_unknown_with_incomplete_usage(tmp_path, problem):
    import json

    from dataforge.services import column_names, column_report, column_usage_coverage
    from dataforge.store import Store

    with closing(Store(tmp_path / 'home')) as store:
        w = store.create_workspace('Usage coverage')
        query = {
            'ambiguous': 'CREATE TABLE dst AS SELECT b FROM src JOIN other ON src.a=other.a;',
            'parse_failure': 'SELECT ( FROM src;',
            'wildcard': 'SELECT * FROM src;',
        }.get(problem, 'SELECT a FROM src;')
        importer = Importer(store, w)
        importer.files([('schema.sql', b'CREATE TABLE src (a INT,b INT); CREATE TABLE other (a INT,b INT);'),
                        ('query.sql', query.encode())], {'.sql'})
        if problem == 'wildcard':
            store.set_setting(w, 'expand_wildcards', False)
        analyze(store, w)
        if problem == 'pending':
            importer.files([('query.sql', b'SELECT b FROM src;')], {'.sql'})
        elif problem == 'settings':
            store.set_setting(w, 'case_sensitive', True)
        elif problem == 'parser_version':
            store.execute("UPDATE column_analysis SET parser_version='old' WHERE workspace_id=?", [w])
        asset = next(a for a in store.assets(w) if a['name'] == 'src')
        coverage = column_usage_coverage(store, w, asset['asset_id'])
        assert not coverage['complete'] and coverage['reasons']
        used, unused = column_names(column_report(store, w, asset['asset_id']), json.loads(asset['metadata']),
                                    coverage_complete=coverage['complete'])
        assert unused is None
        if problem == 'ambiguous':
            assert used == ['a']


def test_unused_columns_clean_analysis_and_quoted_identity(tmp_path):
    import json

    from dataforge.services import column_names, column_report, column_usage_coverage
    from dataforge.store import Store

    with closing(Store(tmp_path / 'home')) as store:
        w = store.create_workspace('Clean usage')
        Importer(store, w).files([('a.sql', b'CREATE TABLE src ("Key" INT, "Unused" INT); SELECT "Key" FROM src;')], {'.sql'})
        analyze(store, w)
        asset = next(a for a in store.assets(w) if a['name'] == 'src')
        coverage = column_usage_coverage(store, w, asset['asset_id'])
        assert coverage == {'complete': True, 'reasons': []}
        assert column_names(column_report(store, w, asset['asset_id']), json.loads(asset['metadata']),
                            coverage_complete=True) == (['Key'], ['Unused'])
