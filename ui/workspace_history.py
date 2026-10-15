"""Recoverable history controls, separate from workspace deletion and source cleanup."""
import duckdb
import streamlit as st

from dataforge.maintenance import archive_history, history_plan, list_archives, restore_history


def render(store, workspace):
    panel = st.expander("Archive and restore old history", on_change="rerun", key="history_maintenance")
    if not panel.open:
        return
    with panel:
        st.caption("Archive old analysis/import records with a local file and a compressed database recovery copy. Current facts, source bytes, active references and the latest completed analysis stay protected. Recovery is retained; this does not reclaim source-file disk space.")
        key = "history_" + workspace
        if notice := st.session_state.pop(key + "_notice", None):
            st.success(notice)
        runs = st.number_input("Keep recent analysis records", 1, 10000, 20, key=key + "_runs")
        imports = st.number_input("Keep recent import records", 1, 10000, 20, key=key + "_imports")
        batch = st.number_input("Maximum records per type in this batch", 1, 100, 25, key=key + "_batch")
        try:
            plan = history_plan(store, workspace, runs, imports, batch)
            st.caption(f"This batch: {len(plan['analysis_runs'])} analysis records and {len(plan['ingestion_runs'])} import records eligible. Protected references may retain more than your requested count.")
            if st.button("Archive eligible history", disabled=not any(plan.values())):
                result = archive_history(store, workspace, runs, imports, batch)
                st.session_state[key + "_notice"] = f"Archived {result['analysis_runs']} analysis and {result['ingestion_runs']} import records. Recovery remains available below."
                st.rerun()
            archives = list_archives(store, workspace)
            if archives:
                st.caption("Showing up to 100 most recent recovery archives. Restore prefers the database recovery copy when available. Original files are not included in these metadata archives.")
                options = {a["archive_id"]: a for a in archives}
                selected = st.selectbox("Recovery archive", list(options), format_func=lambda a:
                    f"{options[a]['created_at']} · {options[a]['bytes']:,} bytes · {options[a]['recovery']} · {a[:8]}")
                if st.button("Restore selected history"):
                    restored = restore_history(store, workspace, selected)
                    st.session_state[key + "_notice"] = f"Restored {restored['analysis_runs']} analysis and {restored['ingestion_runs']} import records. Existing records were preserved."
                    st.rerun()
            else:
                st.caption("No history recovery archives in this workspace.")
        except (ValueError, OSError) as exc:
            st.error(f"History maintenance failed: {exc}")
        except duckdb.Error:
            st.error("History storage operation failed. No partial database changes were committed; existing recovery files remain available.")
