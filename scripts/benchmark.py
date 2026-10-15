"""Reproducible labeled synthetic SQL-chain benchmark; no user data needed."""
import argparse
import json
import platform
import tempfile
import time
from pathlib import Path

import duckdb
import sqlglot
import streamlit

from dataforge.graph import LineageGraph
from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=500)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.files <= 5000:
        parser.error("Use 1–5,000 files")
    with tempfile.TemporaryDirectory(prefix="dataforge-benchmark-") as directory:
        store = Store(directory)
        workspace = store.create_workspace("Synthetic benchmark")
        expected = {(f"mart.t{i - 1}" if i else "raw.seed", f"mart.t{i}") for i in range(args.files)}
        entries = [(f"jobs/{i // 100}/q{i}.sql", f"CREATE TABLE mart.t{i} AS SELECT id FROM {src};".encode())
                   for i, (src, _) in enumerate(sorted(expected, key=lambda p: int(p[1].split('t')[-1])))]
        start = time.perf_counter()
        report = Importer(store, workspace).files(entries, {".sql"})
        import_seconds = time.perf_counter() - start
        cold = analyze(store, workspace)
        warm = analyze(store, workspace)
        graph = LineageGraph(store.assets(workspace), store.edges(workspace))
        actual = {(graph.nodes[s]["name"], graph.nodes[t]["name"]) for s, t in graph.graph.edges}
        assert actual == expected
        last = graph.search(f"mart.t{args.files - 1}")
        node = next(a["asset_id"] for a in last if a["name"] == f"mart.t{args.files - 1}")
        start = time.perf_counter()
        for _ in range(100):
            focused = graph.focus(node, "upstream", depth=20, limit=150)
        latency = (time.perf_counter() - start) / 100
        result = {"workload": "labeled synthetic SQL chain, one CTAS per file", "files": report.accepted,
                  "assets": len(graph.nodes), "edges": graph.graph.number_of_edges(),
                  "import_seconds": round(import_seconds, 4), "cold_analysis_seconds": round(cold["duration"], 4),
                  "warm_analysis_seconds": round(warm["duration"], 4), "unchanged_parses_skipped": warm["cached"],
                  "focused_traversal_mean_ms": round(latency * 1000, 4), "focused_nodes": len(focused.nodes),
                  "fixture_precision": 1.0, "fixture_recall": 1.0,
                  "evidence_coverage": sum(bool(e["code"]) for e in store.edges(workspace)) / max(args.files, 1),
                  "python": platform.python_version(), "platform": platform.system(),
                  "streamlit": streamlit.__version__, "duckdb": duckdb.__version__, "sqlglot": sqlglot.__version__}
        store.close()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
