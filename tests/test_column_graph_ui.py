"""Selection and navigation regressions for the column graph."""
from pathlib import Path
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

from dataforge.ingestion import Importer
from dataforge.services import analyze


def test_selection_rejects_stale_and_unknown_ids():
    from ui.column_graph import resolve_selection
    scene = {"trace_key": "new", "nodes": [{"id": "derivation:d", "kind": "transformation"}],
             "edges": [], "cards": [{"id": "card:c", "kind": "card"}]}
    assert resolve_selection(scene, {"trace_key": "old", "kind": "transformation", "id": "derivation:d"}) is None
    assert resolve_selection(scene, {"trace_key": "new", "kind": "column", "id": "derivation:d"}) is None
    assert resolve_selection(scene, {"trace_key": "new", "kind": "transformation", "id": "derivation:d"})["id"] == "derivation:d"
    assert resolve_selection(scene, {"trace_key": "new", "kind": "card", "id": "card:c"})["id"] == "card:c"
    assert resolve_selection(scene, {"trace_key": "old", "kind": "card", "id": "card:c"}) is None


def test_columns_graph_is_lazy_and_inspects_source(tmp_path, monkeypatch):
    from ui import column_lineage
    from ui.common import get_store
    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path))
    store = get_store(str(tmp_path))
    w = store.create_workspace("Graph UI")
    Importer(store, w).files([("a.sql", b"CREATE TABLE mart AS SELECT a+1 AS amount FROM src; "
                                        b"CREATE TABLE dst AS SELECT amount*2 AS result FROM mart;")], {".sql"})
    analyze(store, w)
    app = AppTest.from_file(Path("app.py").resolve(), default_timeout=30).run()
    app.switch_page("ui/pages/columns.py").run()
    assert not app.exception
    asset = next(a["asset_id"] for a in store.assets(w) if a["name"] == "dst")
    next(x for x in app.selectbox if x.label == "Choose an exact asset").set_value(asset).run()
    assert not any(x.label == "Transformation depth" for x in app.slider)
    next(x for x in app.segmented_control if x.label == "Columns view").set_value("Lineage graph").run()
    assert not app.exception
    assert any(x.label == "Transformation depth" for x in app.slider)
    assert any(x.label == "Transformation step" for x in app.selectbox)

    # Opening logic without explicitly choosing a transformation must not pick a writer.
    asset_id = asset
    app.session_state["transformation_inspector_" + w + "_" + asset_id] = True
    app.run()
    assert not app.code
    next(x for x in app.selectbox if x.label == "Transformation step").select_index(1).run()
    assert any("amount*2" in x.value for x in app.code)

    def select_mart(scene, **kwargs):
        card = next(card for card in scene["cards"] if card["label"] == "mart")
        return SimpleNamespace(selection={"trace_key": scene["trace_key"], "kind": "card", "id": card["id"]})

    monkeypatch.setattr(column_lineage, "column_graph_view", select_mart)
    app.session_state["transformation_inspector_" + w + "_" + asset_id] = False
    app.run()
    assert not app.exception
    step = next(x for x in app.selectbox if x.label == "Transformation step")
    assert step.options[1].startswith("mart.amount")
    assert any(option.startswith("dst.result") for option in step.options)
    assert app.code and "a+1" in app.code[0].value.replace(" ", "")
