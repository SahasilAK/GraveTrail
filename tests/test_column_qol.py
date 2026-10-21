"""Copyable summaries must not confuse filtered-out columns with unused columns."""
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

    assert column_names(rows, metadata) == (used, unused)
