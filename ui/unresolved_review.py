"""Explicit, focused review of current parser diagnostics; never calls a provider on render."""
import streamlit as st

from dataforge.assistance_queue import diagnostic_context, diagnostic_queue, preview_review, request_review
from dataforge.store import Store
from ui.assistance_result import render_budget, render_result


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
        prepared = preview_review(store, workspace, selected, int(first), int(last))
        budget = prepared['budget']
        st.code(prepared['code'], language="sql" if preview["extension"] == ".sql" else "sas")
        st.caption(f"{preview['relative_path']} · original lines {first}–{last} · {len(code):,} source characters · task {preview['task']}.")
        render_budget(budget)
        if st.button("Request AI review of this range", disabled=not budget['fits'], key=key + "_request"):
            try:
                with st.spinner("Reviewing selected diagnostic evidence", show_time=True):
                    result = request_review(store, workspace, selected, preview["content_hash"], int(first), int(last),
                                            expected_job=prepared['job_id'], expected_request=prepared['request_fingerprint'])
                if result['record_id']:
                    st.session_state["review_result_" + workspace] = result["record_id"]
                else:
                    st.warning(result['failure']['message'])
            except ValueError as exc:
                st.error(f"Review request failed: {exc}")
            except Exception as exc:
                st.error(f"Review request failed ({type(exc).__name__}). No unvalidated relationships were added.")
    except ValueError as exc:
        st.warning(str(exc))
    render_result(store, workspace, "review_result_" + workspace)
