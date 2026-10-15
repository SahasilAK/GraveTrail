"""Run with: streamlit run app.py"""
import logging
import os

import streamlit as st

from ui.common import ROOT, get_store

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
st.set_page_config(page_title="DataForge | Engineering workspace", page_icon=":material/account_tree:", layout="wide")
store = get_store(os.environ.get("DATAFORGE_HOME", str(ROOT / ".dataforge")))
workspaces = store.workspaces()
if not workspaces:
    store.create_workspace("My workspace", "Local engineering workspace")
    workspaces = store.workspaces()
with st.sidebar:
    st.header(":material/account_tree: DataForge")
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
st.navigation(pages).run()
