"""Bounded, redacted transport artifacts separate from progress/checkpoint rows."""
from __future__ import annotations

import re
from time import time

from dataforge.connections import current_connections

MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
MAX_RUN_BYTES = 64 * 1024 * 1024
RETENTION_SECONDS = 7 * 24 * 3600
KINDS = {'input', 'output', 'decoded'}
INSPECTION_SCHEMA = '''
CREATE TABLE ai_inspection_artifacts(workspace_id VARCHAR, run_id VARCHAR,
    attempt_id VARCHAR, kind VARCHAR, content VARCHAR, byte_count BIGINT,
    status VARCHAR, redacted BOOLEAN, captured_at DOUBLE,
    PRIMARY KEY(run_id,attempt_id,kind));
CREATE INDEX ai_inspection_run ON ai_inspection_artifacts(workspace_id,run_id);
'''


def cleanup_payloads(store, workspace=None):
    """Expire content, retaining small explicit tombstones until run cleanup."""
    workspaces = [workspace] if workspace else [r['workspace_id'] for r in store.rows('SELECT DISTINCT workspace_id FROM ai_inspection_artifacts')]
    for owner in workspaces:
        history = store.setting(owner, 'llm_history', False)
        age = min(RETENTION_SECONDS, int(store.setting(owner, 'llm_retention_days', 30)) * 86400)
        reason = 'Not retained: expired under workspace retention (at most 7 days)' if history else 'Not retained: AI interaction history disabled'
        store.execute('''UPDATE ai_inspection_artifacts SET content=NULL,byte_count=0,status=?
            WHERE workspace_id=? AND content IS NOT NULL AND (captured_at<? OR ?)''',
            [reason, owner, time() - age, not history])
    store.execute('''DELETE FROM ai_inspection_artifacts a WHERE NOT EXISTS
        (SELECT 1 FROM ai_analysis_runs r WHERE r.workspace_id=a.workspace_id AND r.run_id=a.run_id)''' +
        (' AND a.workspace_id=?' if workspace else ''), [workspace] if workspace else [])


def _attempt(store, workspace, run_id, attempt_id):
    if not store.rows('SELECT 1 FROM ai_analysis_attempts WHERE workspace_id=? AND run_id=? AND attempt_id=?',
                       [workspace, run_id, attempt_id]):
        raise ValueError('Attempt not found in this workspace/run')


def capture_payload(store, workspace, run_id, attempt_id, kind, body, secrets=(), *, unavailable=None):
    """Store a redacted copy; never change the dispatched body or retain headers."""
    if kind not in KINDS:
        raise ValueError('Unknown inspection artifact kind')
    with store.lock:
        _attempt(store, workspace, run_id, attempt_id)
        cleanup_payloads(store, workspace)
        status, content, redacted = 'retained', None, False
        if not store.setting(workspace, 'llm_history', False):
            status = 'Not retained: AI interaction history disabled'
        elif unavailable:
            status = 'Not retained: ' + unavailable
        elif len(body) > MAX_ARTIFACT_BYTES:
            status = 'Not retained: artifact size limit (4 MiB)'
        else:
            try:
                original = body.decode('utf-8')
            except UnicodeError:
                status = 'Not retained: response is not UTF-8 text'
            else:
                content = current_connections().redact(original, secrets)
                content = re.sub(r'(?i)("(?:authorization|password|api[_-]?key|access[_-]?token|refresh[_-]?token|secret)"\s*:\s*)"(?:\\.|[^"\\])*"',
                                 r'\1"[REDACTED]"', content)
                redacted = content != original
        size = len(content.encode('utf-8')) if content is not None else 0
        used = store.rows('''SELECT coalesce(sum(byte_count),0) AS n FROM ai_inspection_artifacts
            WHERE workspace_id=? AND run_id=? AND NOT (attempt_id=? AND kind=?)''',
            [workspace, run_id, attempt_id, kind])[0]['n']
        if size > MAX_ARTIFACT_BYTES or used + size > MAX_RUN_BYTES:
            status, content, size = 'Not retained: capture size limit (4 MiB/artifact, 64 MiB/run)', None, 0
        store.execute('''INSERT INTO ai_inspection_artifacts VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(run_id,attempt_id,kind) DO UPDATE SET content=excluded.content,
            byte_count=excluded.byte_count,status=excluded.status,redacted=excluded.redacted,captured_at=excluded.captured_at''',
            [workspace, run_id, attempt_id, kind, content, size, status, redacted, time()])


def inspection_items(store, workspace, run_id, *, offset=0, limit=20):
    """Page request/attempt metadata only, including planned undispatched requests."""
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Invalid inspection page')
    if not store.rows('SELECT 1 FROM ai_analysis_runs WHERE workspace_id=? AND run_id=?', [workspace, run_id]):
        raise ValueError('Analysis run not found in this workspace')
    query = '''FROM ai_analysis_requests r LEFT JOIN ai_analysis_attempts a
        ON a.workspace_id=r.workspace_id AND a.run_id=r.run_id AND a.batch_id=r.batch_id
        WHERE r.workspace_id=? AND r.run_id=?'''
    total = store.rows('SELECT count(*) AS n ' + query, [workspace, run_id])[0]['n']
    items = store.rows('''SELECT r.batch_id AS request_id,a.attempt_id,
        coalesce(a.status,r.status) AS status,r.unit_ids AS part_ids,
        json_extract_string(r.details,'$.work_kind') AS work_kind,
        json_extract(a.details,'$.attempt_number') AS attempt_number ''' + query +
        ' ORDER BY r.rowid,a.rowid LIMIT ? OFFSET ?', [workspace, run_id, limit, offset])
    return {'total': total, 'items': items, 'has_more': offset + len(items) < total}


def inspection_payload(store, workspace, run_id, attempt_id, kind, *, offset=0, limit=16000):
    """Read only the selected text page. Call explicitly for downloads of retained text."""
    if kind not in KINDS or type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= MAX_ARTIFACT_BYTES:
        raise ValueError('Invalid inspection payload page')
    _attempt(store, workspace, run_id, attempt_id)
    missing = {'status': 'Not retained', 'content': None, 'redacted': False, 'total_chars': 0, 'has_more': False}
    if not store.setting(workspace, 'llm_history', False):
        return {**missing, 'status': 'Not retained: AI interaction history disabled'}
    rows = store.rows('''SELECT status,redacted,captured_at,length(content) AS total_chars,
        substring(content,?,?) AS content FROM ai_inspection_artifacts
        WHERE workspace_id=? AND run_id=? AND attempt_id=? AND kind=?''',
        [offset + 1, limit, workspace, run_id, attempt_id, kind])
    if not rows:
        return missing
    row = rows[0]
    age = min(RETENTION_SECONDS, int(store.setting(workspace, 'llm_retention_days', 30)) * 86400)
    if row['captured_at'] < time() - age:
        return {**missing, 'status': 'Not retained: expired under workspace retention (at most 7 days)'}
    return {**row, 'has_more': offset + len(row['content'] or '') < (row['total_chars'] or 0)}
