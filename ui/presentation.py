"""Small, theme-derived presentation helpers for the native Streamlit shell."""
from base64 import b64encode
from functools import lru_cache
from html import escape
from pathlib import Path

import streamlit as st

from dataforge.store import Store
from dataforge.theme_configuration import PALETTES, hover_accent, on_accent

ICON_PATH = Path(__file__).with_name("icon.png")


@lru_cache(maxsize=1)
def _icon_uri() -> str:
    """Return the app icon as an inline PNG data URI.

    Returns:
        Base64 data URI for the app icon.
    """
    return "data:image/png;base64," + b64encode(ICON_PATH.read_bytes()).decode("ascii")


def brand_title() -> str:
    """Build the theme-aware branded title displayed in the sidebar.

    Returns:
        Streamlit Markdown for the app icon and title.
    """
    color = st.get_option("theme.linkColor") or st.get_option("theme.primaryColor") or "currentColor"
    return f'![GraveTrail icon]({_icon_uri()}) Grave:color[Trail]{{foreground="{color}"}}'


def apply_style() -> None:
    """Apply theme-derived CSS variables and the shared presentation stylesheet."""
    from ui.themes import _loaded_preset

    colors = {name: st.get_option("theme." + option) for name, option in {
        "bg": "backgroundColor", "surface": "secondaryBackgroundColor", "text": "textColor",
        "accent": "primaryColor", "border": "borderColor", "link": "linkColor",
    }.items()}
    tokens = ";".join(f"--gt-{key}:{value}" for key, value in colors.items() if value)
    extra = ""
    if palette := PALETTES.get(_loaded_preset()):
        tokens += f';--gt-muted:{palette["muted"]};--gt-on-accent:{on_accent(palette["accent"])}'
        tokens += f';--gt-accent-hover:{hover_accent(palette["accent"])}'
        extra = """
        button[kind^="primary"],button[kind^="primary"] p {color:var(--gt-on-accent)}
        button[kind^="primary"]:hover {background:var(--gt-accent-hover)}
        .st-key-app_workspace [data-testid="stCaptionContainer"],
        [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {color:var(--gt-muted);opacity:1}
        .gt-eyebrow {color:var(--gt-muted);opacity:1}
        .st-key-empty_state,.st-key-overview_next {background:var(--gt-surface)}
        """
    st.html("<style>:root{" + tokens + "}" + Path(__file__).with_name("style.css").read_text() + extra + "</style>")


def eyebrow(text: str) -> None:
    """Render a small escaped eyebrow label.

    Args:
        text: Label text displayed above a section.
    """
    st.html(f'<div class="gt-eyebrow">{escape(text)}</div>')


def empty_state(title: str, description: str, icon: str = ":material/folder_open:") -> None:
    """Render a bordered empty-state panel.

    Args:
        title: Empty-state heading.
        description: Supporting explanation or next step.
        icon: Streamlit Material icon name for the heading.
    """
    with st.container(border=True, key="empty_state"):
        st.subheader(title, icon=icon)
        st.write(description)


def section(label: str, options: list[str], key: str, default: str | None = None) -> str | None:
    """Render a small session-persisted selector for locally switching view bodies.

    Args:
        label: Accessible selector label.
        options: Choices shown to the user.
        key: Unique Streamlit widget key.
        default: Initially selected choice, if supplied.

    Returns:
        The selected option, or ``None`` when the control has no selection.
    """
    return st.segmented_control(label, options, default=default or options[0], key=key,
                                persist_state="session", selection_mode="single")


def sync_context(store: Store, workspace: str) -> None:
    """Drop transient evidence and previews when workspace or source versions change.

    Args:
        store: Workspace storage service.
        workspace: Active workspace identifier.
    """
    revisions = store.rows("SELECT file_id,content_hash FROM source_files WHERE workspace_id=? ORDER BY file_id",
                           [workspace])
    signature = (str(store.home), workspace, tuple((r["file_id"], r["content_hash"]) for r in revisions))
    previous = st.session_state.get("view_context")
    if previous and previous != signature:
        if previous[:2] == signature[:2]:
            st.session_state.pop("lineage_history_" + workspace, None)
        prefixes = ("inventory_source", "lineage_source", "column_source", "schema_source", "search_source",
                    "review_diagnostic_", "diagnostic_source", "lineage_graph_", "tree_", "cleanup_",
                    "import_report_", "analysis_notice_", "settings_notice_", "parsing_notice_", "review_result_")
        for key in list(st.session_state):
            if key.startswith(prefixes) or key in {"workspace_notice", "lineage_direction_tabs", "runtime_secret", "connection_notice"}:
                st.session_state.pop(key, None)
        if previous[:2] != signature[:2]:
            for key in ("asset_search_lineage", "asset_search_columns", "asset_search_impact"):
                st.session_state.pop(key, None)
    st.session_state["view_context"] = signature
