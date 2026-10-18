"""Small, theme-derived presentation helpers for the native Streamlit shell."""
from html import escape
from pathlib import Path

import streamlit as st


def apply_style():
    colors = {name: st.get_option("theme." + option) for name, option in {
        "bg": "backgroundColor", "surface": "secondaryBackgroundColor", "text": "textColor",
        "accent": "primaryColor", "border": "borderColor", "link": "linkColor",
    }.items()}
    tokens = ";".join(f"--gt-{key}:{value}" for key, value in colors.items() if value)
    st.html("<style>:root{" + tokens + "}" + Path(__file__).with_name("style.css").read_text() + "</style>")


def eyebrow(text):
    st.html(f'<div class="gt-eyebrow">{escape(text)}</div>')


def empty_state(title, description, icon=":material/folder_open:"):
    with st.container(border=True, key="empty_state"):
        st.subheader(title, icon=icon)
        st.write(description)


def section(label, options, key, default=None):
    """Short local selectors persist within the session; all bodies are conditional."""
    return st.segmented_control(label, options, default=default or options[0], key=key,
                                persist_state="session", selection_mode="single")


def sync_context(store, workspace):
    """Drop transient evidence and unsafe previews when their owning context changes."""
    revisions = store.rows("SELECT file_id,content_hash FROM source_files WHERE workspace_id=? ORDER BY file_id",
                           [workspace])
    signature = (str(store.home), workspace, tuple((r["file_id"], r["content_hash"]) for r in revisions))
    previous = st.session_state.get("view_context")
    if previous and previous != signature:
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
