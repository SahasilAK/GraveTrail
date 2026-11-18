"""Migration setup, engineering review and handoff."""
import json

import streamlit as st

from dataforge.agent.contracts import AgentError
from dataforge.agent.jobs import TERMINAL
from dataforge.configuration import VisualizationSettings
from dataforge.exports import report_csv
from dataforge.lineage_builder import load_builder
from dataforge.migration import assistance, engine, service, validation
from dataforge.migration.exports import lineage_graph
from dataforge.migration.inspection import annotated, artifacts, source_location
from dataforge.migration.targets import FORMATS, WAREHOUSES
from dataforge.schema_imports import import_schema
from ui.analysis_ai import analysis_jobs
from ui.common import context, graph_view, title
from ui.presentation import section


def setup(store, workspace, prefix, entry):
    files = store.files(workspace)
    paths = {row["file_id"]: row["relative_path"] for row in files}
    default_ids = [key for key, path in paths.items() if path.lower().endswith((".sql", ".sas", "dbt_project.yml"))]
    from_builder = "builder_revision" in entry
    if entry.get("analysis_run"):
        st.caption("Pinned analysis " + entry["analysis_run"])
    if entry.get("selected_outputs"):
        st.text("Selected assets: " + ", ".join(entry["selected_outputs"]))
    if from_builder:
        st.info("Builder design scaffold. Supply transformation expressions, join semantics and row grain during review.")
    if not files:
        st.page_link("ui/pages/builder.py", label="Import sources", icon=":material/upload:")
    with st.form(prefix + "setup"):
        name = st.text_input("Project name", max_chars=160, value=entry.get("name", ""))
        left, center, right = st.columns(3)
        format_id = left.selectbox("Format", list(FORMATS), format_func=FORMATS.get)
        warehouse_id = center.selectbox("Warehouse", list(WAREHOUSES), format_func=lambda key: WAREHOUSES[key].label)
        profiles = {key: val.profile for key, val in WAREHOUSES.items()}
        profile = right.selectbox("Compatibility profile", [profiles[warehouse_id]])
        left, center, right = st.columns(3)
        catalog = left.text_input("Target catalog", "main", max_chars=128)
        schema = center.text_input("Target schema", "migration", max_chars=128)
        materialization = right.selectbox("New model materialization", ["table", "view"])
        picked = st.multiselect("Retained sources", list(paths), format_func=paths.get,
                                default=[] if from_builder else default_ids)
        dialect = st.selectbox("SQL source dialect override",
                              [None, "", "databricks", "tsql", "postgres", "snowflake", "bigquery", "oracle", "spark"],
                              format_func=lambda key: "Use source settings" if key is None else key or "Generic SQL")
        design = load_builder(store, workspace) if from_builder else None
        tables = []
        if design:
            by_id = {table.id: table.name for table in design.tables}
            defaults = [key for key in (entry.get("builder_tables") or by_id) if key in by_id]
            tables = st.multiselect("Design tables", list(by_id), default=defaults, format_func=by_id.get)
        submit = st.form_submit_button("Preview migration")
        create = st.form_submit_button("Create migration", type="primary",
                                       disabled=prefix + "preflight" not in st.session_state)
    if submit or create:
        try:
            settings = {"format": format_id, "warehouse": warehouse_id, "profile": profile,
                        "catalog": catalog, "schema": schema, "materialization": materialization}
            snapshot = service.freeze(
                store, workspace, selection=picked, analysis_run=entry.get("analysis_run"),
                selected_outputs=entry.get("selected_outputs"), builder_revision=entry.get("builder_revision"),
                builder_tables=tables, dialects=({key: dialect for key in picked} if dialect is not None else {}), **settings,
            )
            pin = engine.fingerprint([name, snapshot])
            if create and (previous := st.session_state.get(prefix + "preflight")) and previous["pin"] == pin:
                project = service.create_project(store, workspace, name, snapshot)
                st.session_state[prefix + "open"] = project["id"]
                st.session_state.pop(prefix + "preflight", None)
                st.session_state.pop(prefix + "entry", None)
                st.rerun()
            plan, details = service.preview(snapshot)
            st.session_state[prefix + "preflight"] = {
                "pin": pin, "outputs": [{"model": key, "output": row["name"], "inputs": ", ".join(row["inputs"]),
                                        "excluded": bool(row.get("excluded"))} for key, row in plan["outputs"].items()],
                "sources": [{"source": row["path"], "SHA-256": row["hash"],
                             "admission": row.get("skip", row.get("freshness", "Retained"))}
                            for row in snapshot["sources"]],
                "findings": details["findings"], "admission": snapshot.get("upload_report", []),
            }
            if create:
                st.warning("Scope or settings changed. Review the updated preflight before creating the project.")
            else:
                st.rerun()
        except (ValueError, OSError) as exc:
            st.error(str(exc))
    if previous := st.session_state.get(prefix + "preflight"):
        st.subheader("Preflight")
        for finding in previous["findings"]:
            if finding["code"] == "ambiguous_work_selection":
                st.warning(finding["message"])
        st.caption(f"{len(previous['sources']):,} inventory files · {len(previous['outputs']):,} planned outputs · "
                   f"{len(previous['findings']):,} findings")
        table_page("Planned outputs and upstream dependencies", previous["outputs"], prefix + "preview_out")
        with st.expander("Admission and source freshness"):
            table_page("Retained source inventory", previous["sources"], prefix + "preview_src")
            if previous["admission"]:
                st.json(previous["admission"], expanded=False)
        with st.expander("Preflight findings"):
            table_page("Findings", previous["findings"], prefix + "preview_find")


def table_page(label, rows, key):
    st.caption(label)
    if not rows:
        st.info("No records")
        return
    pages = (len(rows) - 1) // 100 + 1
    page = int(st.number_input("Page", 1, pages, key=key)) if pages > 1 else 1
    st.dataframe(rows[(page - 1) * 100:page * 100], hide_index=True, alt=label)


def job_status(store, workspace, project_id):
    job_id = assistance.latest_job(store, workspace, project_id)
    if not job_id:
        return
    jobs = analysis_jobs(str(store.home))
    try:
        job = jobs.read(job_id, workspace)
    except AgentError:
        st.warning("The previous job journal is unavailable. Retry explicitly from the saved revision.")
        return
    if job["status"] not in TERMINAL:
        @st.fragment(run_every=2)
        def progress():
            current = jobs.read(job_id, workspace)
            if current["status"] in TERMINAL:
                st.rerun()
            st.progress(current.get("progress", 0.0), text=current.get("stage") or "Queued")
            if st.button("Cancel conversion", disabled=current["cancel_requested"]):
                jobs.cancel(job_id, workspace)
        progress()
        st.stop()
    if job["status"] != "completed":
        st.warning(f"Last job {job['status']}. Saved outputs and request reservations are available for retry.")
    if error := (job.get("result") or {}).get("error"):
        st.error(error)


def patch_panel(store, workspace, project, base, proposal):
    st.text(proposal["rationale"])
    if proposal["base"] != base["id"]:
        st.caption("This proposal belongs to an earlier revision.")
        return
    candidate = service.candidate(base, proposal)
    before = service.report(project, base)
    after = service.report(project, candidate)
    invalidated = [model for model, key in before["review_keys"].items()
                   if key != after["review_keys"].get(model) and model in base["reviews"]]
    for model, diff in service.diffs(base, proposal):
        st.caption(model + ".sql")
        st.code(diff[:100_000], language="diff")
        if len(diff) > 100_000:
            st.download_button("Download full diff", diff, file_name=f"{model}.diff", on_click="ignore",
                               key=proposal["id"] + model)
    if invalidated:
        st.text("Reviews to renew: " + ", ".join(invalidated))
    if after["lineage"] != before["lineage"]:
        st.caption("Dependency evidence will be rebuilt for the edited models.")
        if after["lineage"]["missing"] or after["lineage"]["extra"]:
            st.json({key: after["lineage"][key] for key in ("missing", "extra")})
    findings = [row for row in after["findings"] if row["model"] in proposal["edits"]]
    if findings:
        table_page("Proposed revision findings", findings, proposal["id"] + "findings")
    if st.button("Apply reviewed diff", key=proposal["id"], type="primary"):
        service.apply(store, workspace, project["id"], proposal)
        st.rerun()


def numbered_excerpt(text, first, offset=0):
    lines = text.splitlines()[offset:offset + 100]
    return "\n".join(f"{number:>5} | {line}" for number, line in enumerate(lines, first + offset))[:20_000]


def artifact_inspector(store, workspace, project, base, entry, comments, key):
    region, file = entry["region"], entry["file"]
    if not region.get("start_line") and region["end"] > region["start"]:
        first, last = service.review_line_range(store, workspace, project["id"], region, entry["source"])
        region = {**region, "start_line": first, "end_line": last}
        entry = {**entry, "region": region}
    key += entry["id"]
    st.subheader("Inspect conversion")
    st.text(source_location(entry))
    st.caption(entry["confidence"].replace("_", " ").capitalize() + " · Runtime equivalence unverified")
    rendered, anchors, generated = annotated(entry)
    findings = {row["id"]: row for row in entry["findings"]}
    focus = 1
    sql_focus = 1
    if findings:
        selected_finding = st.selectbox("Find a line to inspect", list(findings),
                                        format_func=lambda value: f"Draft line {anchors[value]} · "
                                        + findings[value]["message"], key=key + "finding")
        item = findings[selected_finding]
        focus = anchors[selected_finding]
        if item.get("generated_line"):
            sql_focus = item["generated_line"]
            st.caption(f"Generated SQL line {item['generated_line']} · Review comment at draft line {focus}")
        else:
            st.caption(f"Review comment at draft line {focus} · Original evidence below")
    source, draft = st.columns(2)
    with source:
        st.markdown("**Pinned source**")
        if region["end"] > region["start"] and st.toggle("Show pinned source evidence", key=key + "source"):
            try:
                excerpt = service.evidence(store, workspace, project["id"], region)
                first = region.get("start_line", 1)
                last = first + max(0, len(excerpt.splitlines()) - 1)
                start = first if last - first < 100 else st.number_input(
                    "First source line", first, last, key=key + "source_line")
                st.code(numbered_excerpt(excerpt, first, int(start - first)), language=None)
            except ValueError as exc:
                st.warning(str(exc))
    with draft:
        view = st.segmented_control("Code view", ["Annotated draft", "Generated SQL"], default="Annotated draft",
                                    required=True, key=key + "code_view") if file else "Annotated draft"
        if not file:
            st.markdown("**Annotated draft**")
        text, current = (file["sql"], sql_focus) if file and view == "Generated SQL" else (rendered, focus)
        last = len(text.splitlines())
        start = max(1, current - 5)
        if last > 100:
            start = st.number_input("First code line", 1, last, min(last, start), key=key + f"line_{view}_{current}")
        st.code(numbered_excerpt(text, 1, int(start - 1)), language="sql")
    st.subheader("Engineer comments")
    st.caption("Comments are attached to a revision and can capture missing inputs or decisions.")
    own = [item for item in comments if item["artifact"] == entry["id"]]
    if own:
        table_page("Comments on this artifact", [
            {"By": item["author"], "Line": f"{item['anchor']} {item['line'] or ''}".strip(),
             "Revision": "Current" if item["revision"] == base["id"] else item["revision"][:8],
             "Status": item["status"], "Comment": item["message"]} for item in own], key + "comments")
    anchor_options = {"section": "Whole section"}
    if region.get("start_line") and region["end"] > region["start"]:
        anchor_options["source"] = "Original source line"
    if generated:
        anchor_options["generated"] = "Generated SQL line"
    anchor = st.selectbox("Attach comment to", list(anchor_options), format_func=anchor_options.get,
                          key=key + "anchor")
    with st.form(key + "comment_form"):
        line = None
        if anchor == "source":
            line = int(st.number_input("Source line", region["start_line"], region["end_line"]))
        elif anchor == "generated":
            line = int(st.number_input("Generated line", 1, len(file["sql"].splitlines())))
        author = st.text_input("Comment author", max_chars=160)
        message = st.text_area("Engineer comment or requested input", max_chars=2000)
        if st.form_submit_button("Post comment"):
            service.add_review_comment(store, workspace, project["id"], base["id"], entry["id"],
                                       anchor, line, author, message)
            st.rerun()
    open_comments = {item["id"]: item for item in own if item["status"] == "open"}
    if open_comments:
        chosen = st.selectbox("Open comment", list(open_comments), key=key + "resolve",
                              format_func=lambda value: open_comments[value]["message"][:100])
        if st.button("Resolve comment", key=key + "resolve_button"):
            service.resolve_review_comment(store, workspace, project["id"], chosen)
            st.rerun()


def review(store, workspace, project, base, details, key):
    plans = {name: row for name, row in base["plan"]["outputs"].items() if not row.get("excluded")}
    comments = service.review_comments(store, workspace, project["id"])
    inventory = artifacts(project, base, details, comments)
    with st.expander("Review queue"):
        table_page("Review findings and next actions", details["findings"], key + "queue")
    if not inventory:
        st.info("No conversion artifacts are available. Inspect the source ledger in Scope.")
        return
    st.subheader("Converted code")
    show = st.toggle("Show only artifacts needing review", key=key + "needs_review")
    visible = {name: entry for name, entry in inventory.items() if not show or (
        entry["findings"] or entry["open_notes"] or entry["status"] == "comment_only")}
    if not visible:
        st.info("No artifacts match the review filter.")
        return
    table_page("Converted code inventory", [{
        "Artifact": entry["path"], "Source": source_location(entry), "Status": entry["status"].replace("_", " "),
        "Confidence": entry["confidence"].replace("_", " "), "Findings": len(entry["findings"]),
        "Open comments": entry["open_notes"],
    } for entry in visible.values()], key + "inventory")
    picked = st.selectbox("Artifact to inspect", list(visible), format_func=lambda name: visible[name]["path"],
                         key=key + "artifact")
    entry = visible[picked]
    artifact_inspector(store, workspace, project, base, entry, comments, key)
    selected = entry["model"]
    if selected is None:
        return
    output = plans[selected]
    if remerge := output.get("sas_remerge"):
        st.text("SAS source grain · " + remerge["grain"])
    if details["active"].get(selected) == "engineer_accepted":
        st.caption("Engineer accepted · semantic equivalence unverified")
    elif base["reviews"].get(selected, {}).get("key") == details["review_keys"][selected]:
        st.caption("Engineer reviewed")
    if output.get("manual"):
        with st.expander("Define this output's conversion contract"):
            with st.form(key + selected + "contract"):
                possible = [name for name, row in plans.items() if name != selected and not row.get("excluded")]
                possible += list(base["plan"]["physical"])
                inputs = st.multiselect("Required inputs", possible, default=[
                    name for name in output["inputs"] if name in possible])
                contract = output.get("contract", {})
                behavior = st.text_area("Intended output behavior", contract.get("behavior", ""), max_chars=2000)
                prerequisites = st.text_area("Source, ordering and retained processing prerequisites",
                                             contract.get("prerequisites", ""), max_chars=2000)
                relations = st.text_area("Additional external inputs", placeholder="schema.table or catalog.schema.table, one per line",
                                         max_chars=4000)
                if st.form_submit_button("Save conversion contract"):
                    service.set_contract(store, workspace, project["id"], base["id"], selected, inputs,
                                         behavior, prerequisites, relations=relations.split())
                    st.rerun()
    if output.get("sas_order") and output.get("contract"):
        with st.expander("Draft ordered SAS SQL"):
            st.caption(output["manual"])
            with st.form(key + selected + "sas_order"):
                order = st.text_input("Priority columns in order", placeholder="event_date ASC, event_id ASC", max_chars=800)
                confirmed = st.checkbox("I confirmed the priority uniquely orders rows within each SAS group.")
                if st.form_submit_button("Preview ordered SQL diff"):
                    if not confirmed:
                        raise ValueError("Confirm that the priority uniquely orders rows within each SAS group")
                    st.session_state[key + "sas_proposal"] = service.ordered_sas_proposal(
                        project, base, selected, order.split(","))
            if proposal := st.session_state.get(key + "sas_proposal"):
                if selected in proposal["edits"]:
                    patch_panel(store, workspace, project, base, proposal)
    obligations = [row for row in details["findings"] if row["model"] == selected and not row["inherited_from"]]
    if details["tiers"][selected] != "blocked":
        with st.expander("Record engineer review"):
            with st.form(key + selected + "accept"):
                reviewer = st.text_input("Reviewer", max_chars=160)
                reason = st.text_area("Intended behavior and accepted uncertainty", max_chars=4000)
                accepted = [row["id"] for row in obligations if st.checkbox(row["message"], key=row["id"] + key)]
                if st.form_submit_button("Record review"):
                    service.record_review(store, workspace, project["id"], base["id"], selected, reviewer, reason, accepted)
                    st.rerun()
    with st.expander("Propose a manual edit"):
        edit_scope = st.multiselect("Files to edit", list(plans), default=[selected], key=key + selected + "manual_scope",
                                    max_selections=10)
        with st.form(key + selected + "manual"):
            changes = {model: st.text_area(model + ".sql", value=base["files"].get(model, {}).get("sql", ""),
                                          max_chars=engine.MAX_ARTIFACT, key=key + "draft" + model) for model in edit_scope}
            reason = st.text_input("Edit rationale", max_chars=4000)
            if st.form_submit_button("Preview manual diff", disabled=not edit_scope):
                st.session_state[key + "manual_proposal"] = service.propose(base, changes, reason)
        if proposal := st.session_state.get(key + "manual_proposal"):
            patch_panel(store, workspace, project, base, proposal)


def schemas(store, workspace, project, base, details, key):
    rows = [{"model": model, "column": column, **fact} for model, layout in details["schemas"].items()
            for column, fact in layout.items()]
    only_assumed = st.toggle("Show assumed strings only")
    query = st.text_input("Filter columns", max_chars=120).casefold()
    table_page("Output types and provenance", [
        row for row in rows if (not only_assumed or row["provenance"] == "assumed_string")
        and query in (row["model"] + "." + row["column"]).casefold()], key + "columns")
    physical = base["plan"]["physical"]
    if physical:
        with st.expander("Bulk source mappings"):
            template = [{"source": name, **{field: row[field] for field in ("catalog", "schema", "identifier")}}
                        for name, row in physical.items()]
            st.download_button("Download mapping CSV", report_csv(template), "source-mappings.csv", "text/csv",
                               on_click="ignore", key=key + "mapping-template")
            upload = st.file_uploader("Edited source mapping CSV", type=["csv"], key=key + "mapping-upload")
            if upload:
                mappings = service.read_source_mappings(upload.getvalue())
                table_page("Mappings to confirm", [{"source": name, **row} for name, row in mappings.items()], key + "mapping-preview")
                if st.button("Apply source mappings", key=key + "apply-mappings"):
                    service.revise_schemas(store, workspace, project["id"], base["id"], {
                        "source_mappings": {**base["settings"].get("source_mappings", {}), **mappings}})
                    st.rerun()
    with st.expander("Confirm a source mapping", expanded=bool(physical)):
        if physical:
            source = st.selectbox("Source", list(physical), format_func=lambda name: physical[name].get("relation", name))
            row = physical[source]
            with st.form(key + source + "mapping"):
                catalog = st.text_input("Source catalog", value=row["catalog"])
                schema = st.text_input("Source schema", value=row["schema"])
                identifier = st.text_input("Source identifier", value=row["identifier"])
                if st.form_submit_button("Save source mapping"):
                    mappings = {**base["settings"].get("source_mappings", {}),
                                source: {"catalog": catalog, "schema": schema, "identifier": identifier}}
                    service.revise_schemas(store, workspace, project["id"], base["id"], {"source_mappings": mappings})
                    st.rerun()
        else:
            st.caption("No physical source mappings are required.")
    with st.expander("Confirm column types"):
        groups = list(details["schemas"]) + list(physical)
        if not groups:
            return
        group = st.selectbox("Model or physical source", groups)
        input_source = group in physical
        affected = [model for model, row in base["plan"]["outputs"].items() if group in row["inputs"]]
        if affected:
            st.caption("Direct dependents: " + ", ".join(affected[:30]) + ". Downstream checks and reviews are revalidated.")
        model_types = base["settings"].get("types", {})
        source_types = base["settings"].get("input_types", {})
        upload = st.file_uploader("Import type definitions for this relation", type=["sql", "sas", "json", "yml", "yaml", "xml"])
        with st.form(key + group + "types"):
            lookup = source_types.get(group, {}) if input_source else {
                name.removeprefix(group + "."): value for name, value in model_types.items()
                if name.startswith(group + ".")}
            raw = st.text_area("Confirmed column types (JSON)", json.dumps(lookup, indent=2), max_chars=50_000)
            if st.form_submit_button("Create schema revision"):
                parsed = json.loads(raw)
                if not isinstance(parsed, dict):
                    raise ValueError("Enter a JSON object of column names and Databricks type names")
                if upload:
                    definitions, warnings = import_schema(upload.name, upload.getvalue())
                    if len(definitions) != 1 or warnings:
                        raise ValueError("Import one relation with complete type definitions")
                    parsed.update({column.name: column.data_type for column in definitions[0].columns if column.data_type})
                settings = {"input_types": {**source_types, group: parsed}} if input_source else {
                    "types": {**{k: v for k, v in model_types.items() if not k.startswith(group + ".")},
                              **{f"{group}.{name}": value for name, value in parsed.items()}}}
                service.revise_schemas(store, workspace, project["id"], base["id"], settings)
                st.rerun()


def reconciliation_view(store, workspace, project, base, details, key, revisions):
    st.subheader("Legacy reconciliation")
    st.caption("The coverage table reflects the latest external results for each model and its approved checks.")
    plans = validation.reconciliation_plan(project, base, details)
    runs = service.reconciliation_runs(store, workspace, project["id"])
    recent = {}
    for run in reversed(runs):
        if run["revision"] == base["id"]:
            recent.update({model: entry for model, entry in run["models"].items()
                           if model in plans and plans[model]["comparison_id"] == entry["comparison_id"]})
    if plans:
        coverage = []
        for model, plan in plans.items():
            stages = [*plan["stages"]]
            if replay_stage := plan.get("replay_stage"):
                stages.append(replay_stage)
            for stage in stages:
                recorded = recent.get(model, {}).get("stages", {}).get(stage, {})
                coverage.append({"model": model, "legacy baseline": plan["legacy"], "target": plan["target"],
                                 "stage": stage.replace("_", " "), "status": recorded.get("status", "not observed"),
                                 "coverage": "complete" if recorded.get("complete") else "incomplete"})
        table_page("Current reconciliation coverage", coverage, key + "comparison-coverage")
        model = st.selectbox("Comparison template model", list(plans), key=key + "template-model")
        st.download_button("Download results template", validation.reconciliation_template({model: plans[model]}),
                           f"{model}-reconciliation-results.csv", "text/csv", on_click="ignore", key=key + "template")
    elif not runs:
        st.info("Confirm a legacy baseline for an active model to start recording comparisons.")
    if runs:
        by_id = {run["id"]: run for run in runs}
        record = st.selectbox("Recorded comparison", list(by_id), key=key + "comparison-record",
                              format_func=lambda value: f"{by_id[value]['recorded_at'][:19]} · "
                              f"{'current' if by_id[value]['revision'] == base['id'] else 'previous'} revision")
        run = by_id[record]
        if run["revision"] != base["id"]:
            st.info(f"Showing evidence from revision {run['revision'][:8]}.")
        if any("initial_load" in (stages := entry.get("stages", {})) and validation.REPLAY_STAGE not in stages
               for entry in run["models"].values()):
            st.info("This upload predates the incremental replay checks.")
        if any(entry.get("empty_sample") for entry in run["models"].values()):
            st.info("A comparison stage with zero rows in both systems has incomplete coverage.")
        elif any(entry.get("complete") is False for entry in run["models"].values()):
            st.info("This upload has incomplete coverage for one or more comparison stages.")
        table_page("Reported reconciliation checks", [
            {"model": model, **check, "stage": check.get("stage", "comparison").replace("_", " "),
             "check": check["check"].replace("_", " ")}
            for model, entry in sorted(run["models"].items()) for check in entry["checks"]
        ], key + "comparison-checks")
    with st.expander("Import comparison results"):
        st.caption("Use the same snapshot, confirmed keys, and date window for both relations. Enter keyed counts "
                   "in comparison_value and other metrics in both relation columns.")
        st.caption("For incremental models, enter the same input_snapshot_id on the initial_load and repeat_run "
                   "row_count rows. Use initial_vs_repeat rows to compare the saved target after the initial load "
                   "directly with the target after replay.")
        with st.form(key + "import-comparison"):
            revision_id = st.selectbox("Comparison revision", revisions)
            upload = st.file_uploader("Reconciliation results CSV", type=["csv"])
            if st.form_submit_button("Record comparison results"):
                if not upload:
                    raise ValueError("Upload the filled reconciliation results CSV")
                service.import_reconciliation(store, workspace, project["id"], revision_id, upload.getvalue())
                st.rerun()


def validation_view(store, workspace, project, base, details, key):
    st.subheader("External validation")
    st.caption("Compile, build, and data-test results are recorded for the selected revision. "
               "Runtime equivalence requires a separate comparison with the legacy system.")
    runs = service.validation_runs(store, workspace, project["id"])
    if runs:
        by_id = {row["invocation"]: row for row in runs}
        run_id = st.selectbox("Recorded invocation", list(by_id), key=key + "run",
                              format_func=lambda value: f"{by_id[value]['command']} · {value[:8]} · "
                              + ("current revision" if by_id[value]["revision"] == base["id"] else "previous revision"))
        run = by_id[run_id]
        if run["revision"] == base["id"] and (omitted := details["active"].keys() - run["models"].keys()):
            st.caption(f"{len(omitted)} active models were outside this invocation's project scope.")
        table_page("Imported model observations", [
            {"model": model, "compile": entry.get("compile", "not observed"), "build": entry.get("build", "not observed"),
             "tests": ", ".join(f"{entry.get('test_labels', {}).get(test, test)} · {status}"
                                for test, status in entry.get("tests", {}).items()) or "not observed"}
            for model, entry in sorted(run["models"].items())], key + "evidence-rows")
    revisions = [base["id"], *(row["id"] for row in service.history(store, workspace, project["id"])
                              if row["id"] != base["id"])]
    with st.expander("Import dbt artifacts"):
        st.caption(f"Set {validation.REVISION_ENV} to the revision in the handoff. Upload both files from one external invocation.")
        with st.form(key + "import-validation"):
            revision_id = st.selectbox("Handoff revision", revisions)
            manifest = st.file_uploader("dbt manifest.json", type=["json"])
            results = st.file_uploader("dbt run_results.json", type=["json"])
            if st.form_submit_button("Record validation results"):
                if not manifest or not results:
                    raise ValueError("Upload both dbt artifacts from the same invocation")
                service.import_validation(store, workspace, project["id"], revision_id, manifest.getvalue(), results.getvalue())
                st.rerun()
    reconciliation_view(store, workspace, project, base, details, key, revisions)
    models = sorted(set(base["files"]) & details["schemas"].keys())
    if not models:
        return
    st.subheader("Confirmed checks and materialization")
    model = st.selectbox("Model to configure", models, key=key + "rules-model")
    if warning := details["validation_warnings"].get(model):
        st.warning(warning, title="Update the saved validation checks")
    columns = [name for name in details["schemas"][model] if engine.NAME.fullmatch(name)]
    rules = base["settings"].get("validation_rules", {}).get(model, {})
    comparison = rules.get("comparison", {})
    parents = [parent for parent in details["lineage"]["nodes"][model] if parent in models]
    current_parent = rules.get("relationship", {}).get("model", "")
    parent = st.selectbox("Relationship test parent", ["", *parents], index=parents.index(current_parent) + 1
                          if current_parent in parents else 0, format_func=lambda value: value or "None", key=key + model + "parent")
    with st.form(key + model + "checks"):
        not_null = st.multiselect("Required columns", columns, default=[c for c in rules.get("not_null", []) if c in columns])
        unique = st.multiselect("Individually unique columns", columns, default=[c for c in rules.get("unique", []) if c in columns])
        relationship = None
        if parent and columns:
            saved = rules.get("relationship", {})
            parent_columns = [name for name in details["schemas"][parent] if engine.NAME.fullmatch(name)]
            child_key = st.selectbox("Foreign key column", columns, index=columns.index(saved["column"])
                                     if saved.get("column") in columns else 0)
            parent_key = st.selectbox("Referenced parent column", parent_columns, index=parent_columns.index(saved["field"])
                                      if saved.get("field") in parent_columns else 0)
            relationship = {"column": child_key, "model": parent, "field": parent_key}
        legacy = st.text_input("Legacy relation for reconciliation", comparison.get("legacy", ""), max_chars=386)
        keys = st.multiselect("Comparison keys (together identify a row)", columns,
                              default=[c for c in comparison.get("keys", []) if c in columns])
        keyed_values = st.multiselect("Keyed value columns", columns,
                                     default=[c for c in comparison.get("columns", []) if c in columns],
                                     max_selections=32,
                                     help="Compare these non-key columns across matching keys. Numeric sum columns are also checked by key when keys are set.")
        totals = st.multiselect("Numeric columns to compare by sum", columns,
                                default=[c for c in comparison.get("totals", []) if c in columns])
        tolerance = st.number_input("Absolute tolerance for comparison totals", min_value=0.0,
                                    value=float(comparison.get("tolerance", 0)), format="%.9g")
        window = comparison.get("window", {})
        dates = [column for column in columns if details["schemas"][model][column]["target_type"].startswith(("DATE", "TIMESTAMP"))]
        date_column = st.selectbox("Comparison window column", ["", *dates],
                                   index=dates.index(window["column"]) + 1 if window.get("column") in dates else 0,
                                   format_func=lambda value: value or "All rows")
        starts = st.text_input("Window start (inclusive, YYYY-MM-DD)", value=window.get("start", ""), max_chars=10)
        ends = st.text_input("Window end (exclusive, YYYY-MM-DD)", value=window.get("end", ""), max_chars=10)
        suggested = base["plan"]["outputs"][model].get("suggested_merge_keys", [])
        merge = base["settings"].get("incremental", {}).get(model, suggested)
        merge_keys = st.multiselect("Delta merge keys", columns, default=[c for c in merge if c in columns],
                                    help="Use for an upsert-ready SELECT with one non-null row per key. "
                                         "An empty selection uses the original materialization.")
        if st.form_submit_button("Save confirmed checks and materialization"):
            baseline = {"legacy": legacy.strip(), "keys": keys, "columns": keyed_values,
                        "totals": totals, "tolerance": tolerance}
            if date_column:
                baseline["window"] = {"column": date_column, "start": starts, "end": ends}
            service.configure_validation(store, workspace, project["id"], base["id"], model, {
                "not_null": not_null, "unique": unique, "relationship": relationship,
                "comparison": baseline if legacy.strip() else None,
            }, merge_keys)
            st.rerun()


def chat(store, workspace, project, base, details, key):
    session_reply = f"migration_session_reply_{workspace}_{project['id']}"
    profiles = {row["profile_id"]: row["name"] for row in store.rows(
        "SELECT profile_id,name FROM llm_profiles WHERE workspace_id=? ORDER BY name", [workspace])}
    outputs = [model for model, row in base["plan"]["outputs"].items() if not row.get("excluded")]
    if not outputs or not profiles:
        st.info("Choose a planned output and configure a provider connection to use AI assistance.")
        st.page_link("ui/pages/connections.py", label="Connections & AI")
    else:
        labels = dict(zip(assistance.PURPOSES, ["Draft conversion", "Explain", "Review against source", "Propose edits",
                                              "Propose optimization"]))
        with st.form(key + "AI"):
            provider = st.selectbox("Provider", list(profiles), format_func=profiles.get)
            mode = st.selectbox("Request", assistance.PURPOSES, format_func=labels.get)
            models = st.multiselect("Scoped files", outputs, max_selections=50)
            include_dependencies = st.checkbox("Include upstream model evidence")
            message = st.text_area("Question or instructions", max_chars=4000)
            preview = st.form_submit_button("Preview provider disclosure")
        preview_key = key + "disclosure"
        if preview:
            st.session_state.pop(preview_key, None)
            request = (provider, models, mode, message, include_dependencies)
            prepared = assistance.prepare(store, workspace, project["id"], base["id"], *request[:4],
                                          dependencies=include_dependencies)
            st.session_state[preview_key] = (request, prepared["pin"])
        if stored := st.session_state.get(preview_key):
            (pid, scope, purpose, text, parents), pin = stored
            prepared = assistance.prepare(store, workspace, project["id"], base["id"], pid, scope, purpose, text,
                                          dependencies=parents)
            if prepared["pin"] != pin:
                st.warning("The scope or recipient changed. Preview again before sending.")
            else:
                st.text("Recipient: " + prepared["recipient"] + " · " + prepared["profile"].model)
                st.caption(f"{prepared['tokens']:,} estimated input and reserved output tokens")
                with st.expander("Exact redacted request data"):
                    st.json(prepared["body"], expanded=False)
                if st.button("Send this disclosure", type="primary"):
                    st.session_state.pop(preview_key, None)
                    transient = {}
                    st.session_state[session_reply] = transient

                    def work(progress, cancelled):
                        progress(.2, "Waiting for scoped provider response")
                        try:
                            result = assistance.dispatch(
                                store, workspace, project["id"], base["id"], pid, scope, purpose, text, pin,
                                dependencies=parents, cancelled=cancelled)
                            if not store.setting(workspace, "llm_history", False):
                                transient["response"] = result
                            return {"status": "completed", "missing_outputs": result["missing_outputs"]}
                        except ValueError as exc:
                            return {"status": "failed", "error": str(exc)[:600]}
                    assistance.start_job(store, workspace, project["id"], analysis_jobs(str(store.home)), work)
                    st.rerun()
    activity = assistance.attempts(store, workspace, project["id"])
    if activity:
        st.caption(f"Run budget · {len(activity)} / {assistance.MAX_REQUESTS} requests · "
                   f"{sum(row['reserved'] for row in activity):,} / {assistance.MAX_RESERVED_TOKENS:,} reserved tokens.")
        if any(row["status"] in {"unknown", "reserved"} for row in activity):
            st.warning("An interrupted or unknown request still counts against the budget. Retry requires a fresh disclosure preview.")
    responses = assistance.responses(store, workspace, project["id"])
    temporary = st.session_state.get(session_reply, {}).get("response")
    if temporary and temporary["revision"] == base["id"]:
        responses = [{"id": "latest", **temporary}, *responses]
    if responses:
        labels = {row["id"]: f"{row['purpose'].capitalize()} · {', '.join(row['scope'])} · {row['revision'][:8]} · {row['id'][:6]}"
                  for row in responses}
        selected = st.selectbox("Responses and proposed edits", list(labels), format_func=labels.get)
        response = next(row for row in responses if row["id"] == selected)
        st.caption("Model response")
        st.text(response["answer"])
        if response["citations"]:
            st.text("Source regions: " + ", ".join(response["citations"]))
        if response["missing_outputs"]:
            st.warning("Unresolved in this response: " + ", ".join(response["missing_outputs"]))
        if proposal := response.get("proposal"):
            st.caption("Files in the proposed diff · " + ", ".join(proposal["edits"]))
            patch_panel(store, workspace, project, base, proposal)


def knowledge(store, workspace, project, base, key):
    rules = assistance.lessons(store, workspace, project["id"])
    table_page("Approved lessons and versions", [{k: row[k] for k in (
        "pattern", "kind", "scope", "version", "status", "guidance", "owner")} for row in rules], key + "rules")
    owned = {row["id"]: row for row in rules if row["project"] == project["id"] and row["status"] == "approved"}
    if owned:
        chosen = st.selectbox("Approved version", list(owned), format_func=lambda value: owned[value]["pattern"])
        if st.button("Revoke approved version"):
            assistance.revoke_lesson(store, workspace, project["id"], chosen)
            st.rerun()
    if not base["files"]:
        return
    with st.form(key + "lesson"):
        model = st.selectbox("Evidence model", list(base["files"]))
        scope = st.selectbox("Reuse scope", ["project", "workspace"])
        replacements = st.selectbox("Replace previous approved version", ["", *owned],
                                    format_func=lambda value: owned[value]["pattern"] if value else "New lesson")
        pattern = st.text_input("Literal source pattern", max_chars=120)
        source_region = next(row for row in base["plan"]["regions"] if row["id"] == base["plan"]["outputs"][model]["region"])
        source = next(row for row in project["snapshot"]["sources"] if source_region["source"] == row["id"])
        required = st.text_input("Required confirmed target types (comma separated)")
        guidance = st.text_area("Conversion guidance", max_chars=2000)
        example = st.text_area("Positive example", max_chars=1000)
        counterexample = st.text_area("Counterexample", max_chars=1000)
        owner = st.text_input("Lesson owner", max_chars=160)
        approval = st.checkbox("Approve this version for the selected scope")
        save = st.form_submit_button("Save approved lesson")
        if save:
            if not approval:
                raise ValueError("Explicit approval is required")
            assistance.save_lesson(store, workspace, project["id"], base["id"], {
                "scope": scope, "kind": source["kind"], "dialect": source.get("dialect", ""), "pattern": pattern,
                "required_types": [item.strip().upper() for item in required.split(",") if item.strip()],
                "guidance": guidance, "example": example, "counterexample": counterexample, "owner": owner,
            }, model, replaces=replacements or None)
            st.rerun()


def project_view(store, workspace, project_id):
    project, base = service.load(store, workspace, project_id)
    st.header(project["name"])
    st.caption(f"dbt · {WAREHOUSES[project['snapshot']['warehouse']].label} · "
               f"Revision {base['id'][:8]} · Runtime equivalence unverified")
    job_status(store, workspace, project_id)

    def start_conversion(*, reconvert=False):
        def work(progress, cancelled):
            progress(.15, "Converting retained sources")
            try:
                result = service.convert(store, workspace, project_id, base["id"], cancelled, progress, reconvert=reconvert)
                return {"revision": result["id"]}
            except ValueError as exc:
                return {"status": "failed", "error": str(exc)[:600]}
        assistance.start_job(store, workspace, project_id, analysis_jobs(str(store.home)), work)
        st.rerun()

    if base["plan"] is None:
        st.info("The input snapshot is ready. Run static conversion to produce candidate models and review findings.")
        if st.button("Run static conversion", type="primary"):
            start_conversion()
        return
    details = service.report(project, base)
    st.caption(f"{sum(details['coverage'].values()):,} regions accounted for · "
               f"{details['coverage'].get('converted', 0):,} converted · "
               f"{details['coverage'].get('unresolved', 0):,} unresolved · "
               f"{details['coverage'].get('excluded', 0):,} excluded")
    active = list(details["active"].values())
    st.caption(f"{active.count('statically_qualified'):,} statically qualified models · "
               f"{active.count('engineer_accepted'):,} engineer-accepted models")
    key = f"migration_{workspace}_{project_id}_{base['id']}_"
    view = section("Migration view", ["Scope", "Schemas & mappings", "Review", "AI assistance", "Lineage",
                                      "Validation", "Export", "Knowledge"], "migration_view_" + project_id)
    if view == "Scope":
        table_page("Source ledger", base["plan"]["regions"], key + "regions")
        st.caption("Coverage by decoded source characters")
        st.json(details["characters"])
        choices = {row["id"]: row for row in base["plan"]["regions"]
                   if row["gap"] and row["disposition"] != "excluded"}
        if choices:
            with st.expander("Narrow migration scope"):
                with st.form(key + "exclude"):
                    region = st.selectbox("Unresolved region", list(choices),
                                          format_func=lambda value: value + " · " + choices[value]["gap"])
                    reason = st.text_area("Exclusion rationale and retained processing prerequisite", max_chars=2000)
                    external = st.text_area("Optional externally supplied relation contract (JSON)", max_chars=10_000,
                                            help="For a single excluded producer, set catalog, schema, identifier, owner and columns. "
                                                 "Dependent code will require reviewed edits to use the new source.")
                    if st.form_submit_button("Record explicit exclusion"):
                        service.resolve_scope(store, workspace, project_id, base["id"], region, reason,
                                              external=json.loads(external) if external.strip() else None)
                        st.rerun()
        with st.expander("Revision history"):
            st.caption("Create a fresh draft with the current converter and the project's pinned sources and target profile. "
                       "SQL edits, mappings, scope decisions, validation settings, and reviews stay on their saved revisions. "
                       "Restore an earlier revision here to bring those decisions back.")
            if st.button("Reconvert from pinned sources", key=key + "reconvert"):
                start_conversion(reconvert=True)
            histories = {row["id"]: str(row["created_at"]) for row in service.history(store, workspace, project_id)
                         if row["id"] != base["id"]}
            if histories:
                prior = st.selectbox("Prior revision", list(histories), format_func=lambda value: histories[value] + " · " + value[:8])
                if st.button("Restore as new revision"):
                    service.restore_revision(store, workspace, project_id, base["id"], prior)
                    st.rerun()
    elif view == "Schemas & mappings":
        schemas(store, workspace, project, base, details, key)
    elif view == "Review":
        review(store, workspace, project, base, details, key)
    elif view == "AI assistance":
        chat(store, workspace, project, base, details, key)
    elif view == "Lineage":
        st.subheader("Migrated lineage")
        graph = lineage_graph(details)
        if graph.nodes:
            graph_view(graph, key + "graph", VisualizationSettings.from_store(store, workspace))
        st.caption("Generated dependency edges are extracted from model SQL. The graph displays up to 200 nodes.")
        table_page("Generated dependency evidence", details["lineage"]["edges"], key + "edges")
        table_page("Known generated column lineage", details["lineage"]["columns"], key + "column_edges")
        original = project["snapshot"].get("original_edge_labels", project["snapshot"].get("original_edges", []))
        table_page("Pinned analyzed lineage", [{"source": a, "target": b} for a, b in original], key + "original")
        st.json({name: details["lineage"][name] for name in ("missing", "extra")})
    elif view == "Validation":
        validation_view(store, workspace, project, base, details, key)
    elif view == "Export":
        mode = st.radio("Bundle", ["Draft bundle", "Reviewed handoff", "Pilot handoff"])
        reviewed = mode != "Draft bundle"
        pilot = None
        pilot_ready = True
        if mode == "Pilot handoff":
            pilot = st.multiselect("Pilot outputs", sorted(details["active"]))
            pilot_ready = False
            if pilot:
                try:
                    picked, inputs = service.pilot_scope(base, details, pilot)
                    table_page("Included models", [{"model": model, "required upstream": model not in pilot}
                                                   for model in sorted(picked)], key + "pilot")
                    st.caption(f"{len(inputs)} required external sources")
                    pilot_ready = True
                except ValueError as exc:
                    st.info(str(exc))
        image = st.selectbox("Graph image", [None, "svg", "png"], format_func=lambda value: value.upper() if value else "None")
        workbook = st.checkbox("Include mapping and type workbook")
        if mode == "Reviewed handoff" and not details["eligible"]:
            st.info("Resolve required outputs, structural findings and outstanding reviews for a reviewed handoff.")
        if st.button("Prepare dbt bundle", disabled=not pilot_ready or (pilot is None and reviewed and not details["eligible"])):
            with st.spinner("Preparing revision-pinned bundle…"):
                data = service.bundle(store, workspace, project_id, base["id"], reviewed,
                                      image_format=image, workbook=workbook, pilot=pilot)
            st.download_button("Download dbt project", data, f"{engine.slug(project['name'])}-{base['id'][:8]}.zip",
                               mime="application/zip", on_click="ignore")
    elif view == "Knowledge":
        knowledge(store, workspace, project, base, key)


title("Migration", "Convert retained SQL, SAS, dbt and design evidence into a reviewable dbt project.")
store, workspace = context()
prefix = f"migration_{workspace}_"
items = {row["id"]: row["name"] for row in service.projects(store, workspace)}
entry = st.session_state.get(prefix + "entry", {})
if opened := st.session_state.pop(prefix + "open", None):
    st.session_state[prefix + "project"] = opened
if entry and st.session_state.pop(prefix + "new", False):
    st.session_state[prefix + "project"] = ""
project_id = st.selectbox("Migration project", ["", *items], format_func=lambda key: items.get(key, "New migration"),
                          key=prefix + "project")
try:
    if project_id:
        project_view(store, workspace, project_id)
    else:
        if entry and st.button("Clear entry scope", key=prefix + "clear"):
            st.session_state.pop(prefix + "entry", None)
            st.session_state.pop(prefix + "preflight", None)
            st.rerun()
        if not entry and (design := load_builder(store, workspace)).tables and st.button("Start from Builder design"):
            st.session_state[prefix + "entry"] = {"builder_revision": design.revision}
            st.session_state.pop(prefix + "preflight", None)
            st.rerun()
        setup(store, workspace, prefix, entry)
except (ValueError, OSError, AgentError) as exc:
    st.error(str(exc))
