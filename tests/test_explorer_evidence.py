from pathlib import Path
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


def test_source_panel_follows_active_tree_tab_unless_graph_evidence_is_selected(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path))
    app = AppTest.from_file(Path("app.py").resolve()).run()
    store = Store(tmp_path)
    try:
        w = app.session_state["workspace"]
        Importer(store, w).files([("up.sql", b"create table mart.middle as select id from raw.a;"),
                                 ("down.sql", b"create table mart.final as select id from mart.middle;")], {".sql"})
        analyze(store, w)
        middle = next(a["asset_id"] for a in store.assets(w) if a["name"] == "mart.middle")
        app.switch_page("ui/pages/explorer.py").run()
        next(s for s in app.selectbox if s.label == "Choose an exact asset").set_value(middle).run()
        assert next(s for s in app.selectbox if s.label == "Source file").options == ["up.sql"]
        app.session_state["lineage_direction_tabs"] = "Downstream dependencies"
        app.run()
        assert not app.exception
        assert next(s for s in app.selectbox if s.label == "Source file").options == ["down.sql"]
        assert app.segmented_control[0].value == "upstream"  # graph controls stay independent
        from ui import common
        monkeypatch.setattr(common, "graph_view", lambda *args: SimpleNamespace(selection={"edge": 0}))
        app.run()
        assert next(s for s in app.selectbox if s.label == "Source file").options == ["up.sql"]
    finally:
        store.close()
