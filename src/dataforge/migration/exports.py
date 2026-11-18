"""A revision-pinned dbt handoff with offline evidence and quarantined drafts."""
import io
import json
import zipfile
from collections import defaultdict

import xlsxwriter
import yaml

from dataforge.connections import current_connections
from dataforge.exports import graph_html, report_csv
from dataforge.graph import LineageGraph
from dataforge.graph_images import render_graph_image
from dataforge.ingestion import safe_relative
from dataforge.migration.engine import MAX_PROJECT, digest, slug
from dataforge.migration.inspection import annotated, artifacts, commented_source, source_path
from dataforge.migration.targets import DBT_CORE_VERSION, warehouse


def lineage_graph(details):
    edges = details["lineage"]["edges"]
    ids = set(details["lineage"]["nodes"]) | {edge["source"] for edge in edges}
    nodes = [{"asset_id": key, "name": key, "canonical_name": key,
              "kind": "table", "temporary": False, "metadata": "{}"} for key in sorted(ids)]
    graph = LineageGraph(nodes, [
        {"source_id": edge["source"], "target_id": edge["target"], "kind": "select",
         "status": "observed", "method": "static", "start_line": edge.get("line", 1),
         "content_hash": edge["model_hash"], "file": edge["target"] + ".sql"} for edge in edges
    ])
    if len(graph.nodes) > 200:
        graph = LineageGraph._from_graph(graph.graph.subgraph(sorted(graph.nodes)[:200]).copy(), truncated=True)
    return graph


def _yaml(value):
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _literal(value):
    # dbt can interpret Jinja in documentation and configuration as well as SQL.
    return str(value).replace("{", "〔").replace("}", "〕")


def _mapping_workbook(mappings, assumptions):
    if len(mappings) + len(assumptions) > 50_000:
        raise ValueError("The workbook exceeds 50,000 rows. Export the CSV reports for the full scope.")
    output = io.BytesIO()
    with xlsxwriter.Workbook(output, {"in_memory": True, "strings_to_urls": False,
                                     "strings_to_formulas": False}) as workbook:
        for label, rows in (("Model mapping", mappings), ("Type provenance", assumptions)):
            sheet = workbook.add_worksheet(label)
            sheet.freeze_panes(1, 0)
            if rows:
                sheet.write_row(0, 0, list(rows[0]))
                for index, row in enumerate(rows, 1):
                    if sheet.write_row(index, 0, list(row.values())):
                        raise ValueError("A report value exceeds the workbook cell limit")
    return output.getvalue()


def build_bundle(project, revision, details, reviewed, image_format=None, workbook=False, *, read_evidence=None):
    if reviewed and not details["eligible"]:
        raise ValueError("Resolve all required outputs, structural findings and outstanding reviews first")
    target = warehouse(project["snapshot"])
    plan = revision["plan"]
    project_name = plan.get("project") or slug(project["name"])
    name = "Reviewed handoff" if reviewed else "Draft bundle"
    content = {}
    used_paths = set()
    total = 0

    def write(path, value):
        nonlocal total
        path = safe_relative(path)
        if path.casefold() in used_paths:
            raise ValueError("Output path collision")
        data = value.encode("utf-8") if isinstance(value, str) else value
        total += len(data)
        if total > MAX_PROJECT:
            raise ValueError("Archive exceeds the expanded export size limit")
        used_paths.add(path.casefold())
        content[path] = data

    write("dbt_project.yml", _yaml({
        "name": project_name, "version": "1.0.0", "config-version": 2, "profile": project_name,
        "require-dbt-version": "==" + DBT_CORE_VERSION, "model-paths": ["models"],
    }))
    write("profiles.yml.example", _yaml({
        project_name: {"target": "migration", "outputs": {"migration": {
            "type": target.dialect, "catalog": project["snapshot"]["catalog"],
            "schema": project["snapshot"]["schema"], "threads": 4,
            "host": "{{ env_var('DATABRICKS_HOST') }}",
            "http_path": "{{ env_var('DATABRICKS_HTTP_PATH') }}",
            "token": "{{ env_var('DATABRICKS_TOKEN') }}",
        }}},
    }))
    write("requirements.txt", f"dbt-core=={DBT_CORE_VERSION}\ndbt-databricks=={target.adapter_version}\n")
    regions = {row["id"]: row for row in plan["regions"]}
    sources = {row["id"]: row for row in project["snapshot"]["sources"]}
    models, mappings, assumptions = [], [], []
    physical = defaultdict(list)
    redact = current_connections().redact
    inventory = artifacts(project, revision, details)

    def write_evidence(entry, prefix=""):
        region = entry["region"]
        evidence_path = source_path(region)
        if evidence_path in content:
            return
        original = read_evidence(region) if read_evidence and region["end"] > region["start"] else ""
        write(evidence_path, prefix + commented_source(entry, original, redact=redact))
    for key, item in plan["physical"].items():
        if any(str(item[field]) != _literal(item[field]) for field in ("group", "name", "identifier", "catalog", "schema")):
            raise ValueError("Source mapping contains a template marker")
        columns = []
        for column, fact in details["source_schemas"].get(key, {}).items():
            columns.append({"name": _literal(column), "data_type": fact["target_type"],
                            "meta": {"migration_type_provenance": fact["provenance"]}})
            assumptions.append({"model": key, "column": column, **fact, "ordinal": ""})
        physical[(item["group"], item["catalog"], item["schema"])].append({
            "name": item["name"], "identifier": item["identifier"], "columns": columns,
        })
    # dbt requires a unique source name across schemas.
    source_rows = []
    for (group, catalog, schema), tables in physical.items():
        source_rows.append({"name": group, "database": catalog, "schema": schema, "tables": tables,
                            "quoting": {"database": True, "schema": True, "identifier": True}})
    write("models/sources.yml", _yaml({"version": 2, "sources": source_rows}))
    for model, output in plan["outputs"].items():
        region = regions[output["region"]]
        source = sources[region["source"]]
        file = revision["files"].get(model)
        active = model in details["active"]
        status = inventory[model]["status"] if model in inventory else "excluded"
        path = ""
        annotation_path = ""
        if entry := inventory.get(model):
            if file and digest(file["sql"]) != file["hash"]:
                raise ValueError("Generated artifact failed its integrity check")
            path = entry["path"]
            if active:
                content_sql = file["sql"]
                if redact(content_sql) != content_sql:
                    raise ValueError("A model contains credential-like text. Review the model before exporting.")
                write(path, content_sql)
                models.append({"name": model, "description": _literal(redact(plan["docs"].get(output["name"], ""))),
                               "config": details["model_config"][model],
                               "columns": [{"name": _literal(column), "data_type": fact["target_type"],
                                            "meta": {"migration_type_provenance": fact["provenance"]}}
                                           for column, fact in details["schemas"].get(model, {}).items()]})
                if status == "engineer_accepted" and entry["findings"]:
                    annotation_path = f"review/{model}.sql.txt"
                    write(annotation_path, annotated(entry, redact=redact, include_source_path=not reviewed)[0])
                    if not reviewed:
                        write_evidence(entry)
            else:
                write(path, annotated(entry, redact=redact)[0])
                annotation_path = path
                write_evidence(entry)
        for column, fact in details["schemas"].get(model, {}).items():
            assumptions.append({"model": model, "column": column, **fact})
        mappings.append({"model": model, "original_relation": output["name"], "source": source["path"],
                         "source_hash": region["hash"], "start": region["start"], "end": region["end"],
                         "region": region["id"], "source_start_line": region.get("start_line"),
                         "source_end_line": region.get("end_line"),
                         "artifact": path, "annotation_artifact": annotation_path,
                         "artifact_hash": digest(content[path]) if path else None,
                         "revision_artifact_hash": file and file["hash"], "status": status})
    for entry in inventory.values():
        if entry["model"] is not None:
            continue
        region = entry["region"]
        prefix = annotated(entry, redact=redact)[0]
        if entry["path"] in content:
            raise ValueError("Review evidence path collision")
        write_evidence(entry, prefix)
        mappings.append({"model": "", "original_relation": "", "source": entry["source"]["path"],
                         "source_hash": region["hash"], "start": region["start"], "end": region["end"],
                         "region": region["id"], "source_start_line": region.get("start_line"),
                         "source_end_line": region.get("end_line"),
                         "artifact": entry["path"], "annotation_artifact": entry["path"],
                         "artifact_hash": digest(content[entry["path"]]),
                         "revision_artifact_hash": None, "status": entry["status"]})
    write("models/schema.yml", _yaml({"version": 2, "models": models}))
    checklist = (
        "Validate the generated project and dependency installation in your controlled environment. "
        "Compare output counts, keys, duplicates, nulls, aggregates, precision and row grain with the legacy system. "
        "Confirm source availability, grants, orchestration, SLAs, rollback and cutover ownership."
    )
    write("README.md", f"# {name}\n\nRuntime equivalence is unverified.\n\n"
          "See migration/handoff.md for the output, evidence and validation checklist. "
          "Draft candidates remain under review/ until their checks and reviews are resolved.\n")
    write("migration/handoff.md", f"# {name}\n\nRevision `{revision['id']}`\n\n"
          "Use the pinned dependencies and the credential-free profile template. "
          "Review source mappings and operational prerequisites before running anything externally.\n\n"
          f"## External validation\n\n{checklist}\n\n"
          "Propose data tests after confirming business requirements. Generated tests have no execution evidence.\n")
    write("migration/source-map.json", _json(mappings))
    write("migration/coverage.json", _json({"regions": plan["regions"], "counts": details["coverage"],
                                           "characters": details["characters"], "utf8_bytes": details["utf8_bytes"],
                                           "admission": project["snapshot"].get("upload_report", []),
                                           "inventory": list(sources.values())}))
    write("migration/findings.json", _json(details["findings"]))
    write("migration/validation.json", _json({k: details[k] for k in ("checks", "tiers", "active", "runtime_equivalence")}))
    write("migration/conversion-contracts.json", _json({key: value["contract"] for key, value in plan["outputs"].items()
                                                       if value.get("contract")}))
    write("migration/reviews.json", _json({model: review for model, review in revision["reviews"].items()
                                         if review["key"] == details["review_keys"].get(model)}))
    write("migration/lineage.json", _json({**details["lineage"], "revision": revision["id"],
                                         "original_edges": project["snapshot"].get("original_edges", [])}))
    write("migration/assumptions.csv", report_csv(assumptions))
    write("migration/model-mapping.csv", report_csv(mappings))
    if workbook:
        write("migration/mappings.xlsx", _mapping_workbook(mappings, assumptions))
    write("migration/test-proposals.json", _json([
        {"model": model, "provenance": "static_projection", "status": "not_evaluated",
         "proposal": "Inspect the output column names and order after external compilation.",
         "columns": list(details["schemas"][model])}
        for model in details["active"] if details["schemas"].get(model)
    ]))
    graph = lineage_graph(details)
    write("migration/lineage.html", graph_html(graph))
    if image_format:
        image, _ = render_graph_image(graph, format=image_format, options={"title": "Migrated lineage"})
        write(f"migration/lineage.{image_format}", image)
    write("review/manual-work.json", _json([row for row in plan["regions"] if row["gap"]]))
    write("migration/manifest.json", _json({
        "project": project["id"], "revision": revision["id"], "mode": "reviewed" if reviewed else "draft",
        "profile": target.profile, "runtime_equivalence": "not_evaluated", "converter_version": plan["version"],
        "analysis_run": project["snapshot"].get("analysis_run"), "scope": project["snapshot"].get("selected_outputs", []),
        "source_prerequisites": plan["physical"], "builder_revision": project["snapshot"].get("builder_revision"),
        "builder_links": project["snapshot"].get("builder_links", []),
        "files": {path: {"sha256": digest(data), "bytes": len(data)} for path, data in content.items()},
    }))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, data in sorted(content.items()):
            archive.writestr(zipfile.ZipInfo(path, (1980, 1, 1, 0, 0, 0)), data, compress_type=zipfile.ZIP_DEFLATED)
    return output.getvalue()
