"""Exclusive-owner backup, safe restore to a new home and read-only integrity inspection."""
from __future__ import annotations

import hashlib
import json
import re
import stat
import tempfile
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

import duckdb

from dataforge.cleanup import WORKSPACE_TABLES, checked_path, maintenance_guard
from dataforge.store import AI_ANALYSIS_TABLES, AI_SNAPSHOT_TABLES, COLUMN_TABLES

MAX_BACKUP_BYTES = 512 * 1024 * 1024
MAX_FILES = 50000
RUNTIME_DIRS = {'blobs', 'history-recovery', 'agent', '.streamlit'}
MANAGED_FILE = re.compile(
    r'(?:dataforge\.duckdb|\.streamlit/config\.toml|blobs/[a-f0-9]{64}'
    r'|history-recovery/[a-f0-9]{32}/[a-f0-9]{32}\.(?:json|tmp)'
    r'|agent/(?:jobs|access)/[a-f0-9]{32}(?:\.[a-f0-9]{32})?\.(?:json|tmp)'
    r'|agent/results/[a-f0-9]{32}/[a-f0-9]{32}\.(?:json|csv|html)'
    r'|agent/artifacts/[a-f0-9]{32}/[a-f0-9]{32}\.(?:json|bin)'
    r'|agent/audit(?:\.previous)?\.jsonl)'
)


def inspect_database(store):
    with store.lock:
        return _inspect_database(store.home, store.rows)


def _inspect_database(home, rows):
    versions = [r['version'] for r in rows('SELECT version FROM schema_migrations ORDER BY version')]
    workspace_tables = tuple(t for t in WORKSPACE_TABLES
        if (7 in versions or t not in AI_SNAPSHOT_TABLES) and (5 in versions or t not in COLUMN_TABLES) and (6 in versions or t not in AI_ANALYSIS_TABLES))
    tables = {}
    for table in (*workspace_tables, 'parse_cache', 'prompt_versions'):
        tables[table] = rows(f'SELECT count(*) AS n FROM {table}')[0]['n']
    orphaned = {}
    for table in workspace_tables:
        if table in {'workspaces', 'settings'}:
            continue
        orphaned[table] = rows(f'SELECT count(*) AS n FROM {table} WHERE workspace_id IS NULL OR workspace_id NOT IN (SELECT workspace_id FROM workspaces)')[0]['n']
    checks = {
        'edges_source': 'SELECT count(*) AS n FROM edges e LEFT JOIN assets a ON e.source_id=a.asset_id AND e.workspace_id=a.workspace_id WHERE a.asset_id IS NULL',
        'edges_target': 'SELECT count(*) AS n FROM edges e LEFT JOIN assets a ON e.target_id=a.asset_id AND e.workspace_id=a.workspace_id WHERE a.asset_id IS NULL',
        'edges_statement': 'SELECT count(*) AS n FROM edges e LEFT JOIN statements s ON e.statement_id=s.statement_id AND e.workspace_id=s.workspace_id WHERE s.statement_id IS NULL',
        'statements_file': 'SELECT count(*) AS n FROM statements s LEFT JOIN source_files f ON s.file_id=f.file_id AND s.workspace_id=f.workspace_id WHERE f.file_id IS NULL',
        'operations_statement': 'SELECT count(*) AS n FROM operations o LEFT JOIN statements s ON o.statement_id=s.statement_id AND o.workspace_id=s.workspace_id WHERE s.statement_id IS NULL',
        'columns_asset': 'SELECT count(*) AS n FROM column_usages u LEFT JOIN assets a ON u.asset_id=a.asset_id AND u.workspace_id=a.workspace_id WHERE a.asset_id IS NULL',
        'llm_file': 'SELECT count(*) AS n FROM llm_records r LEFT JOIN source_files f ON r.file_id=f.file_id AND r.workspace_id=f.workspace_id WHERE f.file_id IS NULL',
    }
    if 5 in versions:
        checks.update({
            'column_reference_asset': 'SELECT count(*) AS n FROM column_references c LEFT JOIN assets a ON c.asset_id=a.asset_id AND c.workspace_id=a.workspace_id WHERE a.asset_id IS NULL',
            'column_derivation_target': 'SELECT count(*) AS n FROM column_derivations d LEFT JOIN column_references c ON d.target_column_id=c.column_id AND d.workspace_id=c.workspace_id WHERE c.column_id IS NULL',
            'column_derivation_statement': 'SELECT count(*) AS n FROM column_derivations d LEFT JOIN statements s ON d.statement_id=s.statement_id AND d.workspace_id=s.workspace_id WHERE s.statement_id IS NULL',
            'column_derivation_run': 'SELECT count(*) AS n FROM column_derivations d LEFT JOIN column_analysis r ON d.workspace_id=r.workspace_id AND d.run_id=r.run_id WHERE r.run_id IS NULL',
            'column_dependency_source': 'SELECT count(*) AS n FROM column_dependencies d LEFT JOIN column_references c ON d.source_column_id=c.column_id AND d.workspace_id=c.workspace_id WHERE c.column_id IS NULL',
            'column_dependency_derivation': 'SELECT count(*) AS n FROM column_dependencies i LEFT JOIN column_derivations d ON i.derivation_id=d.derivation_id AND i.workspace_id=d.workspace_id WHERE d.derivation_id IS NULL',
            'column_analysis_run': 'SELECT count(*) AS n FROM column_analysis c LEFT JOIN analysis_runs r ON c.run_id=r.run_id AND c.workspace_id=r.workspace_id WHERE r.run_id IS NULL',
        })
    if 6 in versions:
        checks.update({
            'ai_unit_run': 'SELECT count(*) AS n FROM ai_analysis_units u LEFT JOIN ai_analysis_runs r ON u.run_id=r.run_id AND u.workspace_id=r.workspace_id WHERE r.run_id IS NULL',
            'ai_claim_run': 'SELECT count(*) AS n FROM ai_analysis_claims c LEFT JOIN ai_analysis_runs r ON c.run_id=r.run_id AND c.workspace_id=r.workspace_id WHERE r.run_id IS NULL',
            'ai_support_run': 'SELECT count(*) AS n FROM analysis_fact_support s LEFT JOIN ai_analysis_runs r ON s.run_id=r.run_id AND s.workspace_id=r.workspace_id WHERE r.run_id IS NULL',
            'ai_support_record': "SELECT count(*) AS n FROM analysis_fact_support s LEFT JOIN llm_records r ON s.record_id=r.record_id AND s.workspace_id=r.workspace_id WHERE s.record_id IS NOT NULL AND s.record_id<>'' AND r.record_id IS NULL",
        })
    orphaned.update({key: rows(sql)[0]['n'] for key, sql in checks.items()})
    referenced = {r['content_hash'] for r in rows('SELECT content_hash FROM source_files UNION SELECT content_hash FROM statements')}
    for row in rows("SELECT snapshot FROM analysis_runs WHERE snapshot IS NOT NULL AND snapshot<>''"):
        referenced.update(json.loads(row['snapshot']).get('files', {}).values())
    if 7 in versions:
        orphaned['ai_snapshot_run'] = rows('SELECT count(*) AS n FROM ai_analysis_snapshots s LEFT JOIN ai_analysis_runs r ON s.run_id=r.run_id AND s.workspace_id=r.workspace_id WHERE r.run_id IS NULL')[0]['n']
        referenced.update(r['content_hash'] for r in rows('SELECT content_hash FROM ai_analysis_snapshots'))
    if 6 in versions:
        referenced.update(r['content_hash'] for r in rows('SELECT content_hash FROM ai_analysis_units'))
        for row in rows("SELECT accepted_results FROM ai_analysis_runs WHERE status='committed'"):
            referenced.update(item['metadata']['content_hash'] for item in json.loads(row['accepted_results']))
    missing = []
    for digest in referenced:
        if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
            missing.append('invalid hash')
            continue
        path = checked_path(home, 'blobs/' + digest)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            missing.append(digest)
    return {'ok': not any(orphaned.values()) and not missing and versions in ([1, 2, 3, 4], [1, 2, 3, 4, 5], [1, 2, 3, 4, 6], [1, 2, 3, 4, 5, 6], [1, 2, 3, 4, 5, 6, 7], [1, 2, 3, 4, 6, 7]),
            'schema_versions': versions, 'records': tables, 'orphan_records': orphaned,
            'missing_or_invalid_blobs': missing, 'database_bytes': (home / 'dataforge.duckdb').stat().st_size}


def checkpoint(store):
    with maintenance_guard(store):
        store.execute('CHECKPOINT')
    return {'checkpoint': 'completed', 'note': 'DuckDB checkpoint flushes the WAL; physical shrinkage is not guaranteed.'}


@contextmanager
def _database_snapshot(store, directory):
    store.execute('CHECKPOINT')
    snapshot = directory / (uuid.uuid4().hex + '.duckdb')
    checked_path(store.home, 'dataforge.duckdb')
    database_name = store.rows('SELECT current_database() AS name')[0]['name'].replace('"', '""')
    # ATTACH is a DDL statement without bound parameters; quote this generated internal path.
    store.execute("ATTACH '" + str(snapshot).replace("'", "''") + "' AS maintenance_backup")
    try:
        try:
            store.execute(f'COPY FROM DATABASE "{database_name}" TO maintenance_backup')
        finally:
            store.execute('DETACH maintenance_backup')
        yield snapshot
    finally:
        snapshot.unlink(missing_ok=True)


def _backup(store):
    if not inspect_database(store)['ok']:
        raise ValueError('Database integrity check failed; use an offline recovery copy before repair')
    directory = checked_path(store.home, 'backups')
    directory.mkdir(exist_ok=True)
    with _database_snapshot(store, directory) as snapshot:
        return _archive_snapshot(store, directory, snapshot)


def _archive_snapshot(store, directory, snapshot):
    target = directory / (uuid.uuid4().hex + '.zip')
    temporary = target.with_suffix('.tmp')
    paths = [snapshot]
    for folder in sorted(RUNTIME_DIRS):
        root = checked_path(store.home, folder)
        if root.exists():
            for path in root.rglob('*'):
                checked_path(store.home, path.relative_to(store.home))
                if path.is_file() and MANAGED_FILE.fullmatch(path.relative_to(store.home).as_posix()):
                    paths.append(path)
                if len(paths) > MAX_FILES:
                    raise ValueError('Backup exceeds 50,000 files')
    if sum(p.stat().st_size for p in paths) > MAX_BACKUP_BYTES:
        raise ValueError('Backup exceeds 512 MB; use an offline filesystem backup')
    manifest = {'format': 'dataforge-backup-v1', 'files': {}}
    try:
        with zipfile.ZipFile(temporary, 'x', zipfile.ZIP_DEFLATED) as archive:
            for path in paths:
                data = path.read_bytes()
                relative = 'dataforge.duckdb' if path == snapshot else path.relative_to(store.home).as_posix()
                manifest['files'][relative] = hashlib.sha256(data).hexdigest()
                archive.writestr(relative, data)
            archive.writestr('manifest.json', json.dumps(manifest, sort_keys=True))
        temporary.replace(target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


def backup(store):
    with maintenance_guard(store):
        return _backup(store)


def restore_backup(archive_path, destination):
    try:
        return _restore_backup(archive_path, destination)
    except (zipfile.BadZipFile, KeyError, TypeError, RuntimeError, NotImplementedError, duckdb.Error):
        raise ValueError('Invalid backup archive or database') from None


def _restore_backup(archive_path, destination):
    """Never overwrite an existing home. Validate/extract into a sibling staging directory."""
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink() or destination.resolve() != destination:
        raise ValueError('Restore requires a new, nonredirected destination directory')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='gravetrail-restore-', dir=destination.parent) as temporary:
        staging = Path(temporary)
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_FILES + 1 or sum(e.file_size for e in entries) > MAX_BACKUP_BYTES + 8 * 1024 * 1024:
                raise ValueError('Backup exceeds restore limits')
            names = [e.filename for e in entries]
            if len(names) != len({name.casefold() for name in names}) or 'manifest.json' not in names:
                raise ValueError('Invalid backup manifest')
            manifest_info = archive.getinfo('manifest.json')
            if manifest_info.file_size > 8 * 1024 * 1024:
                raise ValueError('Backup manifest exceeds limit')
            manifest = json.loads(archive.read(manifest_info))
            if (not isinstance(manifest, dict) or manifest.get('format') != 'dataforge-backup-v1'
                    or not isinstance(manifest.get('files'), dict)
                    or set(manifest['files']) != set(names) - {'manifest.json'}):
                raise ValueError('Invalid backup manifest')
            for entry in entries:
                if entry.filename == 'manifest.json':
                    continue
                relative = PurePosixPath(entry.filename)
                if (not relative.parts or relative.as_posix() != entry.filename
                        or not MANAGED_FILE.fullmatch(entry.filename)
                        or relative.is_absolute() or '..' in relative.parts or '\\' in entry.filename or ':' in entry.filename
                        or (entry.filename != 'dataforge.duckdb' and relative.parts[0] not in RUNTIME_DIRS)
                        or stat.S_ISLNK(entry.external_attr >> 16) or entry.is_dir()):
                    raise ValueError('Unsafe backup path')
                data = archive.read(entry)
                if hashlib.sha256(data).hexdigest() != manifest['files'][entry.filename]:
                    raise ValueError('Backup checksum mismatch')
                target = staging.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        database = staging / 'dataforge.duckdb'
        if not database.is_file():
            raise ValueError('Backup has no database')
        connection = duckdb.connect(str(database), read_only=True, config={'enable_external_access': False})
        try:
            versions = connection.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall()
            if versions not in ([(1,), (2,), (3,), (4,)], [(1,), (2,), (3,), (4,), (5,)],
                                [(1,), (2,), (3,), (4,), (6,)], [(1,), (2,), (3,), (4,), (5,), (6,)],
                                [(1,), (2,), (3,), (4,), (5,), (6,), (7,)], [(1,), (2,), (3,), (4,), (6,), (7,)]):
                raise ValueError('Unsupported backup schema')
            for table in WORKSPACE_TABLES:
                if (7,) not in versions and table in AI_SNAPSHOT_TABLES:
                    continue
                if (5,) not in versions and table in COLUMN_TABLES:
                    continue
                if (6,) not in versions and table in AI_ANALYSIS_TABLES:
                    continue
                connection.execute(f'SELECT count(*) FROM {table}').fetchone()
            def rows(sql):
                cursor = connection.execute(sql)
                names = [column[0] for column in cursor.description]
                return [dict(zip(names, values)) for values in cursor.fetchall()]
            if not _inspect_database(staging, rows)['ok']:
                raise ValueError('Backup integrity check failed')
        finally:
            connection.close()
        # Atomic rename into a previously nonexistent directory, on the same filesystem.
        staging.rename(destination)
    return destination
