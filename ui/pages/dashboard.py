import streamlit as st

from dataforge.ingestion import Importer, Limits
from dataforge.services import analyze
from ui.common import ROOT, context, load_graph, title
from ui.lineage_navigation import focus_asset
from ui.presentation import empty_state

title("Overview", "A clear view of your sources, their dependencies and the evidence between them.")
store, w = context()
files, assets, edges = store.files(w), store.assets(w), store.edges(w)
pending = sum(f["parsing_status"] == "pending" for f in files)
if not files:
    empty_state("Every dependency has a story. Start with your sources.",
                "Try a sample project or import your own SQL, SAS, CSV or dbt sources.")
    st.caption("The SQL example adds a synthetic project to this empty workspace, runs local analysis, and opens its lineage graph.")
    if st.button("Run SQL example", icon=":material/play_arrow:", type="primary"):
        try:
            with st.spinner("Importing and analyzing the SQL example…", show_time=True):
                archive = ROOT / "tests/sample_data/dataforge_sql_lineage_test_project.zip"
                limits = Limits(max_file_bytes=int(store.setting(w, "max_file_mb", 20)) * 1024 * 1024,
                                max_files=int(store.setting(w, "max_files", 10000)))
                with store.lock:
                    if store.files(w):
                        st.rerun()
                    report = Importer(store, w, limits=limits).zip(archive.read_bytes(), {".sql"}, sql_dialect="")
                    if report.diagnostics or not report.accepted:
                        raise ValueError("The example import was incomplete. Review the workspace import limits.")
                    sample_ids = [source["file_id"] for source in store.files(w)]
                analyze(store, w, sample_ids)
                asset = next((a for a in store.assets(w) if a["name"] == "pub.all_kpis"), None)
                if asset is None:
                    raise ValueError("Analysis did not find pub.all_kpis. Review the analysis diagnostics.")
        except Exception as exc:
            st.error(f"Could not open the SQL example: {exc}")
            if store.files(w):
                st.page_link("ui/pages/analysis.py", label="Continue in Analysis", icon=":material/play_circle:")
        else:
            focus_asset(st.session_state, w, asset["asset_id"], asset["name"])
            st.session_state[f"graph_direction_{w}"] = "upstream"
            st.session_state[f"graph_depth_{w}"] = 30
            st.switch_page("ui/pages/explorer.py")
    st.page_link("ui/pages/builder.py", label="Import sources", icon=":material/upload_file:")
    with st.expander("Why GraveTrail?"):
        st.write("Use GraveTrail when the evidence you have is a folder of scripts. It builds lineage across files and links each relationship to its original statement. Local analysis needs no warehouse connection or AI provider.")
        st.write("Unity Catalog captures lineage from supported Databricks workloads. SQL parsers such as SQLGlot provide building blocks for code analysis. GraveTrail uses SQLGlot and adds a project workspace for tracing and reviewing the evidence.")
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
