from dataforge.graph import LineageGraph


def test_cycle_safe_bounded_search_and_contraction():
    nodes = [{"asset_id": n, "name": n, "temporary": n == "t", "kind": "table"} for n in ["a", "t", "b", "c"]]
    edges = [{"source_id": a, "target_id": b, "edge_id": a + b, "code": "evidence"}
             for a, b in [("a", "t"), ("t", "b"), ("b", "c"), ("c", "a")]]
    graph = LineageGraph(nodes, edges)
    assert len(graph.focus("a", "downstream", 1).nodes) == 2
    assert len(graph.focus("a", "combined", 10, limit=3).nodes) <= 3
    assert graph.cycles()
    simple = graph.simplified()
    assert "t" not in simple.nodes and simple.graph.has_edge("a", "b")
    assert {e["edge_id"] for e in simple.graph["a"]["b"]["evidence"]} == {"at", "tb"}
