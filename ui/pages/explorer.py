import json

import streamlit as st

from dataforge.exports import graph_data, graph_html, source_bundle
from ui.common import choose_asset, context, downloads, graph_view, load_graph, source_viewer, title

title("Lineage explorer", "Trace upstream inputs, downstream impact and the source evidence behind each relationship.")
store, w = context()
graph = load_graph(store, w)
asset = choose_asset(graph, "lineage")
if asset:
    upstream, downstream = st.tabs(["Upstream dependencies", "Downstream dependencies"])
    # Selection also allows a combined graph without losing either principal tab.
    direction = st.segmented_control("Graph direction", ["upstream", "downstream", "combined"], default="upstream")
    with st.container(horizontal=True):
        depth = st.slider("Traversal depth", 1, 30, int(store.setting(w, "traversal_depth", 5)))
        simplified = st.toggle("Collapse temporary steps", value=True)
    view_graph = graph.simplified(keep=[asset]) if simplified else graph
    limit = int(store.setting(w, "graph_limit", 150))

    def tree(node, direction, level=0, seen=None, budget=None):
        seen, budget = set() if seen is None else seen, [60] if budget is None else budget
        if budget[0] <= 0:
            st.caption("Tree display limit reached. Use focused graph or a smaller depth.")
            return
        if node in seen:
            st.caption(f"Cycle returns to {view_graph.nodes[node]['name']}")
            return
        seen = seen | {node}
        neighbors = list(view_graph.graph.predecessors(node) if direction == "upstream" else view_graph.graph.successors(node))
        for n in neighbors:
            if budget[0] <= 0:
                break
            budget[0] -= 1
            edge = view_graph.graph[n][node] if direction == "upstream" else view_graph.graph[node][n]
            label = view_graph.nodes[n]["name"]
            with st.expander(f"{label} • {len(edge['evidence'])} evidence records", expanded=level < 1):
                st.caption(", ".join(dict.fromkeys(e.get("kind", "") + " [" + e.get("status", "") + "]" for e in edge["evidence"])))
                if level + 1 < min(depth, 8):
                    tree(n, direction, level + 1, seen, budget)

    for tab, d in [(upstream, "upstream"), (downstream, "downstream")]:
        with tab:
            tree(asset, d)
    focused = view_graph.focus(asset, direction, depth, limit)
    if focused.truncated:
        st.warning(f"Graph limited to {limit} assets. Reduce depth or focus another asset.")
    if focused.cycles():
        st.warning("Cyclic dependencies are present in this view. Tree expansion stops at repeated nodes.")
    result = graph_view(focused, "lineage_graph")
    rows = focused.lineage_rows()
    selection = result.selection
    evidence = [e for _, _, a in focused.graph.edges(data=True) for e in a["evidence"]]
    if selection and "edge" in selection:
        edge_list = list(focused.graph.edges(data=True))
        if 0 <= selection["edge"] < len(edge_list):
            evidence = edge_list[selection["edge"]][2]["evidence"]
    elif selection and selection.get("node") in focused.nodes:
        node = selection["node"]
        evidence = [e for s, t, a in focused.graph.edges(data=True) if node in {s, t} for e in a["evidence"]]
    left, right = st.columns([1, 1])
    with left:
        st.subheader("Step-wise lineage")
        st.caption("Dependency-based logical ordering. Source execution order is unknown.")
        st.dataframe([{k: v for k, v in r.items() if k not in {"file_id", "statement_id"}} for r in rows], hide_index=True)
        downloads(rows, "lineage_" + direction, include_html=False)
        with st.expander("Root-to-target paths"):
            for path in focused.root_paths(asset):
                st.text(" → ".join(focused.nodes[n]["name"] for n in path))
        with st.container(horizontal=True):
            st.download_button("Download offline graph", graph_html(focused), "lineage.html", "text/html")
            st.download_button("Download graph JSON", json.dumps(graph_data(focused), default=str, indent=2), "graph.json", "application/json")
            ids = list(dict.fromkeys(e["file_id"] for e in evidence))
            if ids:
                st.download_button("Download relevant sources", source_bundle(store, ids), "sources.zip", "application/zip")
    with right:
        st.subheader("Source evidence")
        source_viewer(store, list(dict.fromkeys(e["file_id"] for e in evidence)), "lineage_source", evidence)
