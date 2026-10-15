from streamlit.testing.v1 import AppTest


def tree_app():
    from dataforge.graph import LineageGraph
    from ui.lineage_tree import render_tree

    nodes = [{"asset_id": n, "name": n, "kind": "table"} for n in ["a", "b", "c", "d"]]
    edges = [{"source_id": s, "target_id": t, "edge_id": s + t,
              "kind": "CREATE", "status": "verified", "relative_path": "q.sql"}
             for s, t in [("a", "b"), ("b", "c"), ("c", "d")]]
    render_tree(LineageGraph(nodes, edges), "d", "upstream", depth=5, key="test-tree", default_expansion=0)


def test_tree_does_not_render_closed_descendants_and_expands_to_depth():
    app = AppTest.from_function(tree_app).run()
    assert not app.exception
    assert [e.label.split(" • ")[0] for e in app.expander] == ["c"]
    next(n for n in app.number_input if n.label == "Expand tree to depth").set_value(3)
    next(b for b in app.button if b.label == "Expand to depth").click().run()
    assert not app.exception
    assert [e.label.split(" • ")[0] for e in app.expander] == ["c", "b", "a"]
    next(b for b in app.button if b.label == "Collapse tree").click().run()
    assert not app.exception
    assert [e.label.split(" • ")[0] for e in app.expander] == ["c"]
