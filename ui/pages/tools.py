import json

import streamlit as st

from dataforge.reporting import code_matches, data_dictionary
from dataforge.services import compare_runs
from ui.common import choose_asset, context, downloads, load_graph, source_viewer, title

title("Engineering tools", "Search code, inspect schemas, compare runs and assess downstream impact.")
store, w = context()
mode = st.segmented_control("Tool", ["Code search", "Data dictionary", "Impact analysis", "Run comparison"], default="Code search")
if mode == "Code search":
    query = st.text_input("Find text in imported source", placeholder="Table, column, procedure or keyword")
    if query:
        results = code_matches(store, w, query, 1000)
        st.caption(f"{len(results)} results (maximum 1,000). CSV values are excluded from code search.")
        st.dataframe(results, hide_index=True)
        downloads(results, "code_search", include_html=False)
        source_viewer(store, list(dict.fromkeys(r["file_id"] for r in results)), "search_source")
elif mode == "Data dictionary":
    query = st.text_input("Filter dictionary")
    rows = data_dictionary(store, w, query)
    st.dataframe(rows, hide_index=True)
    downloads(rows, "data_dictionary")
elif mode == "Impact analysis":
    graph = load_graph(store, w)
    asset = choose_asset(graph, "impact")
    if asset:
        depth = st.slider("Impact depth", 1, 30, 10)
        focused = graph.focus(asset, "downstream", depth, 1000)
        st.metric("Potentially affected assets", len(focused.nodes) - 1)
        st.caption("Static dependency impact; this does not establish runtime execution or data changes.")
        rows = focused.lineage_rows()
        st.dataframe(rows, hide_index=True)
        downloads(rows, "impact")
        if focused.truncated:
            st.warning("Impact report reached the 1,000 asset limit. Explore a narrower subgraph.")
else:
    runs = [r for r in store.runs(w) if r["status"] == "completed"]
    if len(runs) < 2:
        st.info("Complete at least two analysis runs to compare workspace changes.")
    else:
        options = {r["run_id"]: r for r in runs}
        def fmt(k):
            return f"{options[k]['created_at']} ({k[:8]})"
        before = st.selectbox("Baseline run", list(options), index=1, format_func=fmt)
        after = st.selectbox("Comparison run", list(options), format_func=fmt)
        result = compare_runs(options[before], options[after])
        st.json(result)
        st.download_button("Download comparison", json.dumps(result, indent=2), "comparison.json", "application/json")
