"""Opt-in live LLM check using synthetic SQL/SAS only; never reads project source data."""
import argparse
import json
import tempfile
import time
from pathlib import Path

from dataforge.ingestion import Importer
from dataforge.llm import Adapter, Profile, assist, merge_claims, response_object
from dataforge.services import analyze
from dataforge.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="OmniRoute")
    parser.add_argument("--base-url", default="http://localhost:20128/v1")
    parser.add_argument("--model", default="auto/best-reasoning")
    parser.add_argument("--key-env", default="OMNIROUTE_API_KEY")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    profile = Profile(provider=args.provider, base_url=args.base_url, model=args.model,
                      key_env=args.key_env, timeout=90, retries=0, max_tokens=2048)
    report = {"provider": profile.provider, "endpoint": profile.base_url, "model": profile.model,
              "credential_variable": profile.key_env, "synthetic_sources_only": True, "checks": []}
    started = time.perf_counter()
    try:
        with Adapter(profile) as adapter:
            report["discovered_models"] = len(adapter.models())
            raw, usage = adapter.complete('Return only JSON, no Markdown. Use key "status".',
                                          'Return {"status":"connected"}.')
        if response_object(raw).get("status") != "connected":
            raise ValueError("Connection response failed its contract")
        report["checks"].append({"name": "connection", "status": "passed", "usage": usage})
        with tempfile.TemporaryDirectory(prefix="dataforge-live-check-") as directory:
            store = Store(directory)
            try:
                workspace = store.create_workspace("Synthetic live LLM verification")
                sources = [("query.sql", b"create table mart.x as select id from raw.a;"),
                           ("step.sas", b"data mart.y;\nset raw.b;\nrun;")]
                Importer(store, workspace).files(sources, {".sql", ".sas"})
                analyze(store, workspace)
                for source in store.files(workspace):
                    result = assist(store, workspace, profile, source["file_id"], 1, source["line_count"],
                                    "sql_lineage" if source["extension"] == ".sql" else "sas_lineage")
                    if result["outcome"] != "validated" or not result["result"]["claims"]:
                        report["checks"].append({"name": source["extension"], "status": "failed",
                                                  "outcome": result["outcome"], "reason": result["reason"],
                                                  "usage": result["usage"]})
                        raise ValueError(f"{source['extension']} assistance was quarantined or produced no claims")
                    count = merge_claims(store, workspace, result["record_id"])
                    report["checks"].append({"name": source["extension"], "status": "passed",
                                              "merged_claims": count, "usage": result["usage"]})
                analyze(store, workspace)
                inferred = [e for e in store.edges(workspace) if e["method"] == "llm"]
                if len(inferred) < 2 or any(e["status"] != "inferred" or e["confidence"] > .8 for e in inferred):
                    raise ValueError("Merged inferred evidence did not survive reanalysis")
            finally:
                store.close()
            reopened = Store(directory)
            try:
                if len([e for e in reopened.edges(workspace) if e["method"] == "llm"]) < 2:
                    raise ValueError("Merged evidence did not persist across restart")
            finally:
                reopened.close()
        report["checks"].append({"name": "merge-refresh-restart", "status": "passed"})
        report["status"] = "passed"
    except Exception as exc:
        # Never include provider response bodies, source context, headers or credential values.
        report.update(status="failed", error_type=type(exc).__name__)
    report["duration_seconds"] = round(time.perf_counter() - started, 2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
