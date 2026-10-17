"""Human cleanup controls; policy and mutations stay in shared services."""
import uuid

import streamlit as st

from dataforge.cleanup import CATEGORIES, apply_cleanup, cleanup_plan
from dataforge.database_maintenance import backup, checkpoint, inspect_database, restore_backup
from dataforge.services import analyze
from dataforge.temporary_cleanup import cleanup_temporary, temporary_plan


def render(store, workspace):
    st.subheader('Data Management & Cleanup')
    st.caption('Preview dependencies before removal. Backups contain private source data; keep a copy outside this runtime home.')
    names = {row['workspace_id']: row['name'] for row in store.workspaces()}
    metrics = []
    for category in ('sources', 'lineage', 'columns', 'ai', 'history', 'jobs'):
        plan = cleanup_plan(store, workspace, category)
        metrics.append({'Category': category, 'Records affected': sum(plan['records'].values()),
                        'Logical bytes estimate': plan['logical_bytes_estimate'], 'Managed file bytes': plan['file_bytes']})
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
    phrase = 'RESET DATAFORGE' if category == 'application' else 'CLEAN SHARED DATA' if shared else names[workspace]
    if st.button('Preview cleanup', type='primary'):
        try:
            st.session_state['cleanup_preview'] = cleanup_plan(store, '' if shared else workspace, category, file_ids, run_id)
        except (ValueError, OSError):
            st.error('Cannot safely inspect these runtime paths. Check storage access and redirected paths.')
    preview = st.session_state.get('cleanup_preview')
    if preview and preview['category'] == category and preview['workspace_id'] == ('' if shared else workspace):
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
                st.success('Cleanup committed. Retained files, if any, can be retried after checking access.')
                st.json(result)
                if category in {'workspace', 'application'}:
                    st.session_state['runtime_connections'].clear()
                    st.session_state.pop('workspace', None)
                    st.rerun()
            except (ValueError, OSError) as exc:
                st.error('Cleanup refused: ' + str(exc))
    if st.button('Rebuild lineage'):
        try:
            with st.spinner('Rebuilding stored lineage'):
                result = analyze(store, workspace, force=True)
            st.success(f"Lineage rebuilt: {result['assets']} assets, {result['edges']} edges")
        except Exception:
            st.error('Rebuild failed. Inspect diagnostics and active jobs.')
    st.subheader('Database maintenance')
    if st.button('Check integrity and storage'):
        try:
            st.json(inspect_database(store))
        except (ValueError, OSError):
            st.error('Integrity inspection failed. Check filesystem access and runtime path safety.')
    if st.button('Checkpoint database'):
        try:
            st.json(checkpoint(store))
        except (ValueError, OSError):
            st.error('Checkpoint refused. Wait for active work to finish.')
    if st.button('Create runtime backup'):
        try:
            path = backup(store)
            st.success('Backup created: ' + str(path))
            st.download_button('Download runtime backup', path.read_bytes(), path.name, 'application/zip')
        except (ValueError, OSError):
            st.error('Backup refused. Wait for active jobs or check storage access and backup size limits.')
    st.caption('Restore validates checksums and schema into a new directory. The active home is never overwritten; restart with DATAFORGE_HOME pointing to the restored directory.')
    archives = sorted((store.home / 'backups').glob('*.zip'))
    if archives:
        archive = st.selectbox('Backup to restore', archives, format_func=lambda p: p.name)
        restore_confirmation = st.text_input('Type RESTORE DATAFORGE to create a restored home')
        if st.button('Restore into a new sibling home', disabled=restore_confirmation != 'RESTORE DATAFORGE'):
            try:
                destination = store.home.parent / ('dataforge-restored-' + uuid.uuid4().hex)
                st.success('Restored to ' + str(restore_backup(archive, destination)))
            except (ValueError, OSError):
                st.error('Restore refused; the backup is invalid or its destination is unavailable.')
    st.subheader('Expired temporary data')
    with st.form('automatic_expired_cleanup'):
        automatic = st.checkbox('Automatically clear expired recovery staging files when opening cleanup settings',
                                value=store.setting(workspace, 'auto_cleanup_temporary', False))
        st.caption('Opt-in; only app-created staging files older than 24 hours, at most 100 / 25 MB per visit. A recoverable database copy is retained. Active jobs block deletion.')
        if st.form_submit_button('Save temporary cleanup preference'):
            from dataforge.settings_service import save_ui_settings
            save_ui_settings(store, workspace, 'temporary_cleanup', {'enabled': automatic})
    if automatic:
        try:
            plan = temporary_plan(store, workspace)
            if plan['files']:
                st.json(cleanup_temporary(store, workspace, plan['files']))
        except (ValueError, OSError):
            st.caption('Automatic staging cleanup deferred while storage is busy or paths are unsafe.')
