"""Coordinator-owned durable requests; no provider credentials or copied source."""
from __future__ import annotations

import json
import uuid

from dataforge.ai_analysis_store import _json, _run

PIPELINE_SCHEMA = '''
CREATE TABLE ai_analysis_requests(batch_id VARCHAR PRIMARY KEY, workspace_id VARCHAR,
    run_id VARCHAR, unit_ids VARCHAR, status VARCHAR, details VARCHAR);
CREATE INDEX ai_requests_run ON ai_analysis_requests(workspace_id,run_id,status);
CREATE TABLE ai_analysis_attempts(attempt_id VARCHAR PRIMARY KEY, workspace_id VARCHAR,
    run_id VARCHAR, batch_id VARCHAR, reserved_output BIGINT, status VARCHAR, details VARCHAR);
CREATE INDEX ai_attempts_run ON ai_analysis_attempts(workspace_id,run_id,status);
CREATE TABLE ai_context_dependencies(workspace_id VARCHAR, run_id VARCHAR, unit_id VARCHAR,
    dependencies VARCHAR, PRIMARY KEY(run_id,unit_id));
CREATE TABLE ai_link_checkpoints(workspace_id VARCHAR, run_id VARCHAR, fingerprint VARCHAR,
    report VARCHAR, PRIMARY KEY(run_id));
'''


def save_request(store, workspace, run_id, batch_id, unit_ids, *, details=None):
    _run(store, workspace, run_id)
    previous = store.rows('SELECT workspace_id,run_id FROM ai_analysis_requests WHERE batch_id=?', [batch_id])
    if previous and previous[0] != {'workspace_id': workspace, 'run_id': run_id}:
        raise ValueError('Request belongs to another run')
    store.execute('INSERT INTO ai_analysis_requests VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING',
        [batch_id, workspace, run_id, _json(unit_ids), 'planned', _json(details or {})])


def begin_attempt(store, workspace, run_id, batch_id, reserved_output, *, details=None):
    _run(store, workspace, run_id)
    if not store.rows('SELECT 1 FROM ai_analysis_requests WHERE workspace_id=? AND run_id=? AND batch_id=?',
                      [workspace, run_id, batch_id]):
        raise ValueError('Request does not belong to run/workspace')
    if type(reserved_output) is not int or reserved_output < 1:
        raise ValueError('Invalid output reservation')
    ticket = uuid.uuid4().hex
    store.execute('INSERT INTO ai_analysis_attempts VALUES (?,?,?,?,?,?,?)',
                  [ticket, workspace, run_id, batch_id, reserved_output, 'dispatched', _json(details or {})])
    return ticket


def finish_attempt(store, workspace, run_id, ticket, status, *, details=None):
    _run(store, workspace, run_id)
    if status not in {'received', 'known_failure', 'unknown'}:
        raise ValueError('Invalid attempt outcome')
    rows = store.rows('SELECT status,details FROM ai_analysis_attempts WHERE workspace_id=? AND run_id=? AND attempt_id=?',
                      [workspace, run_id, ticket])
    if not rows:
        raise ValueError('Attempt does not belong to run/workspace')
    if rows[0]['status'] not in {'dispatched', status}:
        raise ValueError('Attempt already completed with another outcome')
    store.execute('UPDATE ai_analysis_attempts SET status=? WHERE attempt_id=?', [status, ticket])
    if details is not None:
        store.execute('UPDATE ai_analysis_attempts SET details=? WHERE attempt_id=?',
            [_json({**json.loads(rows[0]['details']), **details}), ticket])


def attempt_totals(store, workspace, run_id):
    """Recover conservative lifetime counters independently of the summary write."""
    _run(store, workspace, run_id)
    rows = store.rows('SELECT reserved_output,details FROM ai_analysis_attempts WHERE workspace_id=? AND run_id=?', [workspace, run_id])
    requests, reserved = len(rows), sum(row['reserved_output'] for row in rows)
    for row in rows:
        detail = json.loads(row['details'])
        requests = max(requests, detail.get('lifetime_attempts', 0))
        reserved = max(reserved, detail.get('lifetime_reserved_output', 0))
    return requests, reserved


def reported_totals(store, workspace, run_id):
    totals = {'input_tokens': 0, 'output_tokens': 0}
    for row in store.rows('SELECT details FROM ai_analysis_attempts WHERE workspace_id=? AND run_id=?', [workspace, run_id]):
        usage = json.loads(row['details']).get('usage', {})
        for key, aliases in {'input_tokens': ('input_tokens', 'prompt_tokens', 'promptTokenCount'),
                             'output_tokens': ('output_tokens', 'completion_tokens', 'candidatesTokenCount')}.items():
            totals[key] += next((usage[a] for a in aliases if type(usage.get(a)) is int), 0)
    return totals


def recover_pipeline(store, workspace, run_id):
    _run(store, workspace, run_id)
    rows = store.rows("""SELECT a.* FROM ai_analysis_attempts a JOIN ai_analysis_requests r
        ON a.batch_id=r.batch_id AND a.run_id=r.run_id AND a.workspace_id=r.workspace_id
        WHERE a.workspace_id=? AND a.run_id=? AND r.status<>'processed' AND (a.status IN ('dispatched','unknown')
        OR (a.status='received' AND r.status='planned'))""", [workspace, run_id])
    return {'unknown': [r for r in rows if not json.loads(r['details']).get('retry_authorized')]}


def batch_attempts(store, workspace, run_id, batch_id):
    rows = store.rows('SELECT * FROM ai_analysis_attempts WHERE workspace_id=? AND run_id=? AND batch_id=?',
                     [workspace, run_id, batch_id])
    return sorted(rows, key=lambda r: (json.loads(r['details']).get('attempt_number', 0), r['attempt_id']))


def save_context_dependencies(store, workspace, run_id, unit_id, dependencies):
    _run(store, workspace, run_id)
    store.execute('INSERT INTO ai_context_dependencies VALUES (?,?,?,?) ON CONFLICT(run_id,unit_id) DO UPDATE SET dependencies=excluded.dependencies',
        [workspace, run_id, unit_id, _json(dependencies)])


def save_link_checkpoint(store, workspace, run_id, fingerprint, report):
    _run(store, workspace, run_id)
    store.execute('INSERT INTO ai_link_checkpoints VALUES (?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET fingerprint=excluded.fingerprint,report=excluded.report',
        [workspace, run_id, fingerprint, _json(report)])
