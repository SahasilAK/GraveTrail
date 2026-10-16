"""Previewed, dependency-aware runtime cleanup. No caller-supplied SQL or paths."""
from __future__ import annotations

import hashlib
import json
import re
import stat
import time
from contextlib import contextmanager

from dataforge.maintenance import _idle

GRAPH = ('edges', 'column_usages', 'operation_assets', 'operations', 'statements',
         'asset_aliases', 'assets', 'diagnostics')
WORKSPACE_TABLES = (*GRAPH, 'analysis_runs', 'llm_records', 'ingestion_runs', 'source_files',
                    'history_archives', 'temporary_recovery', 'llm_profiles', 'settings', 'workspaces')
CATEGORIES = ('sources', 'lineage', 'columns', 'ai', 'history', 'jobs', 'cache', 'reset',
              'workspace', 'orphans', 'application')


def checked_path(home, relative):
    """Reject symlinks, hard links, Windows junctions and escaped paths at every component."""
    path = home / relative
    if not path.resolve().is_relative_to(home) or path == home:
        raise ValueError('Runtime path escapes the data home')
    current = home
    for component in path.relative_to(home).parts:
        current = current / component
        if current.exists() or current.is_symlink():
            info = current.lstat()
            if current.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('Runtime paths cannot be symlinks or reparse points')
            if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                raise ValueError('Runtime files cannot be hard links')
    return path


def _job_files(store):
    directory = checked_path(store.home, 'agent/jobs')
    paths = sorted(directory.glob('*.json')) if directory.exists() else []
    if len(paths) > 1000:
        raise ValueError('Job inventory exceeds 1000 records; repair storage before maintenance')
    return paths


def assert_idle(store, workspace=''):
    """Also catch queued imports and provider requests which do not own analysis_lock."""
    from dataforge.llm_resources import has_active_requests

    if has_active_requests(store.home, workspace):
        raise ValueError('An active AI request blocks cleanup')
    for path in _job_files(store):
        checked_path(store.home, path.relative_to(store.home))
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError('Job journal exceeds maintenance limit')
        record = json.loads(path.read_text(encoding='utf-8'))
        if (not workspace or record['workspace_id'] == workspace) and record['status'] not in {'completed', 'failed', 'interrupted'}:
            if time.time() - record['updated_at'] <= 30:
                raise ValueError('An active job blocks cleanup')
    params = [workspace] if workspace else []
    if store.rows("SELECT 1 FROM analysis_runs WHERE status='running'" + (' AND workspace_id=?' if workspace else '') + ' LIMIT 1', params):
        raise ValueError('An active analysis blocks cleanup; recover interrupted runs first')


@contextmanager
def maintenance_guard(store, workspace=''):
    with _idle(store):
        assert_idle(store, workspace)
        yield


def _revision(store):
    # Aggregate row hashes avoid disclosing source or secrets in a preview token.
    fingerprints = []
    for table in (*WORKSPACE_TABLES, 'parse_cache', 'prompt_versions'):
        row = store.rows(f'SELECT count(*) AS n, bit_xor(hash(t)) AS h FROM {table} t')[0]
        fingerprints.append([table, row['n'], str(row['h'])])
    return hashlib.sha256(json.dumps(fingerprints).encode()).hexdigest()


def _files(store, workspace, category):
    files = []
    if category in {'jobs', 'workspace', 'application'}:
        for path in _job_files(store):
            record = json.loads(checked_path(store.home, path.relative_to(store.home)).read_text(encoding='utf-8'))
            if category == 'application' or record['workspace_id'] == workspace:
                if record['status'] in {'completed', 'failed', 'interrupted'} or time.time() - record['updated_at'] > 30:
                    files.append(path)
    scopes = []
    if category in {'sources', 'reset', 'workspace', 'application'}:
        ids = [r['workspace_id'] for r in store.workspaces()] if category == 'application' else [workspace]
        scopes = [f'{folder}/{wid}' for wid in ids for folder in ('history-recovery', 'agent/results')]
    for relative in scopes:
        directory = checked_path(store.home, relative)
        if directory.exists():
            for path in directory.iterdir():
                checked_path(store.home, path.relative_to(store.home))
                if path.is_file() and re.fullmatch(r'[a-f0-9]{32}\.(json|tmp|csv|html)', path.name):
                    files.append(path)
    if category in {'workspace', 'application'}:
        ids = [r['workspace_id'] for r in store.workspaces()] if category == 'application' else [workspace]
        for wid in ids:
            path = checked_path(store.home, f'agent/access/{wid}.json')
            if path.is_file():
                files.append(path)
    if category == 'application':
        for relative in ('agent/audit.jsonl', 'agent/audit.previous.jsonl', '.streamlit/config.toml'):
            path = checked_path(store.home, relative)
            if path.is_file():
                files.append(path)
    if category in {'orphans', 'application'}:
        referenced = {r['content_hash'] for r in store.rows('SELECT content_hash FROM source_files UNION SELECT content_hash FROM statements')}
        for row in store.rows("SELECT snapshot FROM analysis_runs WHERE snapshot IS NOT NULL AND snapshot<>''"):
            referenced.update(json.loads(row['snapshot']).get('files', {}).values())
        # Recovery archives can retain references to older source versions. Preserve conservatively.
        archived = bool(store.rows('SELECT 1 FROM history_archives LIMIT 1'))
        directory = checked_path(store.home, 'blobs')
        for path in directory.iterdir():
            if re.fullmatch(r'[a-f0-9]{64}', path.name):
                checked_path(store.home, path.relative_to(store.home))
                if category == 'application' or (not archived and path.name not in referenced):
                    files.append(path)
    if len(files) > 50000:
        raise ValueError('Cleanup exceeds 50,000 files; use smaller workspace operations')
    return [{'path': p.relative_to(store.home).as_posix(), 'bytes': p.stat().st_size,
             'modified_ns': p.stat().st_mtime_ns, 'inode': p.stat().st_ino} for p in sorted(set(files))]


def _selection(store, workspace, category, file_ids, run_id):
    if category not in CATEGORIES:
        raise ValueError('Unknown cleanup category')
    global_scope = category in {'orphans', 'application', 'cache'}
    if global_scope and workspace:
        raise ValueError('This category is shared across the application; omit workspace')
    if not global_scope and not store.rows('SELECT 1 FROM workspaces WHERE workspace_id=?', [workspace]):
        raise ValueError('Workspace does not exist')
    if file_ids and category != 'sources':
        raise ValueError('File selection is supported only for source cleanup')
    if run_id and category != 'history':
        raise ValueError('Run selection is supported only for unreferenced analysis history')
    tables = {
        'sources': (*GRAPH, 'analysis_runs', 'llm_records', 'history_archives', 'temporary_recovery', 'source_files'),
        'lineage': (*GRAPH, 'analysis_runs'), 'columns': ('column_usages',),
        'ai': (*GRAPH, 'analysis_runs', 'llm_records'),  # remove dependent inferred graph, rebuild deterministically
        'history': ('analysis_runs', 'ingestion_runs'), 'jobs': (), 'cache': ('parse_cache',),
        'reset': (*GRAPH, 'analysis_runs', 'llm_records', 'history_archives', 'temporary_recovery', 'ingestion_runs'),
        'workspace': WORKSPACE_TABLES, 'orphans': (),
        'application': (*WORKSPACE_TABLES, 'parse_cache', 'prompt_versions'),
    }[category]
    selected = {}
    for table in tables:
        where, params = ('TRUE', []) if global_scope else ('workspace_id=?', [workspace])
        if table == 'source_files' and file_ids:
            if len(file_ids) > 10000 or not set(file_ids) <= {f['file_id'] for f in store.files(workspace)}:
                raise ValueError('Selected files do not belong to this workspace')
            where += ' AND file_id IN (' + ','.join('?' for _ in file_ids) + ')'
            params += file_ids
        if category == 'history':
            if table == 'analysis_runs':
                where += " AND status IN ('completed','failed','cancelled') AND run_id NOT IN (SELECT run_id FROM edges WHERE workspace_id=?)"
                params.append(workspace)
                if run_id:
                    where += ' AND run_id=?'
                    params.append(run_id)
            else:
                where += ' AND ingestion_id NOT IN (SELECT ingestion_id FROM source_files WHERE workspace_id=?)'
                params.append(workspace)
                if run_id:
                    where += ' AND FALSE'
        selected[table] = (where, params)
    return selected


def cleanup_plan(store, workspace='', category='lineage', file_ids=None, run_id=None):
    with store.lock:
        selected = _selection(store, workspace, category, file_ids, run_id)
        counts, sizes = {}, {}
        for table, (where, params) in selected.items():
            row = store.rows(f'SELECT count(*) AS n, coalesce(sum(octet_length(encode(to_json(t)))),0) AS bytes FROM {table} t WHERE {where}', params)[0]
            counts[table], sizes[table] = row['n'], row['bytes']
        files = _files(store, workspace, category)
        plan = {'workspace_id': workspace, 'category': category, 'file_ids': file_ids or [], 'run_id': run_id,
                'records': counts, 'logical_bytes_estimate': sum(sizes.values()), 'files': files,
                'file_bytes': sum(f['bytes'] for f in files), 'revision': _revision(store),
                'notes': ['Logical JSON row estimates are not physically reclaimable database bytes.',
                          'Source/AI cleanup invalidates the complete workspace graph and analysis history; rebuild lineage afterwards.',
                          'Parser cache is shared and separate. Clear shared cache and orphan blobs separately to remove unreferenced source-derived copies.',
                          'Repository documentation and unrecognized runtime files are never deleted.']}
        plan['token'] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
        return plan


def apply_cleanup(store, preview, confirmation, backup_first=False):
    workspace, category = preview['workspace_id'], preview['category']
    with maintenance_guard(store, '' if category in {'application', 'cache', 'orphans'} else workspace):
        expected = store.rows('SELECT name FROM workspaces WHERE workspace_id=?', [workspace]) if workspace else []
        phrase = expected[0]['name'] if expected else 'RESET DATAFORGE' if category == 'application' else 'CLEAN SHARED DATA'
        if confirmation != phrase:
            raise ValueError('Explicit confirmation does not match')
        current = cleanup_plan(store, workspace, category, preview.get('file_ids'), preview.get('run_id'))
        if current['token'] != preview.get('token'):
            raise ValueError('Storage changed; refresh the cleanup preview')
        backup_path = None
        if backup_first:
            from dataforge.database_maintenance import _backup
            backup_path = str(_backup(store))
        with store.transaction():
            for table, (where, params) in _selection(store, workspace, category, preview.get('file_ids'), preview.get('run_id')).items():
                store.execute(f'DELETE FROM {table} WHERE {where}', params)
            if category in {'sources', 'lineage', 'ai', 'reset'}:
                store.execute("UPDATE source_files SET parsing_status='pending',metadata='{}',error_details='' WHERE workspace_id=?", [workspace])
        removed, failed = [], []
        # Database commits first: interruption can leave harmless unreferenced files, never missing evidence.
        for item in current['files']:
            try:
                path = checked_path(store.home, item['path'])
                info = path.stat()
                if (info.st_size, info.st_mtime_ns, info.st_ino) != (item['bytes'], item['modified_ns'], item['inode']):
                    raise ValueError('File changed')
                path.unlink()
                removed.append(item['path'])
            except (OSError, ValueError):
                failed.append(item['path'])
        return {'records_deleted': current['records'], 'files_deleted': removed, 'files_retained': failed,
                'backup': backup_path, 'rebuild_required': category in {'sources', 'lineage', 'ai', 'reset'}}
