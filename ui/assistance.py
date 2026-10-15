"""Focused, user-triggered AI assistance over imported source evidence."""
import streamlit as st

from dataforge.llm import TASKS, assist_task, merge_claims
from dataforge.services import analyze


def render(store, workspace):
    profiles = store.rows("SELECT profile_id FROM llm_profiles WHERE workspace_id=?", [workspace])
    if not profiles:
        st.info("Configure an LLM profile in Settings to request optional assistance. Deterministic analysis needs no provider.")
        return
    files = [f for f in store.files(workspace) if f["extension"] != ".csv"]
    if not files:
        return
    paths = {f["file_id"]: f["relative_path"] for f in files}
    fid = st.selectbox("File for assistance", list(paths), format_func=paths.get)
    source = store.file(fid)
    count = max(1, len(source["raw_content"].splitlines()))
    first = st.number_input("Evidence start line", 1, count, 1)
    last = st.number_input("Evidence end line", int(first), count, min(count, int(first) + 20))
    task = st.selectbox("Analysis task", TASKS, format_func=lambda x: x.replace("_", " ").capitalize())
    st.code("\n".join(source["raw_content"].splitlines()[int(first) - 1:int(last)]), language="sql" if source["extension"] == ".sql" else "sas")
    st.caption("Only the selected code range is sent, subject to your privacy gates, redaction and context budget. AI explanations remain advisory; relationships require exact source quotes and explicit read/write evidence.")
    if st.button("Analyze selected evidence with AI"):
        try:
            with st.spinner("Requesting grounded analysis"):
                response = assist_task(store, workspace, fid, int(first), int(last), task)
            st.session_state["ai_result_" + workspace] = response
        except Exception as exc:
            st.error(f"Assistance failed: {exc}")
    response = st.session_state.get("ai_result_" + workspace)
    if response:
        if response["outcome"] != "validated":
            st.warning(f"Response quarantined ({response['reason']}); no relationships were added.")
        else:
            st.json(response["result"])
            st.caption("Validated quotes and asset references do not establish runtime correctness. Merged relationships remain marked inferred.")
            if response["result"]["claims"] and st.button("Merge grounded relationships as inferred"):
                try:
                    count = merge_claims(store, workspace, response["record_id"])
                    analyze(store, workspace)
                    st.success(f"Merged {count} inferred relationships and refreshed lineage")
                    del st.session_state["ai_result_" + workspace]
                except ValueError as exc:
                    st.error(str(exc))
        st.json(response["usage"])
    st.subheader("AI activity")
    st.dataframe(store.rows("SELECT created_at,task,provider,model,outcome,duration,usage FROM llm_records WHERE workspace_id=? ORDER BY created_at DESC LIMIT 50", [workspace]), hide_index=True)
