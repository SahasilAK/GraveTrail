import json

import streamlit as st

from dataforge.services import column_report
from ui.common import choose_asset, context, downloads, load_graph, source_viewer, title

title("Columns", "Columns read directly from an asset. References through downstream tables are excluded.")
store, w = context()
graph = load_graph(store, w)
asset = choose_asset(graph, "columns")
if asset:
    rows = column_report(store, w, asset)
    needle = st.text_input("Filter columns", placeholder="Column name")
    rows = [r for r in rows if needle.casefold() in r["column_name"].casefold()]
    with st.container(horizontal=True):
        st.metric("Known direct columns", len({r["column_name"] for r in rows if r["column_name"] != "*"}), border=True)
        st.metric("Direct references", len(rows), border=True)
        st.metric("Referencing files", len({r["file_id"] for r in rows}), border=True)
    if any(r["column_name"] == "*" for r in rows):
        st.warning("Wildcard coverage is unknown. No columns are invented without a trustworthy schema.")
    metadata = json.loads(graph.nodes[asset].get("metadata", "{}"))
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
        st.info("No direct references established for this asset. Ambiguous columns and unsupported dynamic expressions appear in Analysis → Diagnostics.")
