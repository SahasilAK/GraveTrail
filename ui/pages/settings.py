import streamlit as st

from ui.common import context, title
from ui.presentation import section
from ui.workspace_settings import render_appearance, render_parsing, render_resources

title("Workspace settings", "Tune parsing, resource budgets and the way you explore evidence.")
store, w = context()
if notice := st.session_state.pop("settings_notice_" + w, None):
    st.success(notice)
mode = section("Workspace preferences", ["Parsing", "Resources", "Appearance"], "workspace_settings_section_" + w)
st.caption("Changes apply only when you save. Leaving a form discards unsaved edits.")
with st.container(key="preferences_body"):
    if mode == "Parsing":
        render_parsing(store, w)
    elif mode == "Resources":
        render_resources(store, w)
    else:
        render_appearance(store, w)
