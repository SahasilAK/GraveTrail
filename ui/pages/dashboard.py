import streamlit as st

from ui.common import context, load_graph, title

title("Workspace overview", "Inventory, analysis health and dependency hotspots in your engineering workspace.")
store, w = context()
files, assets, edges = store.files(w), store.assets(w), store.edges(w)
with st.container(horizontal=True):
    st.metric("Source files", len(files), border=True)
    st.metric("Data assets", len(assets), border=True)
    st.metric("Dependencies", len(edges), border=True)
    st.metric("Diagnostics", len(store.diagnostics(w)), border=True)
if not files:
    st.info("Start with your source code. Import a ZIP, select a folder, or use a host directory in Lineage builder.", title="Build your first lineage workspace")
    st.page_link("ui/pages/builder.py", label="Open lineage builder", icon=":material/add_box:")
else:
    success = sum(f["parsing_status"] == "success" for f in files)
    pending = sum(f["parsing_status"] == "pending" for f in files)
    st.caption(f"{success}/{len(files)} files analyzed without warnings • {pending} pending • every stored edge includes evidence")
    if pending:
        st.warning("Inventory has pending changes. Analyze in Lineage builder to refresh dependencies.")
    graph = load_graph(store, w)
    left, right = st.columns([3, 2])
    with left:
        st.subheader("Dependency hotspots")
        hotspots = sorted([{"Asset": a["name"], "Connections": graph.graph.degree(n),
                            "Downstream": graph.graph.out_degree(n)} for n, a in graph.nodes(data=True)],
                           key=lambda x: x["Connections"], reverse=True)
        st.dataframe(hotspots[:15], hide_index=True)
    with right:
        st.subheader("Workspace health")
        cycles = graph.cycles()
        st.write(f"{sum(graph.graph.degree(n) == 0 for n in graph.nodes)} isolated assets")
        st.write(f"{len(cycles)} cyclic dependency groups")
        st.write(f"{sum(a['temporary'] for a in assets)} temporary assets")
        if cycles:
            st.warning("Cycles are present. Explorer traversal is bounded and cycle safe.")
    st.subheader("Recent analysis runs")
    st.dataframe([{k: r[k] for k in ["run_id", "status", "analyzed", "cached", "duration", "created_at"]}
                  for r in store.runs(w)[:20]], hide_index=True)
