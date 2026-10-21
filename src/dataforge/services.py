"""Inventory-to-lineage analysis, transactional materialization and direct usage reports."""
from __future__ import annotations

import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from dataforge.asset_identity import AssetResolver, asset_label, source_job
from dataforge.configuration import ParsingSettings
from dataforge.graph_image_service import export_graph_image as export_graph_image
from dataforge.models import AssetRef, ParseResult, operation_ids, stable_id
from dataforge.parsers.csv import parse_csv
from dataforge.parsers.sas import parse_sas
from dataforge.parsers.sql import parse_sql
from dataforge.schemas import collect_schemas

PARSER_VERSION = "14"
log = logging.getLogger(__name__)


def analysis_is_current(store, workspace):
    files = store.files(workspace)
    runs = store.rows("SELECT snapshot,configuration FROM analysis_runs WHERE workspace_id=? AND status='completed' ORDER BY created_at DESC LIMIT 1", [workspace])
    config = ParsingSettings.model_validate({key: store.setting(workspace, key, default)
        for key, default in ParsingSettings().model_dump().items()}).model_dump()
    return bool(runs) and all(f['parsing_status'] != 'pending' for f in files) and (
        json.loads(runs[0]['snapshot'])['files'] == {f['relative_path']: f['content_hash'] for f in files}
        and json.loads(runs[0]['configuration']) == config)


def export_lineage_excel(store, workspace, asset, *, direction='upstream', max_paths=50, max_depth=15,
                         max_relationships=2000, collapse_temporary=None, include_evidence=False,
                         include_source_text=False):
    """Snapshot committed facts/settings, then build a bounded offline workbook; callers authorize disclosure."""
    from dataforge.excel_exports import MAX_SECONDS, MAX_TEXT_BYTES, lineage_xlsx
    from dataforge.graph import LineageGraph

    started = time.monotonic()
    if direction not in {'upstream', 'downstream'}:
        raise ValueError('Use upstream/downstream for an Excel path export')
    if any(type(value) is not int or not 1 <= value <= maximum for value, maximum in [
        (max_paths, 500), (max_depth, 30), (max_relationships, 20000)]):
        raise ValueError('Use 1–500 paths, 1–30 depth and 1–20000 relationships')
    if any(type(value) is not bool for value in [include_evidence, include_source_text]) or (
        collapse_temporary is not None and type(collapse_temporary) is not bool
    ):
        raise ValueError('Evidence, source text and temporary-stage options must be booleans')
    if include_source_text and not include_evidence:
        raise ValueError('Source text requires the Evidence sheet')
    with store.transaction():
        workspace_rows = store.rows('SELECT name FROM workspaces WHERE workspace_id=?', [workspace])
        if not workspace_rows:
            raise ValueError('Select an existing workspace')
        counts = store.rows('SELECT count(*) AS n, coalesce(sum(length(name)+length(metadata)),0) AS text_size FROM assets WHERE workspace_id=?', [workspace])[0]
        edge_count = store.rows('SELECT count(*) AS n FROM edges WHERE workspace_id=?', [workspace])[0]['n']
        if counts['n'] > 20000 or edge_count > 100000:
            raise ValueError('Excel graph exceeds 20000 assets or 100000 evidence edges; narrow workspace')
        text_size = store.rows("""SELECT coalesce(sum(length(f.relative_path) + ? * length(s.code)),0) AS n
            FROM edges e JOIN statements s ON e.statement_id=s.statement_id
            JOIN source_files f ON e.file_id=f.file_id WHERE e.workspace_id=?""",
            [int(include_source_text), workspace])[0]['n']
        # UTF-8 can take four bytes per character. Bound input before loading text.
        if (text_size + counts['text_size']) * 4 > MAX_TEXT_BYTES:
            raise ValueError('Excel graph text exceeds input budget; exclude source text or narrow workspace')
        assets = store.rows('SELECT * FROM assets WHERE workspace_id=? ORDER BY asset_id', [workspace])
        if not any(a['asset_id'] == asset for a in assets):
            raise ValueError('Select an existing exact asset ID')
        code = 's.code' if include_source_text else "'' AS code"
        edges = store.rows(f"""SELECT e.*,s.start_line,s.end_line,{code},s.content_hash AS source_hash,f.relative_path
            FROM edges e JOIN statements s ON e.statement_id=s.statement_id
            JOIN source_files f ON e.file_id=f.file_id WHERE e.workspace_id=? ORDER BY e.edge_id""", [workspace])
        confidence = store.setting(workspace, 'min_lineage_confidence', 0.)
        inferred = store.setting(workspace, 'include_inferred', True)
        collapse = store.setting(workspace, 'collapse_temporary', False) if collapse_temporary is None else collapse_temporary
        revisions = store.rows("SELECT run_id FROM analysis_runs WHERE workspace_id=? AND status='completed' ORDER BY created_at DESC LIMIT 1", [workspace])
        current = analysis_is_current(store, workspace)
        diagnostic_count = store.rows("SELECT count(*) AS n FROM diagnostics WHERE workspace_id=? AND severity IN ('warning','error')", [workspace])[0]['n']
        scope = {'workspace': workspace_rows[0]['name'], 'workspace_id': workspace,
            'revision': revisions[0]['run_id'] if revisions else 'unanalysed', 'analysis_current': current,
            'export_time': datetime.now(timezone.utc).isoformat(), 'max_relationships': max_relationships,
            'temporary_policy': 'collapsed' if collapse else 'included',
            'filters': f'minimum confidence {confidence:g}; inferred {"included" if inferred else "excluded"}',
            'warnings': []}
        if not current:
            scope['warnings'].append('Analysis is not current; pending imports/settings changes are not represented.')
        if diagnostic_count:
            scope['warnings'].append(f'{diagnostic_count} stored analysis warnings/errors; unsupported coverage may remain.')
    graph = LineageGraph(assets, edges, confidence, inferred)
    if collapse:
        graph = graph.simplified(keep=[asset], preserve_paths=True, evidence_limit=20000)
    report = graph.path_report(asset, direction, max_paths, max_depth,
        max_relationships=max_relationships, max_evidence=20000, include_code=include_source_text)
    if time.monotonic() - started > MAX_SECONDS:
        raise ValueError('Excel export time limit exceeded; narrow the selection and retry')
    data, metadata = lineage_xlsx(report, graph.nodes, scope, include_evidence=include_evidence,
                                 include_source_text=include_source_text)
    if time.monotonic() - started > MAX_SECONDS:
        raise ValueError('Excel export time limit exceeded; narrow the selection and retry')
    versions = {}
    for path in report['paths']:
        for step in path['steps']:
            for evidence in step['evidence']:
                versions.setdefault(evidence['file_id'], set()).add(evidence['source_hash'])
    for evidence in report.get('boundaries', []):
        if evidence.get('file_id') and evidence.get('source_hash'):
            versions.setdefault(evidence['file_id'], set()).add(evidence['source_hash'])
    metadata['source_versions'] = {fid: sorted(hashes) for fid, hashes in versions.items()}
    return data, metadata


def analyze(store, workspace: str, file_ids: list[str] | None = None, force: bool = False,
            progress=None, cancelled=None) -> dict:
    from dataforge.ai_analysis_store import active_project_runs
    with store.analysis_lock:
        if active_project_runs(store, workspace):
            raise ValueError('An active AI analysis blocks parser publication')
        return _analyze(store, workspace, file_ids, force, progress, cancelled)


def _analyze(store, workspace, file_ids, force, progress, cancelled):
    """Rebuild derived facts atomically; hashes skip unchanged parser work.

    A selection reparses selected files and reuses compatible cached analysis for others.
    Previously analyzed files whose cache became incompatible are refreshed to preserve a
    coherent workspace. Newly imported unselected files remain pending.
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
                elif selected or metadata["parsing_status"] != "pending":
                    jobs.append((metadata, key, None, pool.submit(_parse_inventory, store, metadata, config)))
            _collect_jobs(store, jobs, results, progress, cancelled)
        analyzed = sum(job[3] is not None for job in jobs)
        cached = len(jobs) - analyzed
        _restore_ai_results(store, workspace, results, config)
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
    dialect = config.get("dialect_by_extension", {}).get(metadata["extension"], config["dialect"])
    for prefix, override in sorted(config["dialect_by_folder"].items(), key=lambda p: len(p[0])):
        if metadata["relative_path"].startswith(prefix):
            dialect = override
    return dialect


def prepare_analysis_results(store, workspace, file_ids=None, force=False, progress=None, cancelled=None):
    """Collect parser results offline without publishing or restoring selected AI facts.

    The orchestrator snapshots/CAS-checks inputs. Unselected accepted representations
    remain intact, while selected extraction always starts with a parser-only cache.
    """
    from dataforge.ai_analysis_store import accepted_file_ids, load_accepted_file_results

    started = time.perf_counter()
    config = ParsingSettings.model_validate({k: store.setting(workspace, k, default)
        for k, default in ParsingSettings().model_dump().items()}).model_dump()
    accepted = load_accepted_file_results(store, workspace, config)
    saved_scope = accepted_file_ids(store, workspace)
    if file_ids is not None:
        incompatible = (saved_scope - set(file_ids)) & {m['file_id'] for m in store.files(workspace)} - set(accepted)
        if incompatible:
            raise ValueError('Saved AI facts for unselected files are incompatible; include affected files for reanalysis')
    results, jobs = [], []
    with ThreadPoolExecutor(max_workers=min(8, max(1, int(store.setting(workspace, 'parse_workers', 1))))) as pool:
        for metadata in store.files(workspace):
            fid = metadata['file_id']
            selected = file_ids is None or fid in file_ids
            if not selected and fid in accepted:
                results.append(accepted[fid])
                continue
            key = stable_id(PARSER_VERSION, metadata['content_hash'], metadata['relative_path'], json.dumps(config, sort_keys=True))
            cached = store.rows('SELECT result FROM parse_cache WHERE cache_key=?', [key])
            if cached and (not force or not selected):
                jobs.append((metadata, key, ParseResult.from_dict(json.loads(cached[0]['result'])), None))
            elif selected or metadata['parsing_status'] != 'pending':
                jobs.append((metadata, key, None, pool.submit(_parse_inventory, store, metadata, config)))
        _collect_jobs(store, jobs, results, progress, cancelled)
    return results, config, {'analyzed': sum(j[3] is not None for j in jobs),
        'cached': len(results) - sum(j[3] is not None for j in jobs), 'started': started}


def publish_analysis_results(store, workspace, results, config, counts, *, run_id=None,
                             progress=None, cancelled=None):
    """Publish prepared normalized facts; caller owns coordination/CAS transaction."""
    if cancelled and cancelled():
        raise InterruptedError('Analysis cancelled; previous lineage retained')
    run_id = run_id or uuid.uuid4().hex
    store.execute('INSERT INTO analysis_runs(run_id,workspace_id,status,configuration) VALUES (?,?,?,?)',
                  [run_id, workspace, 'running', json.dumps(config)])
    snapshot = _materialize(store, workspace, run_id, results, config)
    duration = time.perf_counter() - counts.get('started', time.perf_counter())
    store.execute("UPDATE analysis_runs SET status='completed',analyzed=?,cached=?,duration=?,snapshot=? WHERE run_id=?",
        [counts.get('analyzed', 0), counts.get('cached', 0), duration, json.dumps(snapshot), run_id])
    return {'run_id': run_id, 'analyzed': counts.get('analyzed', 0), 'cached': counts.get('cached', 0),
            'duration': duration, 'assets': len(snapshot['assets']), 'edges': len(snapshot['edges'])}


def _parse_inventory(store, metadata, config):
    content = store.snapshot_content(metadata)
    ext = metadata["extension"]
    if ext == ".sql":
        return parse_sql(content, source_dialect(metadata, config))
    if ext == ".sas":
        return parse_sas(content, config["library_mappings"], config["macros"], source_dialect(metadata, config))
    return parse_csv(content, metadata["relative_path"], sample_size=config["csv_sample_rows"])


def _collect_jobs(store, jobs, results, progress, cancelled):
    for i, (metadata, key, parsed, future) in enumerate(jobs):
        if cancelled and cancelled():
            raise InterruptedError("Analysis cancelled; previous lineage retained")
        if future is not None:
            parsed = future.result()
            if (any(d.severity == 'error' for d in parsed.diagnostics)
                    and store.rows('SELECT 1 FROM statements WHERE file_id=? LIMIT 1', [metadata['file_id']])):
                raise ValueError('Parsing failed; previous committed analysis retained')
            store.execute("INSERT INTO parse_cache VALUES (?,?) ON CONFLICT(cache_key) DO UPDATE SET result=excluded.result",
                          [key, json.dumps(parsed.to_dict())])
        results.append((metadata, parsed))
        if progress:
            progress((i + 1) / max(len(jobs), 1), metadata["relative_path"])


def _materialize(store, workspace, run_id, results, config):
    from dataforge.transformations import materialize_columns
    resolver = AssetResolver(workspace, results, config)
    resolve = resolver.resolve
    registry, aliases = resolver.registry, resolver.aliases

    schemas = collect_schemas(results, workspace, resolver)
    rows = {"assets": [], "statements": [], "operations": [], "operation_assets": [], "edges": [],
            "column_usages": [], "diagnostics": [], "asset_aliases": []}
    column_rows = materialize_columns(workspace, run_id, results, resolver, schemas, config)
    statuses = []
    for metadata, parsed in results:
        fid = metadata["file_id"]
        parsed.metadata["job_id"] = source_job(metadata, config)
        for ref in parsed.assets:
            aid, _ = resolve(ref, metadata, parsed)
            registry[aid][6] = json.dumps({**{k: v for k, v in parsed.metadata.items() if k != "job_id"},
                                         **json.loads(registry[aid][6])})
        for i, op in enumerate(parsed.operations):
            sid, oid = operation_ids(workspace, metadata, i, op)
            rows["statements"].append([sid, workspace, fid, op.start, op.end, op.code, metadata["content_hash"]])
            rows["operations"].append([oid, workspace, sid, op.kind, op.method,
                min(op.confidence, .8) if op.method == 'ai-project' else op.confidence, json.dumps(op.warnings)])
            inputs = [resolve(s, metadata, parsed, "input") for s in op.sources]
            outputs = [resolve(t, metadata, parsed, "output" if op.method != "llm" else "reference") for t in op.targets]
            for role, refs in [("input", inputs), ("output", outputs)]:
                for aid, _ in set(refs):
                    rows["operation_assets"].append([workspace, oid, aid, role])
            pairs = op.table_pairs if op.table_pairs is not None else [(s, t) for s in range(len(inputs)) for t in range(len(outputs))]
            for pair in pairs:
                if (len(pair) != 2 or any(type(index) is not int for index in pair)
                        or not 0 <= pair[0] < len(inputs) or not 0 <= pair[1] < len(outputs)):
                    raise ValueError('Invalid accepted table pair')
                source, source_inferred = inputs[pair[0]]
                target, target_inferred = outputs[pair[1]]
                inferred = source_inferred or target_inferred or op.method in {'llm', 'ai-project'}
                eid = stable_id(oid, source, target)
                rows["edges"].append([eid, workspace, source, target, oid, sid, fid, op.kind,
                    op.method, min(op.confidence, .8 if op.method in {'llm', 'ai-project'} else .85) if inferred else op.confidence,
                    "unresolved" if any(registry[a][4] == "unresolved" for a in (source, target)) else "inferred" if inferred else "verified", run_id])
            for j, u in enumerate(op.usages):
                aid, inferred = resolve(AssetRef(u.table), metadata, parsed)
                schema = schemas.get(aid, {})
                expanded = (registry[aid][4] != "unresolved" and u.column == "*" and u.wildcard_safe and config["expand_wildcards"]
                            and schema.get("schema_status") == "declared")
                columns = [c["name"] for c in schema["columns"]] if expanded else [u.column]
                for column in columns:
                    rows["column_usages"].append([stable_id(oid, str(j), column), workspace, aid, column,
                        u.context + " (schema expansion)" if expanded else u.context, u.alias, u.expression,
                        "unresolved" if registry[aid][4] == "unresolved" or (u.status == 'unresolved' and not expanded) else "inferred" if inferred or expanded or op.method == 'ai-project' else u.status, sid, fid, oid])
        for i, d in enumerate(parsed.diagnostics):
            rows["diagnostics"].append([stable_id(fid, str(i)), workspace, fid, d.line, d.severity, d.message, d.symbol])
        errors = any(d.severity == "error" for d in parsed.diagnostics)
        status = "failed" if errors and not parsed.operations and not parsed.assets else (
            "partial" if any(d.severity != "info" for d in parsed.diagnostics) else "success")
        statuses.append([status, json.dumps(parsed.metadata), "\n".join(d.message for d in parsed.diagnostics), fid, metadata["content_hash"]])
    for aid, schema in schemas.items():
        if aid in registry and registry[aid][4] != "unresolved":
            registry[aid][6] = json.dumps({**schema, **json.loads(registry[aid][6])})
    rows["assets"] = list(registry.values())
    rows["asset_aliases"] = list(aliases)
    rows.update(column_rows)
    rows['column_analysis'] = [[workspace, run_id, PARSER_VERSION]]
    for table, values in rows.items():
        store.execute(f"DELETE FROM {table} WHERE workspace_id=?", [workspace])
        if values:
            store.db.executemany(f"INSERT INTO {table} VALUES ({','.join('?' for _ in values[0])})", values)
    if statuses:
        store.db.executemany("UPDATE source_files SET parsing_status=?,metadata=?,error_details=? WHERE file_id=? AND content_hash=?", statuses)
    from dataforge.ai_analysis_store import refresh_published_support
    refresh_published_support(store, workspace, results)
    return {"assets": [{"name": a[3], "kind": a[4], "job_id": json.loads(a[6]).get("job_id")} for a in registry.values()],
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


def column_names(rows: list[dict], metadata: dict) -> tuple[list[str], list[str] | None]:
    """Distinct direct names and schema columns without known usage; None means unknown coverage."""
    names = {r["column_name"] for r in rows}
    used = sorted(names - {"*"}, key=str.casefold)
    if metadata.get("schema_status") != "declared" or "*" in names:
        return used, None
    declared = {c["name"] for c in metadata["columns"]}
    if not names <= declared:
        return used, None
    return used, sorted(declared - names, key=str.casefold)


def compare_runs(first: dict, second: dict) -> dict:
    a, b = json.loads(first["snapshot"]), json.loads(second["snapshot"])
    aset, bset = {asset_label(x) for x in a["assets"]}, {asset_label(x) for x in b["assets"]}
    ae, be = {tuple(e) for e in a["edges"]}, {tuple(e) for e in b["edges"]}
    return {"added_assets": sorted(bset - aset), "removed_assets": sorted(aset - bset),
            "added_edges": sorted(be - ae), "removed_edges": sorted(ae - be),
            "changed_files": sorted(k for k in set(a["files"]) | set(b["files"]) if a["files"].get(k) != b["files"].get(k))}


def _restore_ai_results(store, workspace, results, config):
    from dataforge.ai_analysis_store import load_accepted_file_results

    accepted = load_accepted_file_results(store, workspace, config)
    for index, (metadata, parsed) in enumerate(results):
        if metadata['file_id'] in accepted:
            results[index] = accepted[metadata['file_id']]
    restore_manual_ai_results(store, workspace, results, config)


def restore_manual_ai_results(store, workspace, results, config):
    """Reapply explicit legacy merges without replacing selected project operations."""
    from dataforge.llm import GroundedResponse, validate_response
    from dataforge.models import Operation

    resolver = AssetResolver(workspace, results, config)
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
        if details.get("job_id", "workspace") != source_job(metadata, config):
            continue
        response = GroundedResponse.model_validate(details["result"])
        content = store.snapshot_content(metadata)
        try:
            validate_response(response, content, resolver.known_names(metadata), 1, len(content.splitlines()))
        except ValueError:
            continue
        for c in response.claims:
            op = Operation(c.operation, [AssetRef(c.source)], [AssetRef(c.target)],
                c.quote, c.start_line, c.end_line, "llm", min(c.confidence, .8), warnings=[c.explanation])
            if not any(existing == op for existing in parsed.operations):
                parsed.operations.append(op)
