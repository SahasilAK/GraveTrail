"""Human cleanup controls; policy and mutations stay in shared services."""
import uuid

import duckdb
import streamlit as st

from dataforge.cleanup import CATEGORIES, apply_cleanup, cleanup_plan
from dataforge.database_maintenance import backup, checkpoint, inspect_database, restore_backup
from dataforge.lineage_builder import delete_builder_tables, load_builder
from dataforge.services import analyze
from dataforge.store import Store
from dataforge.temporary_cleanup import cleanup_temporary, temporary_plan


def render(store: Store, workspace: str, mode: str = "cleanup") -> None:
    """Render cleanup or backup and integrity controls for a workspace.

    Args:
        store: Workspace storage service.
        workspace: Workspace identifier.
        mode: Selects the cleanup or backup/integrity view.
    """
    st.subheader('Cleanup preview' if mode == 'cleanup' else 'Backups & integrity', icon=':material/shield:')
    st.caption('Preview dependencies before removal. Backups contain private source data; keep a copy outside this runtime home.')
    if mode == 'cleanup':
        with st.expander('Lineage builder table schemas'):
            try:
                if notice := st.session_state.pop('builder_delete_notice_' + workspace, None):
                    st.session_state['builder_delete_tables_' + workspace] = []
                    st.session_state['builder_delete_confirm_' + workspace] = False
                    st.success(notice)
                document = load_builder(store, workspace)
                choices = {t.id: t.name for t in document.tables}
                st.caption('These schemas belong to the workspace. Clearing a canvas only removes its diagram and catalog entries. Saved work snapshots remain available after deletion.')
                selected_tables = st.multiselect('Workspace table schemas to delete', choices, format_func=choices.get,
                                                  key='builder_delete_tables_' + workspace)
                affected = sum(e.source_table in selected_tables or e.target_table in selected_tables for e in document.links)
                st.caption(f'{len(selected_tables)} tables and {affected} current relationships will be deleted.')
                confirmed = st.checkbox('Permanently delete the selected workspace table schemas', key='builder_delete_confirm_' + workspace)
                if st.button('Delete workspace table schemas', disabled=not selected_tables or not confirmed):
                    delete_builder_tables(store, workspace, selected_tables, expected_revision=document.revision)
                    st.session_state['builder_delete_notice_' + workspace] = 'Selected workspace table schemas deleted. Saved work snapshots were retained.'
                    st.rerun()
            except (ValueError, duckdb.Error, OSError) as exc:
                st.error('Table deletion refused: ' + str(exc)[:500])
        if (not st.session_state.get('save_temporary_cleanup_preference')
                and store.setting(workspace, 'auto_cleanup_temporary', False)):
            try:
                plan = temporary_plan(store, workspace)
                if plan['files']:
                    st.json(cleanup_temporary(store, workspace, plan['files']))
            except (ValueError, OSError, duckdb.Error):
                st.caption('Automatic staging cleanup deferred while storage is busy or paths are unsafe.')
        names = {row['workspace_id']: row['name'] for row in store.workspaces()}
        metrics = []
        try:
            for category in ('sources', 'lineage', 'columns', 'ai', 'history', 'jobs'):
                plan = cleanup_plan(store, workspace, category)
                metrics.append({'Category': category, 'Records affected': sum(plan['records'].values()),
                                'Logical bytes estimate': plan['logical_bytes_estimate'], 'Managed file bytes': plan['file_bytes']})
        except (ValueError, OSError, duckdb.Error):
            st.session_state.pop('cleanup_preview', None)
            st.error('Cannot safely inspect cleanup storage. Check database access, job journals and redirected runtime paths.')
            return
        st.dataframe(metrics, hide_index=True, alt='Calculated cleanup scope and logical storage estimates by category')
        st.caption('Categories overlap because dependencies are included. Logical JSON row estimates differ from DuckDB disk space. No embedding index or runtime knowledge base is currently implemented; repository documentation is always preserved.')
        category = st.selectbox('Cleanup category', CATEGORIES, format_func=lambda v: {
            'sources': 'Imported source inventory', 'lineage': 'Lineage and analysis history',
            'columns': 'Direct column usage', 'ai': 'AI results and dependent lineage',
            'history': 'Unreferenced analysis / ingestion history', 'jobs': 'Completed, failed or interrupted jobs',
            'cache': 'Shared parser and Streamlit data caches', 'reset': 'Reset workspace (keep settings and imported files)',
            'workspace': 'Delete workspace', 'orphans': 'Unreferenced shared source blobs',
            'application': 'Full application data reset (recognized runtime data only)',
        }[v])
        shared = category in {'cache', 'orphans', 'application'}
        if shared:
            st.warning('This operation covers shared application storage across all workspaces.')
        file_ids, run_id = None, None
        if category == 'sources':
            files = {f['file_id']: f['relative_path'] for f in store.files(workspace)}
            selected = st.multiselect('Imported files to delete (empty means all)', list(files), format_func=files.get)
            file_ids = selected or None
        if category == 'history':
            runs = [r['run_id'] for r in store.runs(workspace)]
            run_id = st.selectbox('Specific analysis run (optional)', [None, *runs], format_func=lambda r: r or 'All unreferenced history')
        phrase = 'RESET GRAVETRAIL' if category == 'application' else 'CLEAN SHARED DATA' if shared else names[workspace]
        preview = st.session_state.get('cleanup_preview')
        if preview and (preview['category'] != category or preview['workspace_id'] != ('' if shared else workspace)
                        or sorted(preview['file_ids']) != sorted(file_ids or []) or preview['run_id'] != run_id):
            st.session_state.pop('cleanup_preview', None)
            st.session_state.pop('cleanup_confirmation', None)
        if st.button('Preview cleanup', type='primary'):
            st.session_state.pop('cleanup_preview', None)
            st.session_state.pop('cleanup_confirmation', None)
            try:
                st.session_state['cleanup_preview'] = cleanup_plan(store, '' if shared else workspace, category, file_ids, run_id)
            except (ValueError, OSError, duckdb.Error):
                st.error('Cannot safely inspect these runtime paths. Check storage access and redirected paths.')
        preview = st.session_state.get('cleanup_preview')
        if preview and preview['category'] == category and preview['workspace_id'] == ('' if shared else workspace):
            st.warning("This removes the previewed records and their dependent data. A full-home backup is required.")
            st.dataframe([{"Record type": k, "Affected records": v} for k, v in preview["records"].items()], hide_index=True)
            with st.expander("Complete cleanup plan"):
                st.json(preview)
            for note in preview['notes']:
                st.caption(note)
            backup_first = st.checkbox('Create a full-home backup before cleanup', value=True, disabled=True,
                                       help='A recoverable full-home backup is required for general cleanup.')
            confirmation = st.text_input('Type ' + phrase + ' to confirm', key='cleanup_confirmation')
            if st.button('Apply previewed cleanup', disabled=confirmation != phrase):
                try:
                    result = apply_cleanup(store, preview, confirmation, backup_first)
                    if category == 'cache':
                        st.cache_data.clear()
                    st.session_state.pop('cleanup_preview', None)
                    st.session_state['cleanup_result'] = result
                    if category in {'workspace', 'application'}:
                        st.session_state['runtime_connections'].clear()
                    # The app shell selects a surviving workspace before rendering its widget.
                    st.rerun()
                except (ValueError, OSError) as exc:
                    st.error('Cleanup refused: ' + str(exc))
                except duckdb.Error:
                    st.session_state.pop('cleanup_preview', None)
                    st.error('Cleanup stopped after a database error. Reload the page and reconnect storage before creating a fresh preview.')
                    return
        if st.button('Rebuild lineage'):
            try:
                with st.spinner('Rebuilding stored lineage'):
                    result = analyze(store, workspace, force=True)
                st.success(f"Lineage rebuilt: {result['assets']} assets, {result['edges']} edges")
            except Exception:
                st.error('Rebuild failed. Inspect diagnostics and active jobs.')
    else:
        st.subheader('Database maintenance')
        if st.button('Check integrity and storage'):
            try:
                st.json(inspect_database(store))
            except (ValueError, OSError, duckdb.Error):
                st.error('Integrity inspection failed. Check filesystem access and runtime path safety.')
        if st.button('Checkpoint database'):
            try:
                st.json(checkpoint(store))
            except (ValueError, OSError, duckdb.Error):
                st.error('Checkpoint refused. Wait for active work to finish.')
        if st.button('Create runtime backup'):
            try:
                path = backup(store)
                st.success('Backup created: ' + str(path))
                st.download_button('Download runtime backup', path.read_bytes(), path.name, 'application/zip')
            except (ValueError, OSError, duckdb.Error):
                st.error('Backup refused. Wait for active jobs or check storage access and backup size limits.')
        st.caption('Restore validates checksums and schema into a new directory. The active home is never overwritten; restart with DATAFORGE_HOME pointing to the restored directory.')
        archives = sorted((store.home / 'backups').glob('*.zip'))
        if archives:
            archive = st.selectbox('Backup to restore', archives, format_func=lambda p: p.name)
            restore_confirmation = st.text_input('Type RESTORE GRAVETRAIL to create a restored home')
            if st.button('Restore into a new sibling home', disabled=restore_confirmation != 'RESTORE GRAVETRAIL'):
                try:
                    destination = store.home.parent / ('gravetrail-restored-' + uuid.uuid4().hex)
                    st.success('Restored to ' + str(restore_backup(archive, destination)))
                except (ValueError, OSError):
                    st.error('Restore refused; the backup is invalid or its destination is unavailable.')
    if mode == 'cleanup':
        st.subheader('Expired temporary data')
        with st.form('automatic_expired_cleanup'):
            automatic = st.checkbox('Automatically clear expired recovery staging files when opening cleanup settings',
                                    value=store.setting(workspace, 'auto_cleanup_temporary', False))
            st.caption('Opt-in; only app-created staging files older than 24 hours, at most 100 / 25 MB per visit. A recoverable database copy is retained. Active jobs block deletion.')
            if st.form_submit_button('Save temporary cleanup preference', key='save_temporary_cleanup_preference'):
                from dataforge.settings_service import save_ui_settings
                try:
                    save_ui_settings(store, workspace, 'temporary_cleanup', {'enabled': automatic})
                    st.rerun()
                except (ValueError, OSError, duckdb.Error):
                    st.error('Could not save the temporary cleanup preference. Check database access and active jobs.')
