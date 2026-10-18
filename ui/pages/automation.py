import streamlit as st

from ui.agent_settings import render
from ui.common import context, title

title("Automation & access", "Give your tools explicit, bounded access to this workspace.")
store, w = context()
if notice := st.session_state.pop("settings_notice_" + w, None):
    st.success(notice)
render(store, w)
