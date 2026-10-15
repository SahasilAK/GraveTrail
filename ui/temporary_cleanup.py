"""Explicit, previewed and recoverable application staging-file cleanup."""
import duckdb
import streamlit as st

from dataforge.temporary_cleanup import (
    cleanup_temporary,
    restore_temporary,
    temporary_plan,
    temporary_recoveries,
)


def render(store, workspace):
    panel = st.expander("Clean stale temporary files", on_change="rerun", key="temporary_cleanup_panel")
    if panel.open:
        with panel:
            _controls(store, workspace)


def _controls(store, workspace):
    st.caption("Only application-created history staging files older than 24 hours are eligible. Original source files, database files, JSON history archives and other workspaces are excluded. A compressed database recovery copy is committed before removal. This clears staging files; retained recovery copies mean total disk space may not shrink.")
    key = "temporary_cleanup_" + workspace
    if notice := st.session_state.pop(key + "_notice", None):
        st.success(notice)
    age = st.number_input("Minimum temporary-file age (hours)", 24, 8760, 24, key=key + "_age")
    try:
        plan = temporary_plan(store, workspace, age)
        st.caption(f"Eligible preview: {len(plan['files'])} files / {plan['bytes']:,} bytes. Maximum batch 100 files / 25 MB; scan limit 10,000 directory entries.")
        if plan["truncated"]:
            st.warning("Preview is bounded. Additional eligible files may remain after this batch.")
        if plan["files"]:
            st.dataframe([{"file": row["name"], "bytes": row["size"]} for row in plan["files"]], hide_index=True)
            choices = {row["name"]: row for row in plan["files"]}
            choice_key = key + "_selected"
            if any(name not in choices for name in st.session_state.get(choice_key, [])):
                st.session_state.pop(choice_key, None)
            selected = st.multiselect("Temporary files to clean", list(choices), key=choice_key)
            if st.button("Clean selected temporary files", disabled=not selected):
                result = cleanup_temporary(store, workspace, [choices[name] for name in selected], age)
                st.session_state.pop(choice_key, None)
                st.session_state[key + "_notice"] = f"Cleaned {result['removed']} temporary files. Recovery copies remain available."
                st.rerun()
        else:
            st.info("No eligible stale application temporary files in this workspace.")
        recoveries = temporary_recoveries(store, workspace)
        if recoveries:
            labels = {r["recovery_id"]: f"{r['created_at']} · {r['file_name']} · {r['byte_count']:,} bytes" for r in recoveries}
            selected = st.selectbox("Temporary-file recovery copy", list(labels), format_func=labels.get)
            if st.button("Restore selected temporary file"):
                result = restore_temporary(store, workspace, selected)
                st.session_state[key + "_notice"] = f"Restored {result['restored']}. Existing files were not overwritten."
                st.rerun()
    except (ValueError, OSError) as exc:
        st.error(f"Temporary maintenance stopped: {exc}. Committed recovery copies remain retained.")
    except duckdb.Error:
        st.error("Temporary recovery storage is unavailable. No file is removed without a committed recovery copy. Restart the app after upgrading its database schema.")
