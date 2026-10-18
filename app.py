"""Run with: streamlit run app.py"""
import duckdb
import streamlit as st

from dataforge.connections import RuntimeConnections, connection_scope
from dataforge.logging_config import configure_logging
from ui.common import current_home, get_store

configure_logging()
st.set_page_config(page_title="GraveTrail | Engineering workspace", page_icon=":material/account_tree:", layout="wide")
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
with st.sidebar:
    st.header(":material/account_tree: GraveTrail")
    st.caption("Evidence behind every dependency")
    options = {w["workspace_id"]: w["name"] for w in workspaces}
    st.selectbox("Active workspace", list(options), format_func=options.get, key="workspace")
    st.badge("Local workspace", icon=":material/lock:")
    with st.expander("New workspace"):
        with st.form("new_workspace"):
            name = st.text_input("Workspace name")
            description = st.text_input("Description")
            if st.form_submit_button("Create workspace"):
                try:
                    store.create_workspace(name, description)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
pages = {
    "Workspace": [st.Page("ui/pages/dashboard.py", title="Dashboard", icon=":material/space_dashboard:", default=True),
                  st.Page("ui/pages/builder.py", title="Lineage builder", icon=":material/add_box:"),
                  st.Page("ui/pages/explorer.py", title="Lineage explorer", icon=":material/account_tree:"),
                  st.Page("ui/pages/columns.py", title="Column usage", icon=":material/view_column:")],
    "Productivity": [st.Page("ui/pages/tools.py", title="Engineering tools", icon=":material/build:")],
    "Configuration": [st.Page("ui/pages/settings.py", title="Settings", icon=":material/settings:")],
}
st.session_state.setdefault('runtime_connections', RuntimeConnections())
with connection_scope(st.session_state['runtime_connections']):
    st.navigation(pages).run()
