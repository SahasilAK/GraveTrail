"""Focused, bounded column derivations; direct references remain on Columns."""
import json

import streamlit as st

from dataforge.exports import report_csv
from dataforge.services import analysis_is_current
from dataforge.transformations import column_catalog, trace_columns
from ui.common import choose_asset, context, load_graph, title

title("Transformation lineage", "Follow how a column is produced, or which outputs depend on it.")
store, w = context()
graph = load_graph(store, w)
asset = choose_asset(graph, "transformations")
if not asset:
    st.info("Choose an asset to explore its column transformations.")
    st.stop()

if not analysis_is_current(store, w):
    st.warning("Analysis is out of date. These are the last stored transformations; run Analysis to refresh coverage.")

catalog = column_catalog(store, w, asset, limit=500)
scope_key = f"{w}_{asset}"
choices = {c["column_id"]: c for c in catalog}
if choices:
    if st.session_state.get("transformation_column_" + scope_key) not in choices:
        st.session_state.pop("transformation_column_" + scope_key, None)
    column = st.selectbox("Column to trace", list(choices),
        format_func=lambda k: f'{choices[k]["column_name"]} · {choices[k].get("scope") or "physical"}' +
                             (f' · v{choices[k]["version"]}' if choices[k].get("version") else ""),
        key="transformation_column_" + scope_key)
    if len(catalog) == 500:
        st.caption("Showing up to 500 columns. Enter a column name or exact ID below if yours is outside this selection.")
else:
    column = None
    st.info("No transformation columns are cataloged for this asset. Run Analysis to establish coverage, or enter a column name to inspect its state.")
requested = st.text_input("Column name or exact ID", placeholder="Optional: trace a column outside the selector",
                          key="transformation_exact_" + scope_key)
column = requested.strip() or column
if not column:
    st.stop()

with st.container(horizontal=True, vertical_alignment="bottom"):
    direction = st.segmented_control("Direction", ["upstream", "downstream"], default="upstream",
        format_func=lambda value: "How it is produced" if value == "upstream" else "What it affects",
        key="transformation_direction_" + scope_key) or "upstream"
    depth = st.slider("Transformation depth", 1, 15, 5, key="transformation_depth_" + scope_key)
    status = st.selectbox("Resolution status", ["all", "verified", "inferred", "unresolved"],
                         key="transformation_status_" + scope_key)

try:
    trace = trace_columns(store, w, asset, column, direction=direction, depth=depth,
                          limit=200, status=status, include_source=False)
except ValueError as exc:
    st.info(str(exc))
    st.stop()

steps = trace["derivations"]
coverage = trace["coverage"]
state_messages = {
    "constant": "Known constant: this output has no value input columns. Row-selection context may still apply.",
    "not_analyzed": "Transformation coverage is not available. Run Analysis to establish column derivations.",
    "unresolved": "This column could not be resolved statically. Review the coverage boundaries below.",
    "no_known_dependency": "No known dependency in this direction. This does not establish runtime independence.",
}
with st.container(horizontal=True):
    st.metric("Transformation steps", len(steps), border=True)
    st.metric("Coverage boundaries", len(coverage), border=True)
    st.metric("Trace state", trace["state"].replace("_", " ").capitalize(), border=True)
if trace["state"] in state_messages:
    st.info(state_messages[trace["state"]])
if trace["truncated"]:
    st.warning("This trace reached a traversal limit. Exported results carry the same incomplete coverage markers.")
elif not trace["complete"]:
    st.warning("Coverage is incomplete. Known steps are shown alongside their unresolved boundaries.")
if coverage:
    with st.expander("Coverage details", expanded=not steps):
        st.dataframe(coverage, hide_index=True, alt="Transformation coverage boundaries")
st.caption("Value inputs supply an output. Selection, matching, rowset and ordering roles describe other effects. Static coverage does not verify runtime behavior.")

if steps:
    st.subheader("Transformation steps")
    display = []
    for index, step in enumerate(steps, 1):
        evidence = step.get("evidence") or {}
        target = step["target"]
        display.append({"Step": index, "Output": f'{target.get("table", "")}.{target["column_name"]}',
            "Transformation": step["category"], "Status": step["status"],
            "Inputs and roles": "; ".join(f'{i.get("table", "")}.{i.get("column_name") or "[rowset]"} ({i["role"]})' for i in step["inputs"]),
            "Branch": step.get("branch"), "Source file": evidence.get("relative_path"),
            "Lines": f'{evidence.get("start_line", "")}–{evidence.get("end_line", "")}'})
    st.dataframe(display, hide_index=True, alt="Ordered column transformations and dependency roles")
    inspector = st.expander("Inspect a transformation", on_change="rerun", key="transformation_inspector_" + scope_key)
    if inspector.open:
        with inspector:
            step_key = "transformation_step_" + scope_key
            if st.session_state.get(step_key, 0) not in range(len(steps)):
                st.session_state.pop(step_key, None)
            selected = st.selectbox("Transformation step", range(len(steps)),
                format_func=lambda i: f'{i + 1}. {display[i]["Output"]} · {steps[i]["category"]}',
                key=step_key)
            step = steps[selected]
            st.caption("Original expression")
            st.code(step.get("expression") or "Expression unavailable", language="sql")
            if step["inputs"]:
                st.dataframe([{"Source": i["table"], "Column": i["column_name"] or "[rowset]",
                               "Role": i["role"], "Scope": i["scope"] or "physical",
                               "Version": i["version"] or "—"} for i in step["inputs"]],
                             hide_index=True, alt="Exact input columns and dependency roles")
            evidence = step.get("evidence") or {}
            st.caption(f'{evidence.get("relative_path", "Unknown source")} · lines {evidence.get("start_line", "?")}–{evidence.get("end_line", "?")} · {evidence.get("method", "static")}')
            st.caption("Analyzed source hash: " + str(evidence.get("source_hash") or "unavailable"))
            if evidence.get("file_id") and evidence.get("source_hash"):
                try:
                    source = store.file(evidence["file_id"], evidence["source_hash"])
                    start = max(1, evidence.get("start_line") or 1)
                    end = max(start, evidence.get("end_line") or start)
                    lines = source["raw_content"].splitlines()
                    preview = "\n".join(lines[start - 1:min(end, start + 199)])
                    st.code(preview[:12000],
                            language="sas" if source["extension"] == ".sas" else "sql")
                    if end >= start + 200 or len(preview) > 12000:
                        st.caption("Source preview is limited to 200 original lines and 12,000 characters.")
                except (ValueError, OSError, KeyError):
                    st.warning("The analyzed source version is unavailable. Reanalyze the source to refresh its evidence.")
            if paths := [p for p in trace["paths"] if p["derivation_id"] == step["derivation_id"]]:
                st.dataframe([{"Depth": p["depth"], "Effect": p["effect"].replace("_", " "),
                               "Output": display[selected]["Output"]} for p in paths],
                             hide_index=True, alt="Uncollapsed column path steps")

markers = {k: trace[k] for k in ("workspace_id", "asset_id", "column", "direction", "depth", "state", "truncated", "complete", "run_id")}
export_rows = [{**markers, "coverage": json.dumps(coverage, default=str),
                "paths": json.dumps([p for p in trace["paths"] if p["derivation_id"] == step["derivation_id"]], default=str),
                **{key: json.dumps(value, default=str) if isinstance(value, (dict, list)) else value
                   for key, value in step.items()}} for step in steps]
if not export_rows:
    export_rows = [{**markers, "coverage": json.dumps(coverage, default=str)}]
with st.popover("Export trace", icon=":material/download:"):
    st.caption("Exports contain this bounded trace, original expressions, evidence references and coverage markers.")
    st.download_button("Download JSON", lambda: json.dumps(trace, indent=2, default=str),
                       "column_transformations.json", "application/json", on_click="ignore")
    st.download_button("Download CSV", lambda: report_csv(export_rows),
                       "column_transformations.csv", "text/csv", on_click="ignore")
