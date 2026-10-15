import json
from pathlib import Path

import pytest

from dataforge.configuration import (
    ParsingSettings,
    export_workspace_configuration,
    import_workspace_configuration,
)
from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


def test_csv_sample_setting_is_bounded_portable_and_invalidates_cached_preview(tmp_path):
    for invalid in [-1, 101]:
        with pytest.raises(ValueError):
            ParsingSettings(csv_sample_rows=invalid)
    store = Store(tmp_path)
    try:
        w = store.create_workspace("CSV previews")
        Importer(store, w).files([("rows.csv", b"id,name\n1,one\n2,two\n3,three\n")], {".csv"})
        store.set_setting(w, "csv_sample_rows", 1)
        analyze(store, w)
        metadata = json.loads(store.files(w)[0]["metadata"])
        assert metadata["preview"] == [["1", "one"]] and metadata["row_count"] == 3
        copied = import_workspace_configuration(store, export_workspace_configuration(store, w))
        assert store.setting(copied, "csv_sample_rows") == 1
        store.set_setting(w, "csv_sample_rows", 0)
        assert analyze(store, w)["analyzed"] == 1
        metadata = json.loads(store.files(w)[0]["metadata"])
        assert metadata["preview"] == [] and metadata["row_count"] == 3
        assert all(c["type"] == "unknown" for c in metadata["columns"])
    finally:
        store.close()


def test_builder_analysis_refreshes_inventory_summary_immediately(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path))
    app = AppTest.from_file(Path("app.py").resolve()).run()
    store = Store(tmp_path)
    try:
        w = app.session_state["workspace"]
        Importer(store, w).files([("ok.sql", b"create table mart.x as select id from raw.a;"),
                                 ("bad.sql", b"select from;"), ("rows.csv", b"id\n1\n")], {".sql", ".csv"})
        app.switch_page("ui/pages/settings.py").run()
        next(n for n in app.number_input if n.label == "CSV sample rows").set_value(1)
        next(b for b in app.button if b.label == "Save parsing settings").click().run()
        assert store.setting(w, "csv_sample_rows") == 1
        app.switch_page("ui/pages/builder.py").run()
        next(b for b in app.button if b.label == "Analyze all files").click().run()
        assert not app.exception and any("Analysis complete" in s.value for s in app.success)
        metrics = {m.label: m.value for m in app.metric}
        assert metrics["Successful parses"] == "2" and metrics["Failed parses"] == "1"
        assert metrics["Pending files"] == "0"
        assert any(".csv: 1" in c.value and ".sql: 2" in c.value for c in app.caption)
    finally:
        store.close()
