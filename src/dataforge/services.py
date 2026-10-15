"""Inventory-to-lineage analysis, transactional materialization and direct usage reports."""
from __future__ import annotations

import json
import logging
import posixpath
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from dataforge.configuration import ParsingSettings
from dataforge.models import AssetRef, Diagnostic, ParseResult, canonical, stable_id
from dataforge.parsers.csv import parse_csv
from dataforge.parsers.sas import parse_sas
from dataforge.parsers.sql import parse_sql
from dataforge.schemas import collect_schemas

PARSER_VERSION = "4"
log = logging.getLogger(__name__)


def analyze(store, workspace: str, file_ids: list[str] | None = None, force: bool = False,
            progress=None, cancelled=None) -> dict:
    with store.analysis_lock:
        return _analyze(store, workspace, file_ids, force, progress, cancelled)


def _analyze(store, workspace, file_ids, force, progress, cancelled):
    """Rebuild derived facts atomically; hashes skip unchanged parser work.

    A selection reparses selected files and reuses the existing cached analysis for others.
    Files with no matching cache outside a selection remain pending.
    """
    start = time.perf_counter()
    run_id = uuid.uuid4().hex
    config = ParsingSettings.model_validate({k: store.setting(workspace, k, default)
        for k, default in ParsingSettings().model_dump().items()}).model_dump()
    store.execute("INSERT INTO analysis_runs(run_id,workspace_id,status,configuration) VALUES (?,?,?,?)",
                  [run_id, workspace, "running", json.dumps(config)])
    analyzed = cached = 0
    results = []
    files = store.files(workspace)
    try:
        workers = min(8, max(1, int(store.setting(workspace, "parse_workers", 1))))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            jobs = []
            for metadata in files:
                fid = metadata["file_id"]
                key = stable_id(PARSER_VERSION, metadata["content_hash"], metadata["relative_path"], json.dumps(config, sort_keys=True))
                existing = store.rows("SELECT result FROM parse_cache WHERE cache_key=?", [key])
                selected = file_ids is None or fid in file_ids
                if existing and (not force or not selected):
                    jobs.append((metadata, key, ParseResult.from_dict(json.loads(existing[0]["result"])), None))
                elif selected:
                    jobs.append((metadata, key, None, pool.submit(_parse_inventory, store, metadata, config)))
            _collect_jobs(store, jobs, results, progress, cancelled)
        analyzed = sum(job[3] is not None for job in jobs)
        cached = len(jobs) - analyzed
        _restore_ai_results(store, workspace, results)
        with store.transaction():
            snapshot = _materialize(store, workspace, run_id, results, config)
            duration = time.perf_counter() - start
            store.execute("UPDATE analysis_runs SET status='completed',analyzed=?,cached=?,duration=?,snapshot=? WHERE run_id=?",
                          [analyzed, cached, duration, json.dumps(snapshot), run_id])
        return {"run_id": run_id, "analyzed": analyzed, "cached": cached, "duration": duration,
                "assets": len(snapshot["assets"]), "edges": len(snapshot["edges"])}
    except Exception as exc:
        store.execute("UPDATE analysis_runs SET status=?,error=?,duration=? WHERE run_id=?",
                      ["cancelled" if isinstance(exc, InterruptedError) else "failed",
                       type(exc).__name__, time.perf_counter() - start, run_id])
        log.exception("analysis_failed", extra={"run_id": run_id})
        raise


def source_dialect(metadata, config):
    dialect = config["dialect"]
    for prefix, override in sorted(config["dialect_by_folder"].items(), key=lambda p: len(p[0])):
        if metadata["relative_path"].startswith(prefix):
            dialect = override
    return dialect


def _parse_inventory(store, metadata, config):
    content = store.snapshot_content(metadata)
    ext = metadata["extension"]
    if ext == ".sql":
        return parse_sql(content, source_dialect(metadata, config))
    if ext == ".sas":
        return parse_sas(content, config["library_mappings"], config["macros"])
    return parse_csv(content, metadata["relative_path"])


def _collect_jobs(store, jobs, results, progress, cancelled):
    for i, (metadata, key, parsed, future) in enumerate(jobs):
        if cancelled and cancelled():
            raise InterruptedError("Analysis cancelled; previous lineage retained")
        if future is not None:
            parsed = future.result()
            store.execute("INSERT INTO parse_cache VALUES (?,?) ON CONFLICT(cache_key) DO UPDATE SET result=excluded.result",
                          [key, json.dumps(parsed.to_dict())])
        results.append((metadata, parsed))
        if progress:
            progress((i + 1) / max(len(jobs), 1), metadata["relative_path"])


def _materialize(store, workspace, run_id, results, config):
    norm = (lambda n: n.strip()) if config["case_sensitive"] else canonical
    known = {}
    for metadata, parsed in results:
        for ref in [*parsed.assets, *(r for op in parsed.operations for r in [*op.sources, *op.targets])]:
            known[norm(ref.name)] = ref
    registry, aliases = {}, set()

    def resolve(ref: AssetRef, metadata, parsed):
        name = ref.name
        key = norm(name)
        changed = False
        if ref.kind == "file":
            path = name.removeprefix("file:")
            relative = "file:" + posixpath.normpath(posixpath.join(posixpath.dirname(metadata["relative_path"]), path))
            if key not in known and norm(relative) in known:
                key = norm(relative)
                name = known[key].name
        elif "." not in key:
            candidates = [k for k, r in known.items() if r.kind != "file" and "." in k and k.rsplit(".", 1)[-1] == key]
            if len(candidates) == 1:
                old = key
                key, name = candidates[0], known[candidates[0]].name
                changed = True
                aliases.add((workspace, old, stable_id(workspace, key), "unique-qualified-match"))
            elif len(candidates) > 1:
                d = Diagnostic(f"Ambiguous table {name}; candidates: {', '.join(candidates)}", symbol=name)
                if not any(x.message == d.message for x in parsed.diagnostics):
                    parsed.diagnostics.append(d)
        aid = stable_id(workspace, key)
        existing_ref = known.get(key, ref)
        temporary = ref.temporary or existing_ref.temporary
        if aid not in registry:
            registry[aid] = [aid, workspace, name, key, ref.kind, temporary, "{}"]
        else:
            registry[aid][5] |= temporary
        return aid, changed

    schemas = collect_schemas(results, workspace, norm, resolve)
    rows = {"assets": [], "statements": [], "operations": [], "operation_assets": [], "edges": [],
            "column_usages": [], "diagnostics": [], "asset_aliases": []}
    statuses = []
    for metadata, parsed in results:
        fid = metadata["file_id"]
        for ref in parsed.assets:
            aid, _ = resolve(ref, metadata, parsed)
            registry[aid][6] = json.dumps(parsed.metadata)
        for i, op in enumerate(parsed.operations):
            sid = stable_id(workspace, fid, str(i), metadata["content_hash"])
            oid = stable_id(sid, op.kind)
            rows["statements"].append([sid, workspace, fid, op.start, op.end, op.code, metadata["content_hash"]])
            rows["operations"].append([oid, workspace, sid, op.kind, op.method, op.confidence, json.dumps(op.warnings)])
            inputs = [resolve(s, metadata, parsed) for s in op.sources]
            outputs = [resolve(t, metadata, parsed) for t in op.targets]
            for role, refs in [("input", inputs), ("output", outputs)]:
                for aid, _ in set(refs):
                    rows["operation_assets"].append([workspace, oid, aid, role])
            for source, source_inferred in inputs:
                for target, target_inferred in outputs:
                    inferred = source_inferred or target_inferred or op.method == "llm"
                    eid = stable_id(oid, source, target)
                    rows["edges"].append([eid, workspace, source, target, oid, sid, fid, op.kind,
                                          op.method, min(op.confidence, .85) if inferred else op.confidence,
                                          "inferred" if inferred else "verified", run_id])
            for j, u in enumerate(op.usages):
                aid, inferred = resolve(AssetRef(u.table), metadata, parsed)
                schema = schemas.get(aid, {})
                expanded = (u.column == "*" and u.wildcard_safe and config["expand_wildcards"]
                            and schema.get("schema_status") == "declared")
                columns = [c["name"] for c in schema["columns"]] if expanded else [u.column]
                for column in columns:
                    rows["column_usages"].append([stable_id(oid, str(j), column), workspace, aid, column,
                        u.context + " (schema expansion)" if expanded else u.context, u.alias, u.expression,
                        "inferred" if inferred or expanded else u.status, sid, fid, oid])
        for i, d in enumerate(parsed.diagnostics):
            rows["diagnostics"].append([stable_id(fid, str(i)), workspace, fid, d.line, d.severity, d.message, d.symbol])
        errors = any(d.severity == "error" for d in parsed.diagnostics)
        status = "failed" if errors and not parsed.operations and not parsed.assets else (
            "partial" if any(d.severity != "info" for d in parsed.diagnostics) else "success")
        statuses.append([status, json.dumps(parsed.metadata), "\n".join(d.message for d in parsed.diagnostics), fid, metadata["content_hash"]])
    for aid, schema in schemas.items():
        if aid in registry:
            registry[aid][6] = json.dumps(schema)
    rows["assets"] = list(registry.values())
    rows["asset_aliases"] = list(aliases)
    for table, values in rows.items():
        store.execute(f"DELETE FROM {table} WHERE workspace_id=?", [workspace])
        if values:
            store.db.executemany(f"INSERT INTO {table} VALUES ({','.join('?' for _ in values[0])})", values)
    if statuses:
        store.db.executemany("UPDATE source_files SET parsing_status=?,metadata=?,error_details=? WHERE file_id=? AND content_hash=?", statuses)
    return {"assets": [{"name": a[3], "kind": a[4]} for a in registry.values()],
            "edges": sorted({(e[2], e[3]) for e in rows["edges"]}),
            "files": {m["relative_path"]: m["content_hash"] for m, _ in results}}


def column_report(store, workspace: str, asset_id: str) -> list[dict]:
    rows = store.rows("""SELECT u.*,a.name AS source_table,a.metadata AS schema_metadata,f.file_name,f.relative_path,s.start_line,s.end_line,s.code,s.content_hash AS source_hash,
        o.kind AS operation_type FROM column_usages u JOIN assets a ON u.asset_id=a.asset_id
        JOIN source_files f ON u.file_id=f.file_id JOIN statements s ON u.statement_id=s.statement_id
        JOIN operations o ON u.operation_id=o.operation_id WHERE u.workspace_id=? AND u.asset_id=?
        ORDER BY u.column_name,f.relative_path,s.start_line""", [workspace, asset_id])
    for row in rows:
        metadata = json.loads(row.pop("schema_metadata"))
        row["schema_source"] = "; ".join(f"{e['relative_path']}:{e['start_line']}–{e['end_line']}"
            for e in metadata.get("schema_evidence", [])) if "(schema expansion)" in row["context"] else ""
    return rows


def compare_runs(first: dict, second: dict) -> dict:
    a, b = json.loads(first["snapshot"]), json.loads(second["snapshot"])
    aset, bset = {x["name"] for x in a["assets"]}, {x["name"] for x in b["assets"]}
    ae, be = {tuple(e) for e in a["edges"]}, {tuple(e) for e in b["edges"]}
    return {"added_assets": sorted(bset - aset), "removed_assets": sorted(aset - bset),
            "added_edges": sorted(be - ae), "removed_edges": sorted(ae - be),
            "changed_files": sorted(k for k in set(a["files"]) | set(b["files"]) if a["files"].get(k) != b["files"].get(k))}


def _restore_ai_results(store, workspace, results):
    from dataforge.llm import GroundedResponse, validate_response
    from dataforge.models import Operation

    known = {r.name for _, parsed in results for r in [*parsed.assets,
             *(ref for op in parsed.operations for ref in [*op.sources, *op.targets])]}
    by_file = {m["file_id"]: (m, parsed) for m, parsed in results}
    for record in store.rows("SELECT * FROM llm_records WHERE workspace_id=? AND outcome='merged'", [workspace]):
        if record["task"] not in {"sas_lineage", "sql_lineage", "lineage_validation"}:
            continue
        details = json.loads(record["details"])
        if record["file_id"] not in by_file:
            continue
        metadata, parsed = by_file[record["file_id"]]
        if metadata["content_hash"] != details["content_hash"]:
            continue
        response = GroundedResponse.model_validate(details["result"])
        content = store.snapshot_content(metadata)
        try:
            validate_response(response, content, known, 1, len(content.splitlines()))
        except ValueError:
            continue
        for c in response.claims:
            parsed.operations.append(Operation(c.operation, [AssetRef(c.source)], [AssetRef(c.target)],
                c.quote, c.start_line, c.end_line, "llm", min(c.confidence, .8), warnings=[c.explanation]))
