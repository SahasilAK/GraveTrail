"""Copyable summaries must not confuse filtered-out columns with unused columns."""
from contextlib import closing
from pathlib import Path

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
    next(s for s in app.segmented_control if s.label == "Columns view").set_value("Direct references").run()
    assert not app.exception
    assert any("Distinct used columns" in s.value for s in app.subheader)
    assert any(p.label == "Unused columns (1)" for p in app.expander)
    next(s for s in app.text_input if s.label == "Filter columns").set_value("id, NAME").run()
    assert not app.exception
    assert set(app.dataframe[0].value["column_name"]) == {"id", "name"}
    next(s for s in app.text_input if s.label == "Filter columns").set_value("not_present").run()
    assert any(p.label == "Unused columns (1)" for p in app.expander)
    Importer(store, w).files([('ambiguous.sql', b'SELECT id FROM raw.a a JOIN raw.b b ON a.id=b.id;')], {'.sql'})
    analyze(store, w)
    app.run()
    assert not app.exception
    assert any(p.label == 'Unused columns' for p in app.expander)
    assert not any(p.label.startswith('Unused columns (') for p in app.expander)
    assert any('Direct reference coverage is incomplete' in warning.value for warning in app.warning)
    import streamlit as st
    st.cache_resource.clear()


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
