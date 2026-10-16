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


def test_dependency_paths_keep_step_evidence_and_temporary_transforms():
    nodes = [{"asset_id": n, "name": n, "temporary": n == "temp", "kind": "table"}
             for n in ["raw", "temp", "mart", "report"]]
    edges = [{"source_id": s, "target_id": t, "edge_id": s + t, "statement_id": s,
              "relative_path": "job.sql", "start_line": 2, "end_line": 4, "source_hash": "abc"}
             for s, t in [("raw", "temp"), ("temp", "mart"), ("mart", "report")]]
    graph = LineageGraph(nodes, edges).simplified()
    result = graph.path_report("report", depth=10)
    assert result["truncated"] is False
    path = result["paths"][0]
    assert path["nodes"] == ["raw", "mart", "report"]
    assert path["boundary"] == "root"
    assert path["steps"][0]["intermediates"] == ["temp"]
    assert {e["edge_id"] for e in path["steps"][0]["evidence"]} == {"rawtemp", "tempmart"}
    assert path["steps"][0]["evidence"][0]["source_hash"] == "abc"
    downstream = graph.path_report("raw", direction="downstream", depth=10)
    assert downstream["paths"][0]["nodes"] == ["raw", "mart", "report"]
    assert downstream["paths"][0]["boundary"] == "terminal"


def test_path_limits_and_cycles_are_explicit_boundaries():
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


def test_missing_edge_endpoints_remain_diagnostics_without_anonymous_nodes():
    assets = [{"asset_id": n, "name": n, "kind": "table", "temporary": False}
              for n in ["raw", "mart"]]
    edges = [{"source_id": s, "target_id": t, "edge_id": s + t,
              "relative_path": "job.sql", "statement_id": "statement"}
             for s, t in [("raw", "mart"), ("missing", "mart"), ("raw", "missing")]]
    graph = LineageGraph(assets, edges)
    assert graph.search("") == assets
    assert set(graph.nodes) == {"raw", "mart"}
    assert list(graph.graph.edges) == [("raw", "mart")]
    assert graph.unresolved_edges == edges[1:]
    focused = graph.simplified().focus("mart")
    assert focused.unresolved_edges == edges[1:]
    assert focused.path_report("mart")["truncated"]
    assert len(focused.lineage_rows()) == 1
