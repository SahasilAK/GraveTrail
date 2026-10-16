from streamlit.testing.v1 import AppTest


def tree_app():
    from dataforge.graph import LineageGraph
    from ui.lineage_tree import render_tree

    nodes = [{"asset_id": n, "name": n, "kind": "table"} for n in ["a", "b", "c", "d"]]
    edges = [{"source_id": s, "target_id": t, "edge_id": s + t,
              "kind": "CREATE", "status": "verified", "relative_path": "q.sql"}
             for s, t in [("a", "b"), ("b", "c"), ("c", "d")]]
    render_tree(LineageGraph(nodes, edges), "d", "upstream", depth=5, key="test-tree", default_expansion=0)


def test_tree_does_not_render_closed_descendants_and_expands_all():
    app = AppTest.from_function(tree_app).run()
    assert not app.exception
    assert [e.label.split("**")[1] for e in app.expander] == ["c"]
    next(b for b in app.button if b.label == "Expand all").click().run()
    assert not app.exception
    assert [e.label.split("**")[1] for e in app.expander] == ["c", "b"]
    assert any("**a**" in m.value and "via q\\.sql" in m.value for m in app.markdown)
    next(b for b in app.button if b.label == "Collapse all").click().run()
    assert not app.exception
    assert [e.label.split("**")[1] for e in app.expander] == ["c"]


def bounded_tree_app(direction="downstream", depth=5, limit=150):
    from dataforge.graph import LineageGraph
    from ui.lineage_tree import render_tree

    nodes = [{"asset_id": n, "name": n, "kind": "table"} for n in ["a", "b", "c"]]
    edges = [{"source_id": s, "target_id": t, "edge_id": s + t,
              "kind": "CREATE", "status": "inferred", "relative_path": "jobs/a_[1].sql",
              "confidence": 0.8} for s, t in [("a", "b"), ("b", "c"), ("c", "a")]]
    render_tree(LineageGraph(nodes, edges), "a", direction, depth=depth, limit=limit,
                key="bounded", default_expansion=5)


def test_directions_cycles_and_optional_details():
    for direction, first in [("upstream", "c"), ("downstream", "b")]:
        app = AppTest.from_function(bounded_tree_app, args=(direction,)).run()
        assert not app.exception
        assert app.expander[0].label.startswith(f"**{first}**")
        assert any("Cycle returns to a" in c.value for c in app.caption)
        assert not any("evidence records" in c.value for c in app.caption)
        app.toggle[0].set_value(True).run()
        assert not app.exception
        assert any("80%" in c.value for c in app.caption)
        assert any("inferred" in c.value for c in app.caption)


def test_depth_and_entry_limits_remain_explicit():
    app = AppTest.from_function(bounded_tree_app, args=("downstream", 1, 150)).run()
    assert not app.exception
    assert len(app.expander) == 1
    assert any("Traversal depth reached" in c.value for c in app.caption)
    app = AppTest.from_function(bounded_tree_app, args=("downstream", 5, 1)).run()
    assert not app.exception
    assert len(app.expander) == 1
    assert any("limited to 1 visible entries" in i.value for i in app.info)
