"""Workspace-owned snapshots, optimistic revisions and scoped review records."""
from __future__ import annotations

import json
import re
import uuid
import zlib
from collections import Counter, defaultdict
from difflib import unified_diff
from functools import lru_cache

import sqlglot

from dataforge.connections import current_connections
from dataforge.dbt.models import DbtSettings
from dataforge.ingestion import decode
from dataforge.lineage_builder import load_builder
from dataforge.migration import engine
from dataforge.migration.sources import SECRET_FILE
from dataforge.migration.targets import warehouse
from dataforge.services import PARSER_VERSION, source_dialect

TABLES = ("migration_activity", "migration_revisions", "migration_sources", "migration_projects")
SCHEMA = """
CREATE TABLE migration_projects(
    workspace_id VARCHAR, project_id VARCHAR, name VARCHAR, revision_id VARCHAR, snapshot VARCHAR,
    created_at TIMESTAMP DEFAULT current_timestamp, PRIMARY KEY(workspace_id, project_id)
);
CREATE TABLE migration_sources(
    workspace_id VARCHAR, project_id VARCHAR, file_id VARCHAR, body BLOB,
    PRIMARY KEY(workspace_id, project_id, file_id)
);
CREATE TABLE migration_revisions(
    workspace_id VARCHAR, project_id VARCHAR, revision_id VARCHAR, body BLOB,
    created_at TIMESTAMP DEFAULT current_timestamp, PRIMARY KEY(workspace_id, project_id, revision_id)
);
CREATE TABLE migration_activity(
    workspace_id VARCHAR, project_id VARCHAR, activity_id VARCHAR, kind VARCHAR, status VARCHAR, body BLOB,
    created_at TIMESTAMP DEFAULT current_timestamp, PRIMARY KEY(workspace_id, project_id, activity_id)
);
"""


def _dump(value):
    return zlib.compress(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(), level=3)


def _read(body):
    return json.loads(zlib.decompress(body))


def latest_run(store, workspace):
    rows = store.rows("""SELECT run_id FROM analysis_runs WHERE workspace_id=? AND status='completed'
                      ORDER BY created_at DESC LIMIT 1""", [workspace])
    return rows[0]["run_id"] if rows else None


def freeze(store, workspace, *, selection, analysis_run=None, selected_outputs=None,
           builder_revision=None, builder_tables=None, dialects=None, **settings):
    """Capture a bounded immutable snapshot using only retained, workspace-owned versions."""
    warehouse(settings)
    dialects = dialects or {}
    if any(value not in sqlglot.Dialect.classes for value in dialects.values()):
        raise ValueError("Choose a known SQL source dialect")
    inventory = store.files(workspace)
    inventory_ids = {row["file_id"] for row in inventory}
    if set(selection or ()) - inventory_ids or set(dialects) - inventory_ids:
        raise ValueError("The source selection changed. Refresh the workspace.")
    picked = set(selection or ())
    snapshot = {**settings, "sources": [], "analysis_run": analysis_run, "analysis_gaps": [],
                "selected_outputs": selected_outputs or [], "known_outputs": {}, "original_edges": []}
    analysis, preferences = {}, {"dialect": store.setting(workspace, "dialect", "")}
    if analysis_run:
        records = store.rows(
            "SELECT snapshot,configuration FROM analysis_runs WHERE workspace_id=? AND run_id=? AND status='completed'",
            [workspace, analysis_run])
        if not records:
            raise ValueError("The selected committed analysis is unavailable")
        analysis = json.loads(records[0]["snapshot"])
        preferences = json.loads(records[0]["configuration"])
        snapshot.update(parser_version=analysis.get("parser_version"), original_edges=analysis.get("edges", []))
        if analysis.get("parser_version") != PARSER_VERSION:
            snapshot["analysis_gaps"].append("Analysis uses an older parser. Inspect the retained source diagnostics.")
        job = store.rows("SELECT status,summary FROM ai_analysis_runs WHERE workspace_id=? AND analysis_run_id=?",
                         [workspace, analysis_run])
        if any(row["status"] != "committed" or "required_work_unresolved" in
               json.loads(row["summary"] or "{}").get("reasons", []) for row in job):
            snapshot["analysis_gaps"].append("The AI analysis may be incomplete. Review its outcome and opaque regions.")
        if latest_run(store, workspace) == analysis_run:
            asset_names = {row["asset_id"]: row["canonical_name"] for row in store.assets(workspace)}
            snapshot["original_edge_labels"] = [[asset_names.get(key, key) for key in pair]
                                                 for pair in snapshot["original_edges"]]
            for row in store.rows("""SELECT DISTINCT s.file_id,a.canonical_name
                FROM operation_assets oa JOIN operations o USING(workspace_id,operation_id)
                JOIN statements s USING(workspace_id,statement_id) JOIN assets a USING(workspace_id,asset_id)
                WHERE oa.workspace_id=? AND oa.role IN ('output','target','write')""", [workspace]):
                snapshot["known_outputs"].setdefault(row["file_id"], []).append(row["canonical_name"])
    required = analysis.get("files", {})
    total = 0
    dbt_settings = DbtSettings.model_validate(store.setting(workspace, "dbt", {}))
    roots = {json.loads(row["metadata"] or "{}").get("dbt_root") for row in inventory if row["file_id"] in picked}
    roots.discard(None)
    if len(inventory) > 10_000:
        raise ValueError("Workspace exceeds 10,000 files. Use a smaller source workspace.")
    for row in inventory:
        path = row["relative_path"]
        meta = json.loads(row["metadata"] or "{}")
        kind = "dbt" if meta.get("source_kind") == "dbt" else row["extension"].lstrip(".")
        chosen = row["file_id"] in picked or meta.get("dbt_root") in roots
        expected = required.get(path)
        configured_dialect = (dbt_settings.projects.get(meta.get("dbt_root"), {}).get("dialect", dbt_settings.dialect)
                              if kind == "dbt" else source_dialect(row, preferences))
        source = {"id": row["file_id"], "path": path, "kind": kind, "role": meta.get("dbt_role"),
                  "hash": expected or row["content_hash"], "encoding": row["encoding"], "size": row["file_size"],
                  "dialect": dialects.get(row["file_id"], analysis.get("dialects", {}).get(path, configured_dialect)
                                         if kind != "dbt" else configured_dialect),
                  "required": chosen}
        snapshot["sources"].append(source)
        # Inventory unselected programs too for producer checks. Seal them off from AI later.
        source["selected"] = chosen
        if SECRET_FILE.search(path):
            source["skip"] = "Sensitive profile or credential file excluded"
        elif builder_revision is not None and not chosen:
            source["skip"] = "Outside selected Builder scope"
        elif not chosen and kind not in {"sql", "sas", "dbt"}:
            source["skip"] = "Outside selected source scope"
        elif analysis_run and not expected and chosen:
            source["skip"] = "This source was absent from the committed analysis."
        elif row["file_size"] > 5 * engine.MAX_ARTIFACT or total + row["file_size"] > engine.MAX_PROJECT:
            source.update(skip="Source exceeds migration input limits", required=True)
        else:
            try:
                if expected and expected != row["content_hash"]:
                    data = store.original(row["file_id"], expected)
                    if len(data) > 5 * engine.MAX_ARTIFACT or engine.digest(data) != expected:
                        raise ValueError("Historical evidence exceeds limits or failed verification")
                    source["text"], source["encoding"], _ = decode(data)
                    source.update(size=len(data), freshness="historical")
                else:
                    source["text"] = store.snapshot_content(row)
                if len(source["text"].encode()) + total > engine.MAX_PROJECT:
                    source.pop("text")
                    source.update(skip="Decoded source exceeds migration input limits", required=True)
                else:
                    total += len(source["text"].encode())
            except (OSError, ValueError, UnicodeError):
                source["skip"] = "No verified original source is available"
        if chosen and row["parsing_status"] in {"pending", "partial", "failed"} and analysis_run:
            snapshot["analysis_gaps"].append(f"{path} had {row['parsing_status']} analysis at snapshot time.")
    for path in sorted(required.keys() - {row["relative_path"] for row in inventory}):
        snapshot["analysis_gaps"].append(f"Analyzed source is no longer retained: {path}")
    if analysis_run:
        for detail in store.diagnostics(workspace)[:100]:
            if detail["file_id"] in picked and detail["severity"] in {"warning", "error"}:
                snapshot["analysis_gaps"].append(f"Analysis diagnostic at line {detail['line']}: {detail['message']}")
    reports = store.rows("SELECT ingestion_id,report FROM ingestion_runs WHERE workspace_id=?", [workspace])
    active_imports = {row["ingestion_id"] for row in inventory if row["file_id"] in picked}
    snapshot["upload_report"] = [
        {"id": row["ingestion_id"], "report": _admission_report(row["report"])}
        for row in reports if row["ingestion_id"] in active_imports
    ]
    if builder_revision is not None:
        design = load_builder(store, workspace)
        if design.revision != builder_revision:
            raise ValueError("Builder changed. Open migration again from the current design.")
        visible = set([table.id for table in design.tables] if builder_tables is None else builder_tables)
        graph = defaultdict(set)
        for link in design.links:
            graph[link.target_table].add(link.source_table)
        queue = list(visible)
        while queue:
            for table_id in graph[queue.pop()] - visible:
                visible.add(table_id)
                queue.append(table_id)
        if visible - {t.id for t in design.tables}:
            raise ValueError("Some selected design tables no longer exist")
        snapshot["builder_revision"] = builder_revision
        snapshot["builder_links"] = [link.model_dump() for link in design.links
                                    if link.source_table in visible and link.target_table in visible]
        snapshot["builder_columns"] = {table.name: {c.name: c.data_type for c in table.columns}
                                       for table in design.tables if table.id in visible}
        for table in design.tables:
            if table.id in visible:
                text = json.dumps(table.model_dump(), ensure_ascii=False)
                snapshot["sources"].append({"id": f"builder-{table.id}", "kind": "builder", "role": table.role,
                                            "path": f"Design revision {builder_revision} / {table.name}", "text": text,
                                            "hash": engine.digest(text), "table": table.name, "selected": True})
    if not any(source.get("selected") for source in snapshot["sources"]):
        raise ValueError("Select retained sources or at least one design table")
    return snapshot


def _admission_report(value):
    report = json.loads(value or "{}")
    return {key: report.get(key) for key in ("discovered", "accepted", "skipped", "duplicates", "skip_reasons")}


def preview(snapshot):
    plan, files = engine.convert(snapshot)
    return plan, engine.validate(snapshot, plan, files)


def projects(store, workspace):
    return store.rows("""SELECT project_id AS id,name,revision_id AS revision FROM migration_projects
        WHERE workspace_id=? ORDER BY created_at DESC""", [workspace])


def _project(store, workspace, project_id):
    rows = store.rows("""SELECT project_id AS id,name,revision_id AS revision,snapshot FROM migration_projects
        WHERE workspace_id=? AND project_id=?""", [workspace, project_id])
    if not rows:
        raise ValueError("Migration project is unavailable in this workspace")
    project = rows[0]
    revoked = store.rows("""SELECT activity_id FROM migration_activity WHERE workspace_id=?
        AND kind='lesson' AND status='revoked'""", [workspace])
    return {**project, "snapshot": {**json.loads(project["snapshot"]),
                                   "revoked_rules": [row["activity_id"] for row in revoked]}}


def _stored_snapshot(store, workspace, project):
    snapshot = project["snapshot"]
    rows = store.rows("SELECT file_id,body FROM migration_sources WHERE workspace_id=? AND project_id=?",
                      [workspace, project["id"]])
    bodies = {row["file_id"]: row["body"] for row in rows}
    return {**snapshot, "sources": [{**source, "text": _verified_text(source, bodies[source["id"]])}
                if source["id"] in bodies else source for source in snapshot["sources"]]}


def _verified_text(source, body):
    decoded = zlib.decompress(body)
    if len(decoded) != source["decoded_bytes"] or engine.digest(decoded) != source["decoded_hash"]:
        raise ValueError("The embedded source snapshot failed its integrity check")
    return decoded.decode()


def evidence(store, workspace, project_id, region):
    project = _project(store, workspace, project_id)
    sources = {source["id"]: source for source in project["snapshot"]["sources"]}
    source = sources.get(region["source"])
    if source is None or source["hash"] != region["hash"]:
        raise ValueError("Pinned source evidence is unavailable")
    text = _source_text(store, workspace, project_id, source)
    if not 0 <= region["start"] <= region["end"] <= len(text):
        raise ValueError("Invalid source evidence range")
    return text[region["start"]:region["end"]]


def _source_text(store, workspace, project_id, source):
    rows = store.rows("SELECT body FROM migration_sources WHERE workspace_id=? AND project_id=? AND file_id=?",
                      [workspace, project_id, source["id"]])
    if not rows:
        raise ValueError("Pinned source evidence is unavailable")
    return _verified_text(source, rows[0]["body"])


def review_line_range(store, workspace, project_id, region, source):
    """Resolve line numbers for revisions that stored byte-independent character offsets only."""
    if region.get("start_line"):
        return region["start_line"], region["end_line"]
    text = _source_text(store, workspace, project_id, source)
    start, end = region["start"], region["end"]
    if source["hash"] != region["hash"] or not 0 <= start <= end <= len(text):
        raise ValueError("Invalid pinned source evidence")
    first = 1 + len(re.findall(r"\r\n|\r|\n", text[:start]))
    last = 1 + len(re.findall(r"\r\n|\r|\n", text[:max(start, end - 1)]))
    return first, last


def create_project(store, workspace, name, snapshot):
    """Store source evidence once so later workspace cleanup cannot orphan a migration."""
    target = warehouse(snapshot)
    name = name.strip()
    if not name or len(name) > 160:
        raise ValueError("Enter a project name of up to 160 characters")
    identity = uuid.uuid4().hex
    revision = uuid.uuid4().hex
    normalized = {**snapshot, "profile": target.profile}
    sizes = sum(len(source.get("text", "").encode()) for source in snapshot["sources"])
    if sizes > engine.MAX_PROJECT or len(snapshot["sources"]) > 10_100:
        raise ValueError("Source snapshot exceeds migration limits")
    normalized["sources"] = []
    bodies = {}
    for source in snapshot["sources"]:
        facts = {key: value for key, value in source.items() if key != "text"}
        if "text" in source and not SECRET_FILE.search(source["path"]):
            decoded = source["text"].encode()
            facts.update(decoded_hash=engine.digest(decoded), decoded_bytes=len(decoded))
            bodies[source["id"]] = zlib.compress(decoded, level=3)
        normalized["sources"].append(facts)
    with store.transaction():
        if not store.rows("SELECT 1 FROM workspaces WHERE workspace_id=?", [workspace]):
            raise ValueError("Workspace is unavailable")
        store.execute("INSERT INTO migration_projects(workspace_id, project_id, name, revision_id, snapshot) VALUES (?,?,?,?,?)",
                      [workspace, identity, name, revision, json.dumps(normalized)])
        if bodies:
            store.db.executemany("INSERT INTO migration_sources VALUES (?,?,?,?)",
                                 [(workspace, identity, key, body) for key, body in bodies.items()])
        _insert_revision(store, workspace, identity, {"id": revision, "parent": None, "settings": {},
                                                       "plan": None, "files": {}, "reviews": {}})
    return {"id": identity, "name": name, "revision": revision}


def _insert_revision(store, workspace, project_id, revision):
    store.execute("""INSERT INTO migration_revisions(workspace_id,project_id,revision_id,body) VALUES (?,?,?,?)""",
                  [workspace, project_id, revision["id"], _dump(revision)])


def load(store, workspace, project_id, revision_id=None):
    project = _project(store, workspace, project_id)
    rows = store.rows("""SELECT body FROM migration_revisions WHERE workspace_id=? AND project_id=? AND revision_id=?""",
                      [workspace, project_id, revision_id or project["revision"]])
    if not rows:
        raise ValueError("Migration revision is unavailable")
    return project, _read(rows[0]["body"])


def history(store, workspace, project_id):
    _project(store, workspace, project_id)
    return store.rows("""SELECT revision_id AS id,created_at FROM migration_revisions
        WHERE workspace_id=? AND project_id=? ORDER BY created_at DESC""", [workspace, project_id])


def _publish(store, workspace, project_id, base, revision):
    if _project(store, workspace, project_id)["revision"] != base:
        raise ValueError("Migration changed. Refresh the revision and review the edit again.")
    _insert_revision(store, workspace, project_id, revision)
    store.execute("UPDATE migration_projects SET revision_id=? WHERE workspace_id=? AND project_id=?",
                  [revision["id"], workspace, project_id])


def convert(store, workspace, project_id, expected_revision, cancelled=lambda: False, progress=None):
    project, base = load(store, workspace, project_id, expected_revision)
    if project["revision"] != expected_revision:
        raise ValueError("Migration changed. Refresh before conversion.")
    if base["plan"]:
        return base
    snapshot = _stored_snapshot(store, workspace, project)
    if cancelled():
        raise InterruptedError()
    prefix = f"{base['id']}.{engine.VERSION}."
    cached = store.rows("""SELECT body FROM migration_activity WHERE workspace_id=? AND project_id=?
                          AND kind='checkpoint' AND starts_with(activity_id, ?)""", [workspace, project_id, prefix])
    resumed = {model: value for row in cached for model, value in _read(row["body"]).items()}

    def checkpoint(units):
        activity_id = prefix + engine.fingerprint(sorted(units))
        with store.transaction():
            if _project(store, workspace, project_id)["revision"] != base["id"]:
                raise ValueError("Migration changed. Refresh before conversion.")
            store.execute("""INSERT INTO migration_activity(workspace_id,project_id,activity_id,kind,status,body)
                VALUES (?,?,?,'checkpoint','saved',?) ON CONFLICT DO NOTHING""",
                [workspace, project_id, activity_id, _dump(units)])

    if resumed and progress:
        progress(.25, f"Resuming {len(resumed):,} saved model conversions")
    plan, files = engine.convert(snapshot, cancelled, progress, resumed=resumed, checkpoint=checkpoint)
    if progress:
        progress(.85, "Saving planned outputs and immutable source mappings")
    revision = {"id": uuid.uuid4().hex, "parent": base["id"], "settings": {}, "plan": plan,
                "files": files, "reviews": {}}
    with store.transaction():
        if cancelled():
            raise InterruptedError()
        _publish(store, workspace, project_id, base["id"], revision)
        store.execute("DELETE FROM migration_activity WHERE workspace_id=? AND project_id=? AND kind='checkpoint'",
                      [workspace, project_id])
    return revision


def report(project, revision):
    if revision["plan"] is None:
        raise ValueError("Run conversion first")
    snapshot = {**project["snapshot"], **revision["settings"]}
    details = engine.validate(snapshot, revision["plan"], revision["files"], revision["reviews"])
    coverage = Counter()
    spans = Counter()
    byte_spans = Counter()
    for row in revision["plan"]["regions"]:
        status = row["disposition"]
        if status in {"candidate", "manual_required"}:
            status = ("converted" if row["outputs"] and all(model in details["active"] for model in row["outputs"])
                      else "unresolved")
        coverage[status] += 1
        spans[status] += row["end"] - row["start"]
        byte_spans[status] += row.get("utf8_bytes", row["end"] - row["start"])
    details.update(coverage=dict(coverage), characters=dict(spans), utf8_bytes=dict(byte_spans))
    return details


def resolve_scope(store, workspace, project_id, expected_revision, region_id, reason, external=None):
    """Exclude an obligation explicitly. Models that consumed its output stay blocked."""
    if not 1 <= len(reason.strip()) <= 2000:
        raise ValueError("Record the scope exclusion and the retained processing prerequisite")
    with store.transaction():
        _, base = load(store, workspace, project_id, expected_revision)
        if base["plan"] is None:
            raise ValueError("Convert the source scope first")
        plan = base["plan"]
        selected = next((row for row in plan["regions"] if row["id"] == region_id), None)
        if not selected or not selected["gap"] or selected["disposition"] == "excluded":
            raise ValueError("Choose an included unresolved source region")
        plan["regions"] = [{**row, "disposition": "excluded", "exclusion": current_connections().redact(reason)}
                           if row["id"] == region_id else row for row in plan["regions"]]
        plan["barriers"] = [item for item in plan["barriers"] if item != region_id]
        if external is not None:
            if (len(selected["outputs"]) != 1 or not isinstance(external, dict)
                    or set(external) != {"catalog", "schema", "identifier", "owner", "columns"}):
                raise ValueError("Externally supplying an output requires one relation, an owner and a column contract")
            parts = [external[field] for field in ("catalog", "schema", "identifier")]
            target = warehouse(_project(store, workspace, project_id)["snapshot"])
            if (any(not isinstance(part, str) or not engine.NAME.fullmatch(part) for part in parts)
                    or not isinstance(external["owner"], str) or not 1 <= len(external["owner"].strip()) <= 160
                    or not isinstance(external["columns"], dict) or not external["columns"]
                    or any(not target.map_type(value) for value in external["columns"].values())):
                raise ValueError("Provide literal source identifiers, confirmed column types and a responsible owner")
            model = selected["outputs"][0]
            source_key, _ = engine._physical_input(parts, ".".join(parts), plan["physical"])
            plan["physical"][source_key].update(
                externally_supplied=model, owner=current_connections().redact(external["owner"]),
                prerequisite=current_connections().redact(reason))
            plan["columns"][source_key] = external["columns"]
            for output in plan["outputs"].values():
                output["inputs"] = [source_key if value == model else value for value in output["inputs"]]
        for model in selected["outputs"]:
            plan["outputs"][model]["excluded"] = True
        revision = {**base, "id": uuid.uuid4().hex, "parent": base["id"]}
        _publish(store, workspace, project_id, base["id"], revision)
    return revision


def set_contract(store, workspace, project_id, expected_revision, model, inputs, behavior, prerequisites):
    """Record authored input/ordering evidence before manually implementing an unresolved output."""
    if not all(isinstance(value, str) and 1 <= len(value.strip()) <= 2000 for value in (behavior, prerequisites)):
        raise ValueError("Describe the output behavior and its source/order prerequisites")
    with store.transaction():
        _, base = load(store, workspace, project_id, expected_revision)
        plan = base["plan"]
        output = plan and plan["outputs"].get(model)
        if not output or not output.get("manual") or output.get("excluded"):
            raise ValueError("Choose an unresolved output without a deterministic lowering")
        allowed = {key for key, row in plan["outputs"].items() if key != model and not row.get("excluded")}
        if set(inputs) - (allowed | plan["physical"].keys()) or set(output["inputs"]) - set(inputs):
            raise ValueError("Keep every known dependency and select available inputs")
        output["inputs"] = sorted(set(inputs))
        output["contract"] = current_connections().sanitize({"behavior": behavior, "prerequisites": prerequisites})
        revision = {**base, "id": uuid.uuid4().hex, "parent": base["id"]}
        _publish(store, workspace, project_id, base["id"], revision)
    return revision


def propose(base, replacements, rationale, *, origin="manual", scopes=None, rules=None):
    """Construct a patch with hashes already bound to the disclosed base and output allowlist."""
    if base["plan"] is None or not replacements or len(replacements) > 50:
        raise ValueError("Choose one to fifty planned outputs")
    if origin not in {"manual", "ai", "optimization"} or not 1 <= len(rationale.strip()) <= 4_000:
        raise ValueError("Provide a bounded rationale for the proposed edits")
    allowed = set(scopes) if scopes is not None else set(base["plan"]["outputs"])
    if set(replacements) - allowed:
        raise ValueError("Proposal includes an output outside the disclosed scope")
    edits = {}
    for model, sql in replacements.items():
        output = base["plan"]["outputs"].get(model)
        if not output or output.get("excluded") or not engine.NAME.fullmatch(model):
            raise ValueError("Edits must address an included, mapped output")
        if not isinstance(sql, str) or not sql.strip() or len(sql.encode()) > engine.MAX_ARTIFACT:
            raise ValueError("Each proposed model needs bounded SQL text")
        old = base["files"].get(model)
        if old and old["sql"] == sql:
            continue
        edits[model] = {"before": old["hash"] if old else None, "sql": sql}
    if not edits:
        raise ValueError("The proposal contains no code changes")
    return {"id": uuid.uuid4().hex, "base": base["id"], "edits": edits, "origin": origin,
            "rationale": current_connections().redact(rationale), "rules": rules or []}


def diffs(base, proposal):
    for model, edit in proposal["edits"].items():
        old = base["files"].get(model, {}).get("sql", "")
        yield model, "".join(unified_diff(old.splitlines(keepends=True), edit["sql"].splitlines(keepends=True),
                            fromfile=f"before/{model}.sql", tofile=f"after/{model}.sql"))


def candidate(base, proposal):
    if proposal["base"] != base["id"]:
        raise ValueError("Proposal is stale. Review it against the current migration revision.")
    replacements = {model: row["sql"] for model, row in proposal["edits"].items()}
    checked = propose(base, replacements, proposal["rationale"], origin=proposal["origin"], rules=proposal["rules"])
    if checked["edits"] != proposal["edits"]:
        raise ValueError("One or more file hashes changed. The whole edit was rejected.")
    files = dict(base["files"])
    for model, row in checked["edits"].items():
        files[model] = {"sql": row["sql"], "hash": engine.digest(row["sql"]),
                        "origin": proposal["origin"], "rules": proposal["rules"]}
    return {**base, "files": files}


def apply(store, workspace, project_id, proposal):
    with store.transaction():
        project, base = load(store, workspace, project_id)
        revision = candidate(base, proposal)
        details = report(project, revision)
        mechanical = {"unsafe_sql", "broken_ref", "broken_source", "unmapped_table",
                      "changed_dependencies", "artifact_integrity", "cycle", "missing_column", "set_layout",
                      "target_collision"}
        previous = {(row["model"], row["code"], row["message"]) for row in report(project, base)["findings"]}
        if any(row["code"] in mechanical and (row["model"] in proposal["edits"]
               or (row["model"], row["code"], row["message"]) not in previous) for row in details["findings"]):
            raise ValueError("The proposal has unresolved SQL or dependency checks. Correct it before applying.")
        revision.update(id=uuid.uuid4().hex, parent=base["id"], proposal=proposal["id"])
        _publish(store, workspace, project_id, base["id"], revision)
    return revision


def revise_schemas(store, workspace, project_id, expected_revision, settings):
    with store.transaction():
        project, base = load(store, workspace, project_id, expected_revision)
        if base["plan"] is None or set(settings) - {"types", "source_mappings", "input_types"}:
            raise ValueError("Invalid schema revision")
        if any(not isinstance(rows, dict) for rows in settings.values()) or any(
            not isinstance(table, dict) or key not in base["plan"]["physical"]
            for key, table in settings.get("input_types", {}).items()
        ):
            raise ValueError("Confirm types on a mapped input or output relation")
        target = warehouse(project["snapshot"])
        for value in (*settings.get("types", {}).values(),
                      *(value for table in settings.get("input_types", {}).values() for value in table.values())):
            if not target.map_type(value):
                raise ValueError("Use a supported Databricks type")
        for key, row in settings.get("source_mappings", {}).items():
            if key not in base["plan"]["physical"] or set(row) != {"catalog", "schema", "identifier"} or any(
                not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][\w]{0,127}", value) for value in row.values()
            ):
                raise ValueError("Map a known input to a literal catalog, schema and table")
        plan = {**base["plan"], "physical": {key: dict(row) for key, row in base["plan"]["physical"].items()}}
        for key, row in settings.get("source_mappings", {}).items():
            plan["physical"][key].update(row, assumed_location=False)
        revision = {**base, "id": uuid.uuid4().hex, "parent": base["id"], "plan": plan,
                    "settings": {**base["settings"], **settings}}
        _publish(store, workspace, project_id, base["id"], revision)
    return revision


def record_review(store, workspace, project_id, expected_revision, model, reviewer, rationale, obligations):
    if not reviewer.strip() or not rationale.strip() or len(reviewer) > 160 or len(rationale) > 4000:
        raise ValueError("Record the reviewer and the intended behavior or accepted uncertainty")
    with store.transaction():
        project, base = load(store, workspace, project_id, expected_revision)
        details = report(project, base)
        required = [row["id"] for row in details["findings"] if row["model"] == model and not row["inherited_from"]]
        if (details["tiers"].get(model) not in {"needs_investigation", "static_checks_satisfied"}
                or sorted(obligations) != sorted(required)):
            raise ValueError("Review every current obligation and resolve structural blockers first")
        reviews = {**base["reviews"], model: {"key": details["review_keys"][model], "obligations": required,
                   "reviewer": current_connections().redact(reviewer), "rationale": current_connections().redact(rationale)}}
        revision = {**base, "id": uuid.uuid4().hex, "parent": base["id"], "reviews": reviews}
        _publish(store, workspace, project_id, base["id"], revision)
    return revision


def restore_revision(store, workspace, project_id, expected_revision, revision_id):
    with store.transaction():
        _, prior = load(store, workspace, project_id, revision_id)
        if prior["plan"] is None:
            raise ValueError("Choose a converted revision")
        revision = {**prior, "id": uuid.uuid4().hex, "parent": expected_revision, "restored": revision_id}
        _publish(store, workspace, project_id, expected_revision, revision)
    return revision


def bundle(store, workspace, project_id, revision_id, reviewed=False, *, image_format=None, workbook=False):
    from dataforge.migration.exports import build_bundle

    project, revision = load(store, workspace, project_id, revision_id)
    sources = {source["id"]: source for source in project["snapshot"]["sources"]}

    @lru_cache(maxsize=4)
    def original(file_id):
        return _source_text(store, workspace, project_id, sources[file_id])

    def read(region):
        text = original(region["source"])
        if sources[region["source"]]["hash"] != region["hash"] or not 0 <= region["start"] <= region["end"] <= len(text):
            raise ValueError("Invalid pinned source evidence")
        return text[region["start"]:region["end"]]

    return build_bundle(project, revision, report(project, revision), reviewed,
                        image_format=image_format, workbook=workbook, read_evidence=read)


def review_comments(store, workspace, project_id):
    _project(store, workspace, project_id)
    return [{**_read(row["body"]), "id": row["activity_id"], "status": row["status"],
             "created_at": str(row["created_at"])} for row in store.rows("""
        SELECT activity_id,status,body,created_at FROM migration_activity
        WHERE workspace_id=? AND project_id=? AND kind='comment'
        ORDER BY created_at DESC,activity_id DESC""", [workspace, project_id])]


def add_review_comment(store, workspace, project_id, revision_id, artifact, anchor, line, author, message):
    from dataforge.migration.inspection import artifacts

    if not 1 <= len(author.strip()) <= 160 or not 1 <= len(message.strip()) <= 2000:
        raise ValueError("Enter an author and an engineer comment")
    with store.transaction():
        project, revision = load(store, workspace, project_id, revision_id)
        if project["revision"] != revision_id or revision["plan"] is None:
            raise ValueError("The migration changed. Confirm the line on the current revision.")
        entry = artifacts(project, revision).get(artifact)
        if entry is None:
            raise ValueError("Choose an artifact in this migration")
        region = entry["region"]
        file = entry["file"]
        if anchor == "source" and region["end"] > region["start"]:
            first, last = review_line_range(store, workspace, project_id, region, entry["source"])
        elif anchor == "generated" and file:
            first, last = 1, len(file["sql"].splitlines())
        elif anchor == "section" and line is None:
            first = last = None
        else:
            raise ValueError("Line anchor is unavailable for this artifact")
        if first is not None and (type(line) is not int or not first <= line <= last):
            raise ValueError("Comment line lies outside the pinned evidence")
        redact = current_connections().redact
        payload = {"revision": revision_id, "artifact": artifact, "anchor": anchor, "line": line,
                   "author": redact(author.strip()), "message": redact(message.strip()),
                   "hash": file["hash"] if anchor == "generated" else region["hash"]}
        if store.rows("""SELECT count(*) AS total FROM migration_activity
            WHERE workspace_id=? AND project_id=? AND kind='comment'""", [workspace, project_id])[0]["total"] >= 1000:
            raise ValueError("This migration has reached its review comment limit")
        store.execute("""INSERT INTO migration_activity(workspace_id,project_id,activity_id,kind,status,body)
            VALUES (?,?,?,'comment','open',?)""", [workspace, project_id, uuid.uuid4().hex, _dump(payload)])


def resolve_review_comment(store, workspace, project_id, comment_id):
    with store.transaction():
        _project(store, workspace, project_id)
        store.execute("""UPDATE migration_activity SET status='resolved'
            WHERE workspace_id=? AND project_id=? AND activity_id=? AND kind='comment'""",
            [workspace, project_id, comment_id])
