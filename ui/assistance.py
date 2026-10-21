"""Focused, user-triggered AI assistance over imported source evidence."""
import streamlit as st

from dataforge.ai_service import preview_ai_evidence
from dataforge.llm import TASKS, assist_task
from dataforge.store import Store
from ui.assistance_result import render_result


def render(store: Store, workspace: str) -> None:
    """Render the explicit, source-bounded AI assistance workflow.

    Args:
        store: Workspace storage service.
        workspace: Workspace identifier.
    """
    _saved_results(store, workspace)
    profiles = store.rows("SELECT profile_id FROM llm_profiles WHERE workspace_id=?", [workspace])
    if not profiles:
        st.info("Configure an LLM profile in Connections & AI to request optional assistance. Deterministic analysis needs no provider.")
        return
    files = [f for f in store.files(workspace) if f["extension"] != ".csv"]
    if not files:
        return
    paths = {f["file_id"]: f["relative_path"] for f in files}
    file_key = "manual_ai_file_" + workspace
    if st.session_state.get(file_key) not in paths:
        st.session_state.pop(file_key, None)
    fid = st.selectbox("File for assistance", list(paths), format_func=paths.get, key=file_key)
    source = store.file(fid)
    count = max(1, len(source["raw_content"].splitlines()))
    first = st.number_input("Evidence start line", 1, count, 1)
    last = st.number_input("Evidence end line", int(first), count, min(count, int(first) + 20))
    task = st.selectbox("Analysis task", TASKS, format_func=lambda x: x.replace("_", " ").capitalize())
    if st.checkbox("Preview selection as statement chunks", key="ai_chunks_" + workspace):
        try:
            chunks = preview_ai_evidence(store, workspace, fid, int(first), int(last), task)['chunks']
        except ValueError as exc:
            st.warning(str(exc))
            return
        index = st.selectbox("Context chunk", range(len(chunks)),
                             format_func=lambda i: f"{i + 1}/{len(chunks)} · lines {chunks[i]['first']}–{chunks[i]['last']}")
        first, last = chunks[index]["first"], chunks[index]["last"]
        st.caption("Only this chunk is requested. Uncheck chunk preview to cancel this selection; no remaining chunks run automatically.")
    st.code("\n".join(source["raw_content"].splitlines()[int(first) - 1:int(last)]), language="sql" if source["extension"] == ".sql" else "sas")
    st.caption("Only the selected code range is sent, subject to your privacy gates, redaction and context budget. AI explanations remain advisory; relationships require exact source quotes and explicit read/write evidence.")
    if st.button("Analyze selected evidence with AI", key=f"manual_ai_request_{workspace}_{fid}_{source['content_hash']}"):
        try:
            with st.spinner("Requesting grounded analysis", show_time=True):
                response = assist_task(store, workspace, fid, int(first), int(last), task,
                                       expected_hash=source["content_hash"])
            st.session_state["ai_record_" + workspace] = response["record_id"]
            st.rerun()
        except Exception as exc:
            st.error(f"Assistance failed: {exc}")
    st.subheader("AI activity")
    st.dataframe(store.rows("SELECT created_at,task,provider,model,outcome,duration,usage FROM llm_records WHERE workspace_id=? ORDER BY created_at DESC LIMIT 50", [workspace]), hide_index=True)


def _saved_results(store: Store, workspace: str) -> None:
    """Show saved AI results and pass the selected record to its renderer.

    Args:
        store: Workspace storage service.
        workspace: Workspace identifier.
    """
    saved = store.rows("SELECT record_id,task,created_at,outcome FROM llm_records WHERE workspace_id=? ORDER BY created_at DESC LIMIT 50", [workspace])
    if saved:
        labels = {r["record_id"]: f"{r['created_at']} · {r['task']} · {r['outcome']}" for r in saved}
        history = st.selectbox("Saved AI result", list(labels), index=None, format_func=labels.get)
        if st.button("Open saved result", disabled=history is None):
            st.session_state["ai_record_" + workspace] = history
    render_result(store, workspace, "ai_record_" + workspace)
