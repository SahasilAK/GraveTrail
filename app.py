"""Run with: streamlit run app.py"""
import duckdb
import streamlit as st

from dataforge.connections import RuntimeConnections, connection_scope
from dataforge.logging_config import configure_logging
from ui.common import current_home, get_store
from ui.presentation import ICON_PATH, apply_style, brand_title, eyebrow, sync_context

configure_logging()
st.set_page_config(page_title="GraveTrail | Engineering workspace", page_icon=str(ICON_PATH), layout="wide")
try:
    store = get_store(current_home())
except (ValueError, OSError, duckdb.Error):
    st.error("Cannot open configured storage. Check DATAFORGE_HOME, DATAFORGE_STORAGE_LOCATIONS and database access.")
    st.stop()
if notice := st.session_state.pop("storage_notice", None):
    st.success(notice)
configure_logging(store.setting("__application__", "log_level", "INFO"))
workspaces = store.workspaces()
if not workspaces:
    store.create_workspace("My workspace", "Local engineering workspace")
    workspaces = store.workspaces()

apply_style()

@st.dialog("Create a workspace", icon=":material/create_new_folder:")
def new_workspace() -> None:
    """Collect details and create a workspace from the sidebar dialog."""
    st.caption("Keep related sources, analysis and preferences together.")
    with st.form("new_workspace"):
        name = st.text_input("Workspace name", max_chars=200)
        description = st.text_input("Description", max_chars=2000)
        if st.form_submit_button("Create workspace", type="primary"):
            try:
                identity = store.create_workspace(name, description)
                st.session_state["workspace"] = identity
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

pages = {
    "Workspace": [st.Page("ui/pages/dashboard.py", title="Overview", icon=":material/space_dashboard:", default=True),
                  st.Page("ui/pages/builder.py", title="Sources", icon=":material/folder_open:"),
                  st.Page("ui/pages/analysis.py", title="Analysis", icon=":material/play_circle:"),
                  st.Page("ui/pages/lineage_builder.py", title="Lineage builder", icon=":material/polyline:")],
    "Explore": [st.Page("ui/pages/explorer.py", title="Lineage", icon=":material/account_tree:"),
                st.Page("ui/pages/columns.py", title="Columns", icon=":material/view_column:"),
                st.Page("ui/pages/transformations.py", title="Transformation lineage", icon=":material/route:"),
                st.Page("ui/pages/tools.py", title="Engineering tools", icon=":material/manage_search:")],
    "Administration": [st.Page("ui/pages/settings.py", title="Workspace settings", icon=":material/tune:"),
                       st.Page("ui/pages/connections.py", title="Connections & AI", icon=":material/hub:"),
                       st.Page("ui/pages/management.py", title="Data management", icon=":material/database:"),
                       st.Page("ui/pages/automation.py", title="Automation & access", icon=":material/admin_panel_settings:")],
}
page = st.navigation(pages, position="hidden")
with st.sidebar:
    with st.container(key="brand"):
        st.header(brand_title())
        st.caption("**Nothing stays buried.**  \nEvery dependency leaves a trail.")
    options = {w["workspace_id"]: w["name"] for w in workspaces}
    if st.session_state.get("workspace") not in options:
        st.session_state["workspace"] = next(iter(options))
    with st.container(key="workspace_context"):
        st.selectbox("Active workspace", list(options), format_func=options.get, key="workspace")
        if st.button("New workspace", icon=":material/add:", type="tertiary"):
            new_workspace()
    with st.container(key="sidebar_navigation", gap=None):
        for group, destinations in pages.items():
            eyebrow(group)
            for destination in destinations:
                st.page_link(destination, label=destination.title, icon=destination.icon, width="stretch")
    st.caption(":material/lock: Local storage · source is never executed")

sync_context(store, st.session_state["workspace"])
st.session_state.setdefault("runtime_connections", RuntimeConnections())
with st.container(key="app_workspace"):
    eyebrow("Workspace / " + options[st.session_state["workspace"]])
    with connection_scope(st.session_state["runtime_connections"]):
        page.run()
