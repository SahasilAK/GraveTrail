from streamlit.testing.v1 import AppTest


def bounded_tree_app(direction: str="downstream", depth: int=5, limit: int=150) -> None:
    """Handle bounded tree app for the test scenario.

    Args:
        direction: Direction value used by the test case.
        depth: Depth value used by the test case.
        limit: Limit value used by the test case.
    """
    from dataforge.graph import LineageGraph
    from ui.lineage_tree import render_tree

    nodes = [{"asset_id": n, "name": n, "kind": "table"} for n in ["a", "b", "c"]]
    edges = [{"source_id": s, "target_id": t, "edge_id": s + t,
              "kind": "CREATE", "status": "inferred", "relative_path": "jobs/a_[1].sql",
              "confidence": 0.8} for s, t in [("a", "b"), ("b", "c"), ("c", "a")]]
    render_tree(LineageGraph(nodes, edges), "a", direction, depth=depth, limit=limit,
                key="bounded", default_expansion=5)


def test_depth_and_entry_limits_remain_explicit() -> None:
    """Verify that depth and entry limits remain explicit."""
    app = AppTest.from_function(bounded_tree_app, args=("downstream", 1, 150)).run()
    assert not app.exception
    assert len(app.expander) == 1
    assert any("Traversal depth reached" in c.value for c in app.caption)
    app = AppTest.from_function(bounded_tree_app, args=("downstream", 5, 1)).run()
    assert not app.exception
    assert len(app.expander) == 1
    assert any("limited to 1 visible entries" in i.value for i in app.info)
