"""Explicit, focused review of current parser diagnostics; never calls a provider on render."""
import streamlit as st

from dataforge.assistance_queue import diagnostic_context, diagnostic_queue, request_review
from dataforge.store import Store
from ui.assistance_result import render_result


def render(store: Store, workspace: str) -> None:
    """Render an explicit, source-bounded review of current parser diagnostics.

    Args:
        store: Workspace storage service.
        workspace: Workspace identifier.
    """
    queue = diagnostic_queue(store, workspace)
    if not queue["items"]:
        st.info("No current SQL/SAS warnings or errors to review. Analyze pending or reimported files first. Informational and CSV diagnostics are excluded.")
        return
    if queue["truncated"]:
        st.warning("Showing the first 100 current diagnostics, with errors first. This list is bounded.")
    st.caption("Choose one parser diagnostic and inspect the exact range before requesting AI. No provider is called automatically. Reviews remain advisory until you explicitly merge grounded relationships.")
    items = {d["diagnostic_id"]: d for d in queue["items"]}
    selection_key = "review_diagnostic_" + workspace
    if st.session_state.get(selection_key) not in items:
        st.session_state.pop(selection_key, None)
    selected = st.selectbox("Diagnostic to review", list(items), key=selection_key,
        format_func=lambda d: f"{items[d]['relative_path']}:{items[d]['line']} [{items[d]['severity']}] {items[d]['message'][:100]}")
    try:
        preview = diagnostic_context(store, workspace, selected)
        source = store.file(preview["file_id"])
        if source["content_hash"] != preview["content_hash"]:
            raise ValueError("Source changed; refresh this review")
        st.text(preview["message"])
        if preview["bounded_context"]:
            st.caption("Suggested nearby context is bounded and may omit part of a statement or SAS block. Adjust the range if needed; runtime constructs can remain unresolved.")
        key = f"review_{workspace}_{selected}_{preview['content_hash']}"
        first = st.number_input("Review start line", 1, preview["line_count"], preview["first"], key=key + "_first")
        last = st.number_input("Review end line", int(first), preview["line_count"], max(int(first), preview["last"]), key=key + "_last")
        code = "\n".join(source["raw_content"].splitlines()[int(first) - 1:int(last)])
        budget = int(store.setting(workspace, "max_context_chars", 8000))
        over_budget = len(code) > budget
        st.code(code[:budget], language="sql" if preview["extension"] == ".sql" else "sas")
        st.caption(f"{preview['relative_path']} · original lines {first}–{last} · {len(code):,} characters · task {preview['task']}. Existing privacy, redaction, profile and context limits apply.")
        if over_budget:
            st.warning("Preview is truncated and sending is disabled. Select fewer lines or increase the source context budget in Security and privacy.")
        configured = bool(store.rows("SELECT 1 FROM llm_profiles WHERE workspace_id=? LIMIT 1", [workspace]))
        if not configured:
            st.info("Configure a default or task-specific provider in Connections & AI to request AI review. This local preview needs no provider.")
        if st.button("Request AI review of this range", disabled=over_budget or not configured, key=key + "_request"):
            try:
                with st.spinner("Reviewing selected diagnostic evidence"):
                    result = request_review(store, workspace, selected, preview["content_hash"], int(first), int(last))
                st.session_state["review_result_" + workspace] = result["record_id"]
            except ValueError as exc:
                st.error(f"Review request failed: {exc}")
            except Exception as exc:
                st.error(f"Review request failed ({type(exc).__name__}). No unvalidated relationships were added.")
    except ValueError as exc:
        st.warning(str(exc))
    render_result(store, workspace, "review_result_" + workspace)
