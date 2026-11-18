from pathlib import Path

import pytest

from dataforge.ingestion import Importer
from dataforge.store import Store


def test_builder_analysis_refreshes_inventory_summary_immediately(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that builder analysis refreshes inventory summary immediately.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
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
        app.switch_page("ui/pages/analysis.py").run()
        next(b for b in app.button if b.label == "Analyze all files").click().run()
        assert not app.exception and any("Analysis complete" in s.value for s in app.success)
        metrics = {m.label: m.value for m in app.metric}
        assert metrics["Successful parses"] == "2" and metrics["Failed parses"] == "1"
        assert metrics["Pending files"] == "0"
        assert any(".csv: 1" in c.value and ".sql: 2" in c.value for c in app.caption)
    finally:
        store.close()
