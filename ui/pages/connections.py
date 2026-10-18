import streamlit as st

from ui.common import context, title
from ui.presentation import section

title("Connections & AI", "Choose your providers and control exactly what can leave this workspace.")
store, w = context()
if notice := st.session_state.pop("settings_notice_" + w, None):
    st.success(notice)
external = store.setting(w, "external_llm", False)
st.badge("External requests enabled" if external else "External requests disabled", icon=":material/shield:",
         color="orange" if external else "green")
mode = section("Connection settings", ["Providers & routing", "Privacy"], "connections_section_" + w)
with st.container(key="preferences_body"):
    if mode == "Providers & routing":
        from ui.provider_settings import render
        render(store, w)
    else:
        from ui.workspace_settings import render_privacy
        render_privacy(store, w)
