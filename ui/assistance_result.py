"""Durable AI result presentation shared by manual and diagnostic-assisted review."""
import json

import streamlit as st

from dataforge.llm import merge_claims
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
    if record["outcome"] == "quarantined":
        st.warning(f"Response quarantined ({details.get('reason', 'validation failed')}); no relationships were added.")
    else:
        st.json(details["result"])
        st.caption("Validated quotes do not establish runtime correctness. Merged relationships remain inferred; diagnostics are not automatically marked resolved.")
        if record["outcome"] == "validated" and details["result"]["claims"]:
            if st.button("Merge grounded relationships as inferred", key=state_key + "_merge_" + record_id):
                try:
                    count = merge_claims(store, workspace, record_id)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    try:
                        analyze(store, workspace)
                    except Exception:
                        st.warning("Inferred relationships were saved, but lineage refresh failed. Run Analyze in Lineage builder to retry.")
                    else:
                        st.session_state.pop(state_key, None)
                        st.session_state[state_key + "_notice"] = f"Merged {count} inferred relationships and refreshed lineage"
                        st.rerun()
        elif record["outcome"] == "merged":
            st.caption("These relationships have already been merged as inferred.")
    st.json(json.loads(record["usage"]))
