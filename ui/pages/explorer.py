import json

import streamlit as st

from dataforge.configuration import VisualizationSettings
from dataforge.excel_exports import XLSX_MIME
from dataforge.exports import graph_data, graph_html, path_rows, report_csv, source_bundle
from dataforge.graph_images import png_available
from dataforge.services import export_graph_image, export_lineage_excel
from ui.common import choose_asset, context, downloads, graph_view, load_graph, source_viewer, title
from ui.dbt_sections import render_resources
from ui.lineage_navigation import ALL_ASSETS, focus_asset, move_history, remember_view
from ui.lineage_tree import render_tree
from ui.presentation import section

title("Lineage", "Trace upstream inputs, downstream impact and the source evidence behind each relationship.")
store, w = context()
render_resources(store, w)
graph = load_graph(store, w)
appearance = VisualizationSettings.from_store(store, w)
asset = choose_asset(graph, "lineage", allow_all=True)
if asset:
    all_assets = asset == ALL_ASSETS
    with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
        direction = st.segmented_control("Graph direction", ["upstream", "downstream", "combined"],
                                         default=appearance.graph_direction, key="graph_direction_" + w, persist_state="session", disabled=all_assets, required=True)
        view = section("Lineage view", ["Graph", "Tree"], "lineage_view_" + w) or "Graph"
        with st.popover("Traversal options", icon=":material/tune:"):
            depth = st.slider("Traversal depth", 1, 30, int(store.setting(w, "traversal_depth", 5)), key="graph_depth_" + w, persist_state="session", disabled=all_assets)
            simplified = st.toggle("Collapse temporary steps", value=appearance.collapse_temporary,
                                   key="graph_collapse_" + w, persist_state="session")
    view_graph = graph.simplified(keep=[asset]) if simplified else graph
    limit = int(store.setting(w, "graph_limit", 150))

    focused = view_graph if all_assets else view_graph.focus(asset, direction, depth, limit)
    default_tab = "Downstream dependencies" if appearance.graph_direction == "downstream" else "Upstream dependencies"
    evidence_key = "lineage_evidence_direction_" + w
    active_tab = st.session_state.get("lineage_direction_tabs", st.session_state.get(evidence_key, default_tab))
    # Native tabs are cleaned up while Graph is shown; this non-widget state survives.
    st.session_state[evidence_key] = active_tab
    history = remember_view(st.session_state, w, {"asset": asset, "query": st.session_state.get("asset_search_lineage", ""),
        "direction": direction, "depth": depth, "simplified": simplified, "view": view, "tree_direction": active_tab})
    with st.container(horizontal=True):
        st.button("Back", icon=":material/arrow_back:", disabled=history["index"] <= 0,
                  on_click=move_history, args=(st.session_state, w, -1))
        st.button("Forward", icon=":material/arrow_forward:", disabled=history["index"] >= len(history["entries"]) - 1,
                  on_click=move_history, args=(st.session_state, w, 1))
        with st.popover('Export', icon=':material/download:'):
            st.caption('Entire filtered graph — fit all nodes in the current bounded result, independent of browser pan/zoom.')
            label = 'All filtered assets' if all_assets else focused.nodes[asset]['name']
            st.write(f'{label} · {direction if not all_assets else "all directions"} · depth {depth}')
            st.caption(f'{len(focused.nodes)} nodes · {len(focused.graph.edges)} relationships · temporary steps {"collapsed" if simplified else "included"}')
            st.caption(f'Minimum confidence {store.setting(w, "min_lineage_confidence", 0.):g}; inferred {"included" if store.setting(w, "include_inferred", True) else "excluded"}.')
            image_format = st.selectbox('Image format', ['SVG', 'PNG'] if png_available() else ['SVG'])
            if not png_available():
                st.caption('PNG renderer unavailable; install resvg-py to enable PNG.')
            background = st.selectbox('Image background', ['light', 'dark', 'transparent'])
            scale = st.selectbox('Image scale', [1, 2], format_func=lambda n: 'Normal' if n == 1 else 'High resolution (2×)')
            image_title = st.text_input('Image title', value='GraveTrail lineage', max_chars=200)
            legend = st.checkbox('Include legend', value=True)
            st.caption('Images include asset/workspace business metadata. Raw source code is excluded.')
            if st.button('Prepare graph image'):
                try:
                    image, summary = export_graph_image(store, w, '' if all_assets else asset,
                        direction=direction, max_depth=depth, max_nodes=max(limit, len(focused.nodes)) if all_assets else limit,
                        collapse_temporary=simplified, format=image_format.lower(), appearance=appearance,
                        options={'scale': scale, 'background': background, 'title': image_title, 'legend': legend})
                    for warning in summary['warnings']:
                        st.warning(warning)
                    st.download_button(f'Download {image_format}', image, summary['filename'], summary['mime_type'], on_click='ignore')
                except (ValueError, OSError) as exc:
                    st.error(f'Graph image could not be prepared: {exc}')
    if all_assets and view == "Tree":
        st.info("Choose an exact asset to explore its dependency tree.")
    if focused.truncated and not all_assets:
        st.warning(f"Graph limited to {limit} assets. Reduce depth or focus another asset.")
    if focused.cycles():
        st.warning("Cyclic dependencies are present in this view. Tree expansion stops at repeated nodes.")
    evidence_direction = ("downstream" if active_tab == "Downstream dependencies" else "upstream") if view == "Tree" and not all_assets else direction
    selection = None
    if view == "Graph" or all_assets:
        revision = store.rows("SELECT run_id FROM analysis_runs WHERE workspace_id=? ORDER BY created_at DESC LIMIT 1", [w])
        revision = revision[0]["run_id"] if revision else "empty"
        graph_key = f"lineage_graph_{w}_{asset}_{evidence_direction}_{depth}_{simplified}_{revision}"

        def navigate_graph() -> None:
            """Move the lineage focus to the node requested by the graph."""
            node = st.session_state[graph_key].get("navigate")
            if node in focused.nodes:
                focus_asset(st.session_state, w, node, graph.nodes[node]["name"])

        with st.container(key="graph_surface"):
            result = graph_view(focused, graph_key, appearance, on_navigate=navigate_graph)
        selection = result.selection
        scope = "All assets" if all_assets else f"{direction} · depth {depth}"
        st.caption(f"{len(focused.nodes):,} assets in view · {len(focused.graph.edges):,} relationships · {scope}")
    rows = focused.lineage_rows()
    source_scope = "All assets" if all_assets else evidence_direction.capitalize() + " dependencies"
    tree_focus = focused if all_assets else view_graph.focus(asset, evidence_direction, depth, limit)
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
    if view == "Tree" and not all_assets:
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
        if all_assets:
            st.caption("Choose an exact asset to trace dependency paths.")
        if paths_panel.open and not all_assets:
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
                with st.popover("Export to Excel", icon=":material/table_view:"):
                    st.caption("Steps show data dependencies, not runtime execution order.")
                    st.write(f"Selected asset: {graph.nodes[asset]['name']} · {path_direction} · depth {depth} · up to {path_limit} paths")
                    st.caption("The workbook uses the current graph confidence/inferred filters and a committed analysis revision. Warnings and coverage limits remain visible in the workbook.")
                    include_temporary = st.checkbox("Include temporary stages", value=not simplified)
                    include_evidence = st.checkbox("Include supporting evidence", value=False)
                    include_source_text = st.checkbox("Include raw SQL/SAS excerpts", value=False,
                        disabled=not include_evidence, help="Includes analyzed source text in the Evidence sheet.")
                    relationship_limit = st.number_input("Maximum exported relationships", 1, 20000, 2000)
                    if st.button("Prepare Excel workbook"):
                        try:
                            with st.spinner("Preparing ordered lineage workbook…"):
                                workbook, summary = export_lineage_excel(store, w, asset, direction=path_direction,
                                    max_paths=int(path_limit), max_depth=depth, max_relationships=int(relationship_limit),
                                    collapse_temporary=not include_temporary, include_evidence=include_evidence,
                                    include_source_text=include_evidence and include_source_text)
                            st.caption(f"{summary['path_count']} paths · {summary['segment_count']} segments · {summary['relationship_count']} relationships · revision {summary['revision']}")
                            for warning in summary['warnings']:
                                st.warning(warning)
                            st.download_button("Download Excel workbook", workbook, f"lineage-{w[:8]}.xlsx",
                                               XLSX_MIME, on_click="ignore")
                        except (ValueError, OSError) as exc:
                            st.error(f"Excel export could not be prepared: {exc}")
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
