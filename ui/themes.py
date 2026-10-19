"""Native Streamlit theme picker over shared, non-UI theme configuration."""
import os
import time
from pathlib import Path

from dataforge.theme_configuration import PALETTES as PALETTES
from dataforge.theme_configuration import PRESET_DESCRIPTIONS
from dataforge.theme_configuration import PRESETS as PRESETS
from dataforge.theme_configuration import apply_preset as apply_preset
from dataforge.theme_configuration import current_preset as current_preset

CONFIG_PATH = Path(os.environ.get('DATAFORGE_THEME_CONFIG', str(Path(__file__).resolve().parents[1] / '.streamlit/config.toml')))

def _loaded_preset():
    import streamlit as st

    return next((name for name, values in PRESETS.items() if all(
        all(st.get_option(f"theme.sidebar.{k}") == v for k, v in value.items()) if key == "sidebar"
        else st.get_option(f"theme.{key}") == value for key, value in values.items())), None)


def render_theme_picker():
    import streamlit as st

    st.subheader("Color theme")
    try:
        active = current_preset(CONFIG_PATH)
        if st.session_state.pop("theme_reload_needed", False):
            st.warning("Theme saved. Refresh this page to reload its appearance; startup theme overrides may take precedence.")
        if pending := st.session_state.get("theme_pending"):
            # Config watching is asynchronous; rerun only after native colors have loaded.
            @st.fragment(run_every=.5)
            def wait_for_theme():
                if _loaded_preset() == pending[0]:
                    st.session_state.pop("theme_pending", None)
                    st.session_state["theme_notice"] = f"{pending[0]} theme applied"
                    st.rerun()
                elif time.monotonic() - pending[1] > 10:
                    st.session_state.pop("theme_pending", None)
                    st.session_state["theme_reload_needed"] = True
                    st.rerun()
                st.caption("Applying the saved theme…")
            wait_for_theme()
        if notice := st.session_state.pop("theme_notice", None):
            st.success(notice)
        choices = list(PRESETS)
        selected = st.selectbox("Theme preset", choices, index=choices.index(active) if active else 0)
        if description := PRESET_DESCRIPTIONS.get(selected):
            st.caption(description)
        st.caption("11 themes, including the original Ocean dark and Ink dark. Choose Apply theme to change this local app's appearance across workspaces.")
        if active is None:
            st.caption("Current palette is customized. Applying a preset replaces its colors and appearance; custom layout/sidebar overrides remain.")
        if st.button("Apply theme", disabled=selected is None or selected == active):
            apply_preset(CONFIG_PATH, selected)
            st.session_state["theme_pending"] = (selected, time.monotonic())
            st.rerun()
    except (OSError, ValueError):
        st.error("Theme configuration could not be updated. The app's .streamlit/config.toml must be valid and writable; the previous file is retained if saving fails.")
