import streamlit as st

from dataforge.services import column_report
from ui.common import choose_asset, context, downloads, load_graph, source_viewer, title

title("Direct column usage", "Columns read directly from an asset. References through downstream tables are excluded.")
store, w = context()
graph = load_graph(store, w)
asset = choose_asset(graph, "columns")
if asset:
    rows = column_report(store, w, asset)
    needle = st.text_input("Filter columns", placeholder="Column name")
    rows = [r for r in rows if needle.casefold() in r["column_name"].casefold()]
    with st.container(horizontal=True):
        st.metric("Unique explicit columns", len({r["column_name"] for r in rows if r["column_name"] != "*"}), border=True)
        st.metric("Direct references", len(rows), border=True)
        st.metric("Referencing files", len({r["file_id"] for r in rows}), border=True)
    if any(r["column_name"] == "*" for r in rows):
        st.warning("Wildcard coverage is unknown. No columns are invented without a trustworthy schema.")
    if rows:
        group = st.segmented_control("Group by", ["All references", "Source file", "Usage type"], default="All references")
        display = [{k: r[k] for k in ["source_table", "column_name", "context", "alias", "relative_path", "start_line", "status", "expression"]} for r in rows]
        if group == "All references":
            st.dataframe(display, hide_index=True)
        else:
            key = "relative_path" if group == "Source file" else "context"
            for value in sorted({r[key] for r in display}):
                with st.expander(value, expanded=True):
                    st.dataframe([r for r in display if r[key] == value], hide_index=True)
        downloads(display, "column_usage")
        source_viewer(store, list(dict.fromkeys(r["file_id"] for r in rows)), "column_source", rows)
    else:
        st.info("No direct references established for this asset. Ambiguous columns and unsupported dynamic expressions appear in Builder diagnostics.")
