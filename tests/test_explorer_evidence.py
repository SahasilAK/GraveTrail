from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


def test_source_panel_follows_graph_direction_or_active_tree_tab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that source panel follows graph direction or active tree tab.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
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
        source_widget_key = next(s for s in app.selectbox if s.label == "Source file").key
        next(s for s in app.segmented_control if s.label == "Lineage view").set_value("Tree").run()
        app.session_state["lineage_direction_tabs"] = "Downstream dependencies"
        app.run()
        assert not app.exception
        assert next(s for s in app.selectbox if s.label == "Source file").options == ["down.sql"]
        assert next(s for s in app.selectbox if s.label == "Source file").key != source_widget_key
        next(s for s in app.segmented_control if s.label == "Lineage view").set_value("Tree").run()
        next(s for s in app.segmented_control if s.label == "Lineage view").set_value("Graph").run()
        app.run()
        assert next(s for s in app.selectbox if s.label == "Source file").options == ["up.sql"]
        assert app.segmented_control[0].value == "upstream"
        from ui import common
        monkeypatch.setattr(common, "graph_view", lambda *args, **kwargs: SimpleNamespace(selection={"edge": 0}))
        app.run()
        assert next(s for s in app.selectbox if s.label == "Source file").options == ["up.sql"]
    finally:
        store.close()


def test_explorer_reports_missing_assets_without_crashing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that explorer reports missing assets without crashing.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    from dataforge.graph import LineageGraph
    from ui import common

    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path))
    app = AppTest.from_file(Path("app.py").resolve()).run()
    graph = LineageGraph(
        [{"asset_id": "mart", "name": "mart.output", "kind": "table", "temporary": False}],
        [{"edge_id": "broken", "source_id": "missing", "target_id": "mart"}])
    monkeypatch.setattr(common, "_cached_graph", lambda *args: graph)
    app.switch_page("ui/pages/explorer.py").run()
    assert not app.exception
    assert any("relationships reference missing assets" in item.value for item in app.warning)
    selector = next(s for s in app.selectbox if s.label == "Choose an exact asset")
    assert selector.options == ["mart.output  [table]", "All"]
    selector.set_value("mart").run()
    assert not app.exception
