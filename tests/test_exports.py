import json

from dataforge.exports import graph_data, graph_html, report_csv, report_html
from dataforge.graph import LineageGraph


def test_offline_graph_and_reports_escape_source() -> None:
    """Verify that offline graph and reports escape source."""
    name = '</script><img src=x onerror=alert(1)>'
    g = LineageGraph([{"asset_id": "a", "name": name, "kind": "table", "temporary": False}], [])
    output = graph_html(g)
    assert "<title>GraveTrail lineage</title>" in output
    assert "<title>GraveTrail report</title>" in report_html([])
    assert name not in output
    assert "https://" not in output and "<svg" in output
    assert json.loads(json.dumps(graph_data(g)))["nodes"][0]["name"] == name
    assert "&lt;img" in report_html([{"file": "<img src=x>"}])
    assert "'=formula" in report_csv([{"file": "=formula"}])


def test_path_csv_rows_keep_order_evidence_and_boundary() -> None:
    """Verify that path csv rows keep order evidence and boundary."""
    from dataforge.exports import path_rows

    graph = LineageGraph([{"asset_id": n, "name": n} for n in ["a", "b", "c"]], [
        {"source_id": "a", "target_id": "b", "edge_id": "ab", "statement_id": "s1", "start_line": 3},
        {"source_id": "b", "target_id": "c", "edge_id": "bc", "statement_id": "s2", "start_line": 7}])
    rows = path_rows(graph.path_report("c"))
    assert [(r["step"], r["source"], r["target"], r["statement_id"]) for r in rows] == [
        (1, "a", "b", "s1"), (2, "b", "c", "s2")]
    assert all(r["boundary"] == "root" and r["path"] == "a -> b -> c" for r in rows)
