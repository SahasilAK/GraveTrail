import streamlit as st

from ui.common import context, title
from ui.presentation import section

title("Data management", "Manage storage, transfer workspace preferences and recover data safely.")
store, w = context()
mode = section("Data management section", ["Storage & transfers", "Backups & integrity", "Cleanup & recovery", "History & staging"], "management_section_" + w)
if mode == "Storage & transfers":
    from ui.workspace_settings import render_storage
    render_storage(store, w)
elif mode in {"Cleanup & recovery", "Backups & integrity"}:
    from ui.data_management import render
    render(store, w, "cleanup" if mode == "Cleanup & recovery" else "database")
else:
    st.subheader("Import history")
    st.dataframe(store.rows("SELECT created_at,source,report FROM ingestion_runs WHERE workspace_id=? ORDER BY created_at DESC", [w]),
                 hide_index=True, alt="Import history for this workspace")
    from ui.workspace_history import render as render_history
    render_history(store, w)
    from ui.temporary_cleanup import render as render_staging
    render_staging(store, w)
