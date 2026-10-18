import streamlit as st

from ui.common import context, load_graph, title
from ui.presentation import empty_state

title("Overview", "A clear view of your sources, their dependencies and the evidence between them.")
store, w = context()
files, assets, edges = store.files(w), store.assets(w), store.edges(w)
pending = sum(f["parsing_status"] == "pending" for f in files)
if not files:
    empty_state("Every dependency has a story. Start with your sources.",
                "Import your SQL, SAS or CSV project. Trace what feeds each table, follow its impact and keep the original proof.")
    st.page_link("ui/pages/builder.py", label="Import sources", icon=":material/upload_file:")
    st.caption("01 Import sources   /   02 Run analysis   /   03 Follow the evidence")
else:
    with st.container(border=True, key="overview_next"):
        if pending:
            st.badge(f"{pending:,} files pending", icon=":material/schedule:", color="orange")
            st.subheader("Your sources are ready for a fresh look.")
            st.write("Run analysis to bring new and changed files into your dependency graph.")
            st.page_link("ui/pages/analysis.py", label="Open Analysis", icon=":material/play_circle:")
        else:
            st.badge("Analysis available", icon=":material/check_circle:", color="green")
            st.subheader("Follow a dependency. Find the proof.")
            st.write("Explore the relationships in this workspace, from the big picture to the exact source statement.")
            st.page_link("ui/pages/explorer.py", label="Explore lineage", icon=":material/arrow_forward:")
    with st.container(horizontal=True):
        st.metric("Source files", len(files), border=True)
        st.metric("Data assets", len(assets), border=True)
        st.metric("Dependencies", len(edges), border=True)
        st.metric("Diagnostics", len(store.diagnostics(w)), border=True)
    graph = load_graph(store, w)
    with st.container(horizontal=True, gap="large"):
        with st.container(width=640):
            st.subheader("Where dependencies meet")
            st.caption("The most connected assets are useful starting points for an investigation.")
            hotspots = sorted([{"Asset": a["name"], "Connections": graph.graph.degree(n),
                                "Downstream": graph.graph.out_degree(n)} for n, a in graph.nodes(data=True)],
                               key=lambda x: x["Connections"], reverse=True)
            st.dataframe(hotspots[:8], hide_index=True, alt="Most connected workspace assets")
        with st.container(width=360, border=True):
            st.subheader("Workspace health", icon=":material/monitor_heart:")
            success = sum(f["parsing_status"] == "success" for f in files)
            st.write(f"**{success:,} of {len(files):,}** files parsed without warnings")
            cycles = graph.cycles()
            st.write(f"**{sum(graph.graph.degree(n) == 0 for n in graph.nodes):,}** isolated assets")
            st.write(f"**{len(cycles):,}** cyclic dependency groups")
            st.write(f"**{sum(a['temporary'] for a in assets):,}** temporary assets")
            if cycles:
                st.warning("Cycles are present. Exploration stays bounded and cycle safe.")
            st.page_link("ui/pages/analysis.py", label="Review analysis", icon=":material/fact_check:")
    st.subheader("Recent work")
    runs = store.runs(w)[:5]
    if runs:
        st.dataframe([{k: r[k] for k in ["created_at", "status", "analyzed", "cached", "duration"]} for r in runs],
                     hide_index=True, column_config={"created_at": "Started", "status": "Status", "analyzed": "Parsed files",
                     "cached": "Reused files", "duration": st.column_config.NumberColumn("Seconds", format="%.2f")}, alt="Latest analysis runs")
    else:
        st.caption("Your first analysis will appear here.")
