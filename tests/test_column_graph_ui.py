"""Selection and navigation regressions for the column graph."""
from pathlib import Path
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

from dataforge.ingestion import Importer
from dataforge.services import analyze


def test_table_graph_lists_only_final_columns(tmp_path):
    from dataforge.graph import LineageGraph
    from dataforge.store import Store
    from dataforge.transformations import final_column_names, table_column_links

    store = Store(tmp_path)
    try:
        w = store.create_workspace("Final columns")
        Importer(store, w).files([("schema.sql", b"""
            CREATE TABLE src (a INT, unused INT, id INT);
            CREATE TABLE mart AS WITH prep AS (SELECT a AS staged FROM src WHERE id > 0)
                SELECT staged + 1 AS result FROM prep;
            CREATE TEMP TABLE stage AS SELECT result AS value FROM mart;
            CREATE TABLE report AS SELECT value AS total FROM stage;
            CREATE VIEW probe AS SELECT x FROM outside;
        """)], {".sql"})
        analyze(store, w)
        assets = {a["asset_id"]: a for a in store.assets(w)}
        by_id = final_column_names(store, w, assets)
        by_name = {a["name"]: by_id[aid] for aid, a in assets.items()}
        assert by_name["src"] == {"names": ["a", "unused", "id"], "declared": True}
        assert by_name["mart"] == {"names": ["result"], "declared": False}
        assert by_name["outside"] == {"names": [], "declared": False}
        graph = LineageGraph(list(assets.values()), store.edges(w)).simplified()
        columns = final_column_names(store, w, graph.nodes)
        links = {(assets[s]["name"], assets[t]["name"]): pairs
                 for (s, t), pairs in zip(graph.graph.edges, table_column_links(store, w, graph, columns))}
        assert links["src", "mart"] == [
            {"source": "a", "target": "result", "value": True},
            {"source": "id", "target": "result", "value": False},
        ]
        assert links["mart", "report"] == [{"source": "result", "target": "total", "value": True}]
        assert ("src", "report") not in links
    finally:
        store.close()


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
    build_scene = column_lineage.build_column_scene
    scene_builds = []

    def tracked_scene(*args, **kwargs):
        scene_builds.append(1)
        return build_scene(*args, **kwargs)

    monkeypatch.setattr(column_lineage, "build_column_scene", tracked_scene)
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
    view = next(x for x in app.segmented_control if x.label == "Columns view")
    assert view.options == ["Lineage graph", "Direct references"]
    assert view.value == "Lineage graph"
    assert any(x.label == "Transformation depth" for x in app.slider)
    view.set_value("Direct references").run()
    assert not any(x.label == "Transformation depth" for x in app.slider)
    next(x for x in app.segmented_control if x.label == "Columns view").set_value("Lineage graph").run()
    assert not app.exception
    assert any(x.label == "Transformation depth" for x in app.slider)
    assert any(x.label == "Transformation step" for x in app.selectbox)
    assert not any("Inputs and roles" in frame.value for frame in app.dataframe)

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
    app.session_state[f"column_lineage_steps_{w}_{asset}"] = True
    app.run()
    assert any("Inputs and roles" in frame.value for frame in app.dataframe)
    assert len(scene_builds) == 1
