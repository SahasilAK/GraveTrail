from dataforge.graph import LineageGraph


def test_cycle_safe_bounded_search_and_contraction() -> None:
    """Verify that cycle safe bounded search and contraction."""
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


def test_path_limits_and_cycles_are_explicit_boundaries() -> None:
    """Verify that path limits and cycles are explicit boundaries."""
    nodes = [{"asset_id": n, "name": n} for n in ["a", "b", "c", "d"]]
    edges = [{"source_id": s, "target_id": t, "edge_id": s + t}
             for s, t in [("a", "b"), ("b", "c"), ("c", "b"), ("d", "c")]]
    graph = LineageGraph(nodes, edges)
    shallow = graph.path_report("c", depth=1)
    assert shallow["truncated"]
    assert any(p["boundary"] == "depth" for p in shallow["paths"])
    report = graph.path_report("c", depth=10)
    assert any(p["boundary"] == "cycle" for p in report["paths"])
    assert all(len(p["nodes"]) <= 4 for p in report["paths"])
    limited = graph.path_report("c", limit=1, depth=10)
    assert limited["truncated"] and len(limited["paths"]) == 1
    assert graph.path_report("missing")["paths"] == []
