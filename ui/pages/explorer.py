import json

import streamlit as st

from dataforge.configuration import VisualizationSettings
from dataforge.exports import graph_data, graph_html, path_rows, report_csv, source_bundle
from ui.common import choose_asset, context, downloads, graph_view, load_graph, source_viewer, title
from ui.lineage_tree import render_tree
from ui.presentation import section

title("Lineage", "Trace upstream inputs, downstream impact and the source evidence behind each relationship.")
store, w = context()
graph = load_graph(store, w)
appearance = VisualizationSettings.from_store(store, w)
asset = choose_asset(graph, "lineage")
if asset:
    with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
        direction = st.segmented_control("Graph direction", ["upstream", "downstream", "combined"],
                                         default=appearance.graph_direction, key="graph_direction_" + w, persist_state="session")
        view = section("Lineage view", ["Graph", "Tree"], "lineage_view_" + w)
        with st.popover("Traversal options", icon=":material/tune:"):
            depth = st.slider("Traversal depth", 1, 30, int(store.setting(w, "traversal_depth", 5)), key="graph_depth_" + w, persist_state="session")
            simplified = st.toggle("Collapse temporary steps", value=appearance.collapse_temporary,
                                   key="graph_collapse_" + w, persist_state="session")
    view_graph = graph.simplified(keep=[asset]) if simplified else graph
    limit = int(store.setting(w, "graph_limit", 150))

    focused = view_graph.focus(asset, direction, depth, limit)
    if focused.truncated:
        st.warning(f"Graph limited to {limit} assets. Reduce depth or focus another asset.")
    if focused.cycles():
        st.warning("Cyclic dependencies are present in this view. Tree expansion stops at repeated nodes.")
    default_tab = "Downstream dependencies" if appearance.graph_direction == "downstream" else "Upstream dependencies"
    evidence_key = "lineage_evidence_direction_" + w
    active_tab = st.session_state.get("lineage_direction_tabs", st.session_state.get(evidence_key, default_tab))
    # Native tabs are cleaned up while Graph is shown; this non-widget state survives.
    st.session_state[evidence_key] = active_tab
    evidence_direction = "downstream" if active_tab == "Downstream dependencies" else "upstream"
    selection = None
    if view == "Graph":
        revision = store.rows("SELECT run_id FROM analysis_runs WHERE workspace_id=? ORDER BY created_at DESC LIMIT 1", [w])
        revision = revision[0]["run_id"] if revision else "empty"
        with st.container(key="graph_surface"):
            result = graph_view(focused, "lineage_graph_" + w + "_" + asset + "_" + evidence_direction + "_" + revision, appearance)
        selection = result.selection
        st.caption(f"{len(focused.nodes):,} assets in view · {len(focused.graph.edges):,} relationships · {direction} · depth {depth}")
    rows = focused.lineage_rows()
    source_scope = active_tab
    tree_focus = view_graph.focus(asset, evidence_direction, depth, limit)
    evidence = [e for _, _, a in tree_focus.graph.edges(data=True) for e in a["evidence"]]
    if selection and "edge" in selection:
        edge_list = list(focused.graph.edges(data=True))
        if 0 <= selection["edge"] < len(edge_list):
            evidence = edge_list[selection["edge"]][2]["evidence"]
            source_scope = "Selected graph relationship"
    elif selection and selection.get("node") in focused.nodes:
        node = selection["node"]
        evidence = [e for s, t, a in focused.graph.edges(data=True) if node in {s, t} for e in a["evidence"]]
        source_scope = "Selected graph asset"
    if view == "Tree":
        upstream, downstream = st.tabs(["Upstream dependencies", "Downstream dependencies"],
                                      default=active_tab, on_change="rerun", key="lineage_direction_tabs")
        for tab, d in [(upstream, "upstream"), (downstream, "downstream")]:
            if tab.open:
                with tab:
                    render_tree(view_graph, asset, d, depth, limit,
                                key=f"tree_{w}_{asset}_{d}_{simplified}",
                                default_expansion=int(store.setting(w, "tree_expansion_depth", 1)))
    with st.container(horizontal=True, gap="large"):
        left = st.container(width=660)
        right = st.container(width=660)
    with left:
        st.subheader("Step-wise lineage")
        st.caption("Dependency-based logical ordering. Source execution order is unknown.")
        st.dataframe([{k: v for k, v in r.items() if k not in {"file_id", "statement_id"}} for r in rows], hide_index=True)
        downloads(rows, "lineage_" + direction, include_html=False)
        paths_panel = st.expander("Dependency paths and exports", on_change="rerun", key="lineage_path_panel")
        if paths_panel.open:
            with paths_panel:
                path_direction = st.segmented_control("Path direction", ["upstream", "downstream"], default="upstream")
                path_limit = st.number_input("Maximum paths", 1, 500, 50)
                report = view_graph.path_report(asset, path_direction, path_limit, depth)
                st.caption("Paths use the selected temporary-step view and traversal depth. Roots/terminals reflect known static dependencies; unresolved constructs may remain. Evidence references original file versions.")
                if report["truncated"]:
                    st.warning("Path/depth limits omit dependencies. This export is a bounded report, not exhaustive lineage.")
                for path in report["paths"]:
                    st.text(" → ".join(path["nodes"]) + " [" + path["boundary"] + "]")
                with st.container(horizontal=True):
                    st.download_button("Download paths JSON", json.dumps(report, default=str, indent=2),
                                       "dependency-paths.json", "application/json")
                    st.download_button("Download paths CSV", report_csv(path_rows(report)),
                                       "dependency-paths.csv", "text/csv")
        with st.popover("Export graph & sources", icon=":material/download:"):
            st.download_button("Download offline graph", lambda: graph_html(focused, appearance), "lineage.html", "text/html")
            st.download_button("Download graph JSON", lambda: json.dumps(graph_data(focused, appearance), default=str, indent=2), "graph.json", "application/json")
            ids = list(dict.fromkeys(e["file_id"] for e in evidence))
            if ids:
                st.download_button("Download relevant sources", lambda: source_bundle(store, ids, {e["file_id"]: e.get("source_hash") for e in evidence}), "sources.zip", "application/zip")
    with right:
        st.subheader("Source evidence")
        st.caption("Source scope: " + source_scope)
        source_viewer(store, list(dict.fromkeys(e["file_id"] for e in evidence)), "lineage_source", evidence)
