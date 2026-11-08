"""Workspace launch cards and an overview of current lineage evidence."""
from html import escape

import streamlit as st

from dataforge.ingestion import Importer, Limits
from dataforge.lineage_builder import load_builder
from dataforge.services import analyze
from ui.common import ROOT, context, load_graph, title
from ui.lineage_navigation import focus_asset


def _page_button(label, page, icon, *, width="content"):
    if st.button(label, icon=icon, type="primary", width=width):
        st.switch_page(page)


def _run_sql_example(store, workspace):
    try:
        with st.spinner("Importing and analyzing the SQL example…", show_time=True):
            archive = ROOT / "tests/sample_data/dataforge_sql_lineage_test_project.zip"
            limits = Limits(max_file_bytes=int(store.setting(workspace, "max_file_mb", 20)) * 1024 * 1024,
                            max_files=int(store.setting(workspace, "max_files", 10000)))
            with store.lock:
                if store.files(workspace):
                    st.rerun()
                report = Importer(store, workspace, limits=limits).zip(archive.read_bytes(), {".sql"}, sql_dialect="")
                if report.diagnostics or not report.accepted:
                    raise ValueError("The example import was incomplete. Review the workspace import limits.")
                sample_ids = [source["file_id"] for source in store.files(workspace)]
            analyze(store, workspace, sample_ids)
            asset = next((a for a in store.assets(workspace) if a["name"] == "pub.all_kpis"), None)
            if asset is None:
                raise ValueError("Analysis did not find pub.all_kpis. Review the analysis diagnostics.")
    except Exception as exc:
        st.error(f"Could not open the SQL example: {exc}")
        if store.files(workspace):
            _page_button("Continue in Analysis", "ui/pages/analysis.py", ":material/play_circle:")
    else:
        focus_asset(st.session_state, workspace, asset["asset_id"], asset["name"])
        st.session_state[f"graph_direction_{workspace}"] = "upstream"
        st.session_state[f"graph_depth_{workspace}"] = 30
        st.switch_page("ui/pages/explorer.py")


title("Overview", "Build a lineage, trace your own sources, or try the SQL example.")
store, w = context()
files = store.files(w)
pending = sum(f["parsing_status"] == "pending" for f in files)
design = load_builder(store, w) if not files else None

with st.container(border=True, key="overview_hero"):
    intro, illustration = st.columns([3, 2], gap="medium", vertical_alignment="center")
    with intro:
        if pending:
            st.badge(f"{pending:,} files pending", icon=":material/schedule:", color="orange")
            st.subheader("Your sources are ready to analyze")
            st.write("Build table and column lineage from your imported files. Then follow each dependency back to its source statement.")
            _page_button("Open Analysis", "ui/pages/analysis.py", ":material/play_circle:")
        elif files:
            st.badge("Analysis available", icon=":material/check_circle:", color="green")
            st.subheader("Explore your workspace lineage")
            st.write("Trace what feeds a table, see where its columns go, and inspect the source statements behind each relationship.")
            _page_button("Explore lineage", "ui/pages/explorer.py", ":material/arrow_forward:")
        elif design and design.tables:
            st.badge("Design in progress", icon=":material/account_tree:", color="blue")
            st.subheader("Pick up your lineage design")
            st.write(f"Your Lineage Builder catalog has **{len(design.tables):,}** tables. Continue arranging tables and connecting their columns.")
            _page_button("Resume design", "ui/pages/lineage_builder.py", ":material/account_tree:")
        else:
            st.badge("New workspace", icon=":material/space_dashboard:", color="blue")
            st.subheader("Understand how your data moves")
            st.write("GraveTrail maps table and column dependencies from SQL, SAS, and dbt projects. Follow the graph back to the source statements behind it.")
            st.caption("Local analysis works from your files. It needs no warehouse connection.")
    with illustration:
        accent = escape(st.get_option("theme.primaryColor") or "#ed6265")
        surface = escape(st.get_option("theme.secondaryBackgroundColor") or "#263142")
        ink = escape(st.get_option("theme.textColor") or "#eef1f5")
        border = escape(st.get_option("theme.borderColor") or "#556479")
        st.image(f"""
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 146">
              <g fill="none" stroke="{accent}" stroke-width="2" stroke-linecap="round">
                <path d="M103 42 C129 42 116 73 145 73 M103 104 C129 104 116 73 145 73 M225 73 C247 73 248 73 266 73"/>
                <path d="M259 68 L266 73 L259 78"/>
              </g>
              <g fill="{surface}" stroke="{border}">
                <rect x="11" y="24" width="92" height="36" rx="10"/>
                <rect x="11" y="86" width="92" height="36" rx="10"/>
                <rect x="145" y="53" width="80" height="40" rx="10"/>
                <rect x="266" y="53" width="82" height="40" rx="10" stroke="{accent}"/>
              </g>
              <g fill="{ink}" text-anchor="middle" font-family="system-ui" font-size="12" font-weight="600">
                <text x="57" y="46">Sources</text><text x="57" y="108">Schemas</text>
                <text x="185" y="77">Transform</text><text x="307" y="77">Output</text>
              </g>
              <g fill="{accent}">
                <circle cx="103" cy="42" r="3"/><circle cx="103" cy="104" r="3"/><circle cx="225" cy="73" r="3"/>
              </g>
            </svg>
        """.strip(), width="stretch")

if files:
    graph = load_graph(store, w)
    counts = store.rows("""SELECT
        (SELECT count(*) FROM assets WHERE workspace_id=?) AS assets,
        (SELECT count(*) FROM edges WHERE workspace_id=?) AS edges,
        (SELECT count(*) FROM diagnostics WHERE workspace_id=?) AS diagnostics""", [w, w, w])[0]
    with st.container(horizontal=True, key="overview_metrics"):
        st.metric("Source files", len(files), border=True)
        st.metric("Data assets", counts["assets"], border=True)
        st.metric("Dependencies", counts["edges"], border=True)
        st.metric("Diagnostics", counts["diagnostics"], border=True)

st.subheader("Workspace tools" if files or (design and design.tables) else "Choose a starting point")
with st.container(key="overview_actions"):
    build, sources, trace = st.columns(3, gap="medium", border=True)
    with build:
        st.subheader("Design a lineage", icon=":material/account_tree:")
        st.write("Lay out tables and connect their columns on a canvas.")
        _page_button("Open Lineage Builder", "ui/pages/lineage_builder.py", ":material/arrow_forward:", width="stretch")
    with sources:
        st.subheader("Trace your files", icon=":material/folder_open:")
        st.write("Import a ZIP, folder, or dbt project. Run Analysis to explore its dependencies.")
        _page_button("Import sources", "ui/pages/builder.py", ":material/arrow_forward:", width="stretch")
    with trace:
        if not files:
            st.subheader("Try the example", icon=":material/experiment:")
            st.write("Load a bundled SQL project and open its analyzed lineage graph.")
            if st.button("Run SQL example", icon=":material/play_arrow:", type="primary", width="stretch"):
                _run_sql_example(store, w)
        elif counts["assets"]:
            st.subheader("Follow a column", icon=":material/view_column:")
            st.write("See where a column comes from and which transformations use it.")
            _page_button("Open Columns", "ui/pages/columns.py", ":material/arrow_forward:", width="stretch")
        else:
            st.subheader("Analyze your sources", icon=":material/play_circle:")
            st.write("Process your inventory to build table and column lineage.")
            _page_button("Analyze files", "ui/pages/analysis.py", ":material/arrow_forward:", width="stretch")

if files:
    connected, health = st.columns([2, 1], gap="medium", border=True)
    with connected:
        st.subheader("Most connected assets", icon=":material/hub:")
        st.caption("Start here when you want to see where a change could have the widest impact.")
        hotspots = sorted([{"Asset": a["name"], "Connections": graph.graph.degree(n),
                            "Downstream": graph.graph.out_degree(n)} for n, a in graph.nodes(data=True)],
                           key=lambda x: x["Connections"], reverse=True)
        if hotspots:
            st.dataframe(hotspots[:8], hide_index=True, alt="Most connected workspace assets")
        else:
            st.caption("Assets will appear here after analysis.")
    with health:
        st.subheader("Workspace health", icon=":material/monitor_heart:")
        success = sum(f["parsing_status"] == "success" for f in files)
        st.write(f"**{success:,} of {len(files):,}** files parsed without warnings")
        cycles = graph.cycles()
        st.write(f"**{sum(graph.graph.degree(n) == 0 for n in graph.nodes):,}** isolated assets")
        st.write(f"**{len(cycles):,}** cyclic dependency groups")
        st.write(f"**{sum(a['temporary'] for a in graph.nodes.values()):,}** temporary assets")
        if cycles:
            st.warning("Cycles are present. Exploration stays bounded and cycle safe.")
        _page_button("Review analysis", "ui/pages/analysis.py", ":material/fact_check:")
    with st.container(border=True, key="overview_recent"):
        st.subheader("Recent analysis", icon=":material/history:")
        runs = store.rows("""SELECT created_at,status,analyzed,cached,duration FROM analysis_runs
                             WHERE workspace_id=? ORDER BY created_at DESC LIMIT 5""", [w])
        if runs:
            st.dataframe(runs, hide_index=True, column_config={"created_at": "Started", "status": "Status",
                "analyzed": "Parsed files", "cached": "Reused files",
                "duration": st.column_config.NumberColumn("Seconds", format="%.2f")}, alt="Latest analysis runs")
        else:
            st.caption("Your first analysis will appear here.")

with st.container(horizontal=True, vertical_alignment="center", key="overview_footer"):
    st.caption("Read the documentation or browse the open-source project.")
    st.link_button("Documentation", "https://sahasilak.github.io/GraveTrail/",
                   icon=":material/menu_book:", type="primary")
    st.link_button("View on GitHub", "https://github.com/SahasilAK/GraveTrail",
                   icon=":material/open_in_new:", type="primary")
