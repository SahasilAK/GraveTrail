"""Carry entry-point evidence into the active workspace's migration setup."""
import streamlit as st


def migration_link(workspace, label, **entry):
    if st.button(label, icon=":material/conversion_path:"):
        prefix = f"migration_{workspace}_"
        st.session_state[prefix + "entry"] = entry
        st.session_state[prefix + "new"] = True
        st.session_state.pop(prefix + "preflight", None)
        st.switch_page("ui/pages/migration.py")
