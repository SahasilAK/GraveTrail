"""Static sample-archive acceptance and actual compact-response measurements; executes no source."""
import argparse
import json
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from dataforge.agent.contracts import AccessPolicy, AgentError, compact
from dataforge.agent.service import AgentService
from dataforge.graph import LineageGraph
from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


def verify(home: Path) -> dict[str, Any]:
    """Measure agent lineage acceptance and compact response sizes for sample ZIPs.

    Args:
        home: Disposable storage home used for both sample workspaces.

    Returns:
        Per-language acceptance, lineage, and response-size measurements.
    """
    store = Store(home)
    results = {}
    try:
        for extension in ("sql", "sas"):
            archive = Path("tests/sample_data") / f"dataforge_{extension}_lineage_test_project.zip"
            with ZipFile(archive) as zipped:
                name = next(n for n in zipped.namelist() if n.endswith("expected/lineage_manifest.json"))
                manifest = json.loads(zipped.read(name))
            w = store.create_workspace(f"Agent acceptance {extension.upper()}")
            report = Importer(store, w).zip(archive.read_bytes(), {"." + extension})
            cold = analyze(store, w)
            warm = analyze(store, w)
            store.set_setting(w, "agent_access", {"max_chars": 100000})
            service = AgentService(store, AccessPolicy(allow_write=True, workspaces=(w,)))
            try:
                query_error = None
                selected = "pub.all_kpis"
                try:
                    summary = service.call("lineage", w, asset=selected,
                        options={"limit": 500, "max_chars": 100000, "max_depth": 30, "collapse_temporary": True})
                except AgentError as exc:
                    query_error = exc.response()
                    summary = {"items": [], "total": 0, "complete": False}
                    selected = "stg.customers_clean"
                names = {i["name"] for i in summary["items"]}
                source_names = {a["target"] for a in manifest["assets"] if a["stage"] == "src"}
                graph = LineageGraph(store.assets(w), store.edges(w))
                simplified = graph.simplified()
                logical = {(simplified.nodes[s]["name"], simplified.nodes[t]["name"])
                           for s, t in simplified.graph.edges}
                expected = {(source, a["target"]) for a in manifest["assets"] for source in a["inputs"]}
                small = service.call("lineage", w, asset=selected, options={"limit": 10, "max_chars": 100000})
                detailed = service.call("lineage", w, asset=selected,
                                        options={"limit": 10, "detail_level": "detailed", "max_chars": 100000})
                sizes = {"summary_chars": len(compact(small)), "detailed_chars": len(compact(detailed))}
                result = {"workspace_id": w, "accepted_scripts": report.accepted,
                    "assets": len(store.assets(w)), "evidence_edges": len(store.edges(w)),
                    "logical_edges": len(logical), "missing_logical_edges": sorted(expected - logical),
                    "extra_logical_edges": sorted(logical - expected),
                    "upstream_count": summary["total"], "all_sources_reached": source_names <= names,
                    "stages_reached": sorted({n.split(".")[0] for n in names} | {"pub"}),
                    "temporary_assets": sum(a["temporary"] for a in store.assets(w)),
                    "complete": summary["complete"], "cold_analyzed": cold["analyzed"], "warm_cached": warm["cached"],
                    "issues": len(store.diagnostics(w)), **sizes,
                    "pub_all_kpis_error": query_error, "measurement_asset": selected,
                    "summary_estimated_tokens": (sizes["summary_chars"] + 3) // 4,
                    "detailed_estimated_tokens": (sizes["detailed_chars"] + 3) // 4,
                    "note": "Character/4 token estimates; static parsing only; no imported SQL/SAS execution"}
                results[extension] = result
                assert result["all_sources_reached"] and result["complete"], result
                assert not result["missing_logical_edges"] and not result["extra_logical_edges"], result
                assert sizes["summary_chars"] < sizes["detailed_chars"] / 2, result
            finally:
                service.close()
    finally:
        store.close()
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, required=True, help="Separate acceptance data home")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = verify(args.home)
    args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
