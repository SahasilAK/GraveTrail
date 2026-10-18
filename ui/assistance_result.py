"""Durable AI result presentation shared by manual and diagnostic-assisted review."""
import json

import streamlit as st

from dataforge.agent.contracts import AgentError
from dataforge.ai_service import merge_ai_result
from dataforge.asset_identity import source_job
from dataforge.services import analyze


def render_result(store, workspace, state_key):
    if notice := st.session_state.pop(state_key + "_notice", None):
        st.success(notice)
    record_id = st.session_state.get(state_key)
    if not record_id:
        return
    records = store.rows("SELECT * FROM llm_records WHERE workspace_id=? AND record_id=?", [workspace, record_id])
    if not records:
        st.session_state.pop(state_key, None)
        st.info("This AI result is no longer retained. Request a new review if needed.")
        return
    record = records[0]
    details = json.loads(record["details"])
    job = details.get("job_id", "workspace")
    st.caption(f"Source job/session: {job}")
    config = {"default_job": store.setting(workspace, "default_job", "workspace"),
              "job_by_folder": store.setting(workspace, "job_by_folder", {})}
    if job != source_job(store.file(record["file_id"]), config):
        st.warning("Source job/session assignment changed since this result. Request assistance again for the current context.")
    if record["outcome"] == "quarantined":
        st.warning(f"Response quarantined ({details.get('reason', 'validation failed')}); no relationships were added.")
    else:
        result = details["result"]
        if record["task"] in {"column_usage", "code_explanation"}:
            st.caption("AI advisory result. Exact citations are checked; prose is not independently verified. These results never change deterministic column reports or lineage.")
            source = store.file(record["file_id"])
            if source["content_hash"] != details["content_hash"]:
                st.warning("Source changed since this result. Citations refer to its saved source version; request a new analysis for current code.")
            if "claims" in result:
                st.info("Legacy advisory format. Request a new analysis for task-specific results; this record cannot be merged.")
                st.json(result)
            else:
                items = result.get("columns", result.get("explanations", []))
                if "columns" in result:
                    st.subheader("AI-inferred direct column suggestions")
                    st.dataframe([{**{k: v for k, v in item.items() if k != "quote"}, "status": "AI-inferred"}
                                  for item in items], hide_index=True)
                for i, item in enumerate(items):
                    label = f"{source['relative_path']}:{item['start_line']}–{item['end_line']} · evidence {i + 1}"
                    with st.expander(label):
                        st.text(item.get("text", item.get("explanation", "")))
                        st.code(item["quote"], language="sql" if source["extension"] == ".sql" else "sas")
                if result.get("unresolved_symbols"):
                    st.write("Unresolved:", result["unresolved_symbols"])
                if not items:
                    st.info("No supported task findings were returned.")
            st.download_button("Download advisory result JSON", json.dumps(details, indent=2),
                               "ai-result.json", "application/json", key=state_key + "_download_" + record_id)
            st.json(json.loads(record["usage"]))
            return
        st.json(result)
        st.caption("Validated quotes do not establish runtime correctness. Merged relationships remain inferred; diagnostics are not automatically marked resolved.")
        if record["outcome"] == "validated" and details["result"]["claims"]:
            if st.button("Merge grounded relationships as inferred", key=state_key + "_merge_" + record_id):
                try:
                    count = merge_ai_result(store, workspace, record_id, refresh=False)['merged']
                except (ValueError, AgentError) as exc:
                    st.error(str(exc))
                else:
                    try:
                        analyze(store, workspace)
                    except Exception:
                        st.warning("Inferred relationships were saved, but lineage refresh failed. Run Analysis to retry.")
                    else:
                        st.session_state.pop(state_key, None)
                        st.session_state[state_key + "_notice"] = f"Merged {count} inferred relationships and refreshed lineage"
                        st.rerun()
        elif record["outcome"] == "merged":
            st.caption("These relationships have already been merged as inferred.")
    st.json(json.loads(record["usage"]))
