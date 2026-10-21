"""Labeled vendor examples prove these inputs, not universal dialect compatibility."""
import json
from pathlib import Path
from typing import Any

import pytest

from dataforge.graph import LineageGraph
from dataforge.ingestion import Importer
from dataforge.services import analyze, column_report
from dataforge.store import Store

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
