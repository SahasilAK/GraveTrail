import json

import streamlit as st

from dataforge.services import column_names, column_report, column_usage_coverage
from ui.common import choose_asset, context, downloads, load_graph, source_viewer, title
from ui.copy_names import copy_names

title("Columns", "Columns read directly from an asset. References through downstream tables are excluded.")
store, w = context()
graph = load_graph(store, w)
asset = choose_asset(graph, "columns")
if asset:
    rows = column_report(store, w, asset)
    metadata = json.loads(graph.nodes[asset].get("metadata", "{}"))
    coverage = column_usage_coverage(store, w, asset)
    used, unused = column_names(rows, metadata, coverage_complete=coverage['complete'])
    wildcard = any(r["column_name"] == "*" for r in rows)
    needle = st.text_input("Filter columns", placeholder="Column name or comma-separated names")
    terms = [term.strip().casefold() for term in needle.split(",") if term.strip()]
    rows = [r for r in rows if not terms or any(term in r["column_name"].casefold() for term in terms)]
    with st.container(horizontal=True):
        st.metric("Known direct columns", len({r["column_name"] for r in rows if r["column_name"] != "*"}), border=True)
        st.metric("Direct references", len(rows), border=True)
        st.metric("Referencing files", len({r["file_id"] for r in rows}), border=True)
    if wildcard:
        st.warning("Wildcard coverage is unknown. No columns are invented without a trustworthy schema.")
    if not coverage['complete']:
        st.warning('Direct reference coverage is incomplete. ' + ' '.join(coverage['reasons']))
    if metadata.get("schema_status") == "declared":
        st.caption("A consistent imported SQL declaration supplies the schema. Wildcard expansions are labeled inferred; they do not verify the live database schema.")
        panel = st.expander("Declared schema and evidence", on_change="rerun", key="column_schema_panel")
        if panel.open:
            with panel:
                st.dataframe(metadata["columns"], hide_index=True)
                refs = metadata["schema_evidence"]
                ids = [e["statement_id"] for e in refs]
                evidence = store.rows("SELECT s.*,f.relative_path,s.content_hash AS source_hash,'SCHEMA' AS kind FROM statements s JOIN source_files f USING(file_id) WHERE s.workspace_id=? AND s.statement_id IN (" + ",".join("?" for _ in ids) + ")", [w, *ids])
                source_viewer(store, [e["file_id"] for e in evidence], "schema_source", evidence)
    st.subheader("Distinct used columns")
    st.caption("All known direct references for this asset, independent of the column filter.")
    if used:
        copy_names(used, f"used_columns_{w}_{asset}")
    else:
        st.caption("No named direct columns established.")
    unused_panel = st.expander("Unused columns" + (f" ({len(unused)})" if unused is not None else ""),
                               on_change="rerun", key=f"unused_columns_{w}_{asset}")
    if unused_panel.open:
        with unused_panel:
            if unused is None:
                st.info("Unused columns require a consistent declared schema and current, complete direct reference coverage.")
            elif unused:
                st.caption("Declared columns with no known direct references in analyzed sources. This does not establish that they are unused in the live system.")
                copy_names(unused, f"unused_column_names_{w}_{asset}")
            else:
                st.caption("Every declared column has a known direct reference.")
    if rows:
        group = st.segmented_control("Group by", ["All references", "Source file", "Usage type"], default="All references")
        display = [{k: r[k] for k in ["source_table", "column_name", "context", "alias", "relative_path", "start_line", "status", "expression", "schema_source"]} for r in rows]
        if group == "All references":
            st.dataframe(display, hide_index=True, alt="Direct column references", column_config={"column_name": "Column", "source_table": "Source asset", "relative_path": "Source file", "start_line": "Line", "status": "Evidence status"})
        else:
            key = "relative_path" if group == "Source file" else "context"
            for value in sorted({r[key] for r in display}):
                with st.expander(value, expanded=True):
                    st.dataframe([r for r in display if r[key] == value], hide_index=True)
        downloads(display, "column_usage")
        source_viewer(store, list(dict.fromkeys(r["file_id"] for r in rows)), "column_source", rows)
    else:
        st.info("No direct references match the column filter." if terms else "No direct references established for this asset. Ambiguous columns and unsupported dynamic expressions appear in Analysis → Diagnostics.")
