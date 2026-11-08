"""Labeled vendor examples prove these inputs, not universal dialect compatibility."""
import json
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from dataforge.graph import LineageGraph
from dataforge.ingestion import Importer
from dataforge.services import analyze, column_report
from dataforge.store import Store
from dataforge.transformations import trace_columns

FIXTURES = Path(__file__).parent / "fixtures" / "vendors"
EXPECTED = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("dialect", EXPECTED)
@pytest.mark.parametrize("newline", [b"\n", b"\r\n"], ids=["LF", "CRLF"])
def test_vendor_edges_direct_columns_temporary_identity_and_original_evidence(tmp_path: Path, dialect: str, newline: Any) -> None:
    """Verify that vendor edges direct columns temporary identity and original evidence.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        dialect: Dialect selected for the test case.
        newline: Newline value used by the test case.
    """
    expected = EXPECTED[dialect]
    path = FIXTURES / expected.get("file", dialect + ".sql")
    original = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", newline)
    code = original.decode("utf-8")
    store = Store(tmp_path)
    try:
        w = store.create_workspace(dialect)
        if dialect != "sas":
            store.set_setting(w, "dialect", dialect)
        Importer(store, w).files([(path.name, original)], {path.suffix})
        analyze(store, w)
        assets = store.assets(w)
        graph = LineageGraph(assets, store.edges(w))
        actual = {(graph.nodes[s]["name"], graph.nodes[t]["name"]) for s, t in graph.graph.edges}
        assert actual == {tuple(edge) for edge in expected["edges"]}  # precision and recall = 1 for this fixture
        assert {a["name"] for a in assets if a["temporary"]} == set(expected["temporary"])
        assert not [d for d in store.diagnostics(w) if d["severity"] == "error"]
        for table, columns in expected["columns"].items():
            asset = next(a for a in assets if a["name"] == table)
            assert {u["column_name"] for u in column_report(store, w, asset["asset_id"])} == set(columns)
        for edge in store.edges(w):
            assert edge["code"] in code
            assert edge["code"].splitlines() == code.splitlines()[edge["start_line"] - 1:edge["end_line"]]
            assert edge["source_hash"] == store.files(w)[0]["content_hash"]
        assert analyze(store, w)["cached"] == 1
        assert store.original(store.files(w)[0]["file_id"]) == original
    finally:
        store.close()


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"], ids=["LF", "CRLF"])
def test_databricks_stream_cte_and_positional_insert_publication(tmp_path, newline):
    path = FIXTURES / "databricks" / "stream_insert.sql"
    original = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", newline)
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace("Databricks")
        Importer(store, workspace).files([(path.name, original)], {".sql"}, sql_dialect="databricks")
        analyze(store, workspace)
        assets = store.assets(workspace)
        graph = LineageGraph(assets, store.edges(workspace))
        assert {(graph.nodes[s]["name"], graph.nodes[t]["name"]) for s, t in graph.graph.edges} == {
            ("main.lake.samples", "main.lake.target"),
        }
        target = next(a["asset_id"] for a in assets if a["name"] == "main.lake.target")
        for column, physical in [("sample_id", "id"), ("soil_ph", "soil.ph")]:
            trace = trace_columns(store, workspace, target, column, include_source=True)
            assert {(item["table"], item["column_name"]) for d in trace["derivations"]
                    for item in d["inputs"] if item["role"] == "value" and not item["scope"]} == {
                ("main.lake.samples", physical),
            }
            assert all(d["evidence"]["code"] in original.decode() for d in trace["derivations"])
        assert analyze(store, workspace)["cached"] == 1


def test_databricks_expectation_and_cdc_publication(tmp_path):
    path = FIXTURES / "databricks" / "pipeline.sql"
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace("Pipeline")
        Importer(store, workspace).files([(path.name, path.read_bytes())], {".sql"}, sql_dialect="databricks")
        analyze(store, workspace)
        assets = store.assets(workspace)
        graph = LineageGraph(assets, store.edges(workspace))
        assert {(graph.nodes[s]["name"], graph.nodes[t]["name"]) for s, t in graph.graph.edges} == {
            ("main.lake.events", "main.lake.clean"), ("main.lake.clean", "main.lake.current_events"),
        }
        target = next(a["asset_id"] for a in assets if a["name"] == "main.lake.current_events")
        trace = trace_columns(store, workspace, target, "amount", include_source=True)
        inputs = {(item["table"], item["column_name"], item["role"]) for d in trace["derivations"] for item in d["inputs"]}
        assert ("main.lake.clean", "change_time", "sequence") in inputs
        assert ("main.lake.clean", "change_time", "value") not in inputs
        assert ("main.lake.events", "raw_amount", "quality_drop") in inputs
        assert not store.rows("SELECT column_id FROM column_references WHERE column_name='positive'")
