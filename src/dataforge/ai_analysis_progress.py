"""Lightweight projections of the durable AI ledger; never hydrate source or results."""
from __future__ import annotations

import json
from collections import Counter


def analysis_progress(store, workspace, run_id):
    with store.lock:
        return _analysis_progress(store, workspace, run_id)


def _analysis_progress(store, workspace, run_id):
    fields = ('parts', 'completion_work', 'consolidation_work', 'recovery_queue', 'unresolved_work',
              'reused_part_ids', 'activity', 'stage', 'initial_estimate', 'current_activity')
    columns = ','.join(f"json_extract(summary,'$.{key}') AS {key}" for key in fields)
    rows = store.rows(f'SELECT status,{columns} FROM ai_analysis_runs WHERE workspace_id=? AND run_id=?',
                      [workspace, run_id])
    if not rows:
        raise ValueError('Analysis run not found in this workspace')
    row = rows[0]
    summary = {key: json.loads(row[key]) if row[key] is not None else None for key in fields}
    planned = {p['part_id']: p for p in summary['parts'] or []}
    for key in ('completion_work', 'consolidation_work'):
        planned.update({w['part']['part_id']: w['part'] for w in summary[key] or []})
    units = store.rows("""SELECT unit_id,file_id,status,context_hash,
        json_extract_string(result,'$.extraction.processed') AS processed
        FROM ai_analysis_units WHERE workspace_id=? AND run_id=?""", [workspace, run_id])
    completed = {u['unit_id'] for u in units if u['status'] == 'completed' and u['context_hash'] == 'extraction5'}
    superseded = {u['unit_id'] for u in units if u['status'] == 'superseded'}
    planned = {key: value for key, value in planned.items() if key not in superseded}
    selected = {p['file_id'] for p in planned.values()}
    finished_files = {u['file_id'] for u in units if u['unit_id'].startswith('file5:') and u['processed'] == 'true'}
    touched = {u['file_id'] for u in units if u['unit_id'] in completed or u['unit_id'].startswith('file5:')}
    partial = (touched & selected) - finished_files
    requests = store.rows('SELECT batch_id,status,unit_ids,details FROM ai_analysis_requests WHERE workspace_id=? AND run_id=? ORDER BY rowid', [workspace, run_id])
    attempts = store.rows('SELECT attempt_id,batch_id,status,reserved_output,details FROM ai_analysis_attempts WHERE workspace_id=? AND run_id=? ORDER BY rowid', [workspace, run_id])
    states = Counter(a['status'] for a in attempts)
    terminal = row['status'] in {'committed', 'cancelled', 'failed', 'interrupted', 'stale', 'awaiting_continuation', 'blocked'}
    in_flight = [] if terminal else [a for a in attempts if a['status'] == 'dispatched']
    active_ids = {a['batch_id'] for a in in_flight}
    current = None
    if in_flight:
        attempt = in_flight[-1]
        req = next(r for r in requests if r['batch_id'] == attempt['batch_id'])
        ids = json.loads(req['unit_ids'])
        current = {'request_id': req['batch_id'], 'attempt_id': attempt['attempt_id'], 'part_ids': ids,
                   'file_ids': sorted({planned[p]['file_id'] for p in ids if p in planned}),
                   'started_at': json.loads(attempt['details']).get('started_at')}
    reported = {'input': [], 'output': []}
    for attempt in attempts:
        usage = json.loads(attempt['details']).get('usage', {})
        for key, aliases in {'input': ('input_tokens', 'prompt_tokens', 'promptTokenCount'),
                             'output': ('output_tokens', 'completion_tokens', 'candidatesTokenCount')}.items():
            reported[key].append(next((usage[a] for a in aliases if type(usage.get(a)) is int), None))
    tokens = {'estimated_input': (summary['initial_estimate'] or {}).get('input_tokens'),
              'reserved_output': sum(a['reserved_output'] for a in attempts)}
    for key, values in reported.items():
        tokens['actual_' + key] = sum(values) if values and all(v is not None for v in values) else None
        tokens['reported_' + key] = sum(v for v in values if v is not None)
    kinds = {}
    for kind in sorted({p['work_kind'] for p in planned.values()}):
        ids = {key for key, p in planned.items() if p['work_kind'] == kind}
        kinds[kind] = {'planned': len(ids), 'completed': len(ids & completed)}
    return {'run_id': run_id, 'status': row['status'], 'stage': summary['stage'] or row['status'],
        'files': {'selected': len(selected) if selected else None, 'completed': len(finished_files),
                  'partial': len(partial), 'unfinished': len(selected - finished_files - partial) if selected else None},
        'parts': {'planned': len(planned) if selected else None, 'completed': len(completed & planned.keys()),
                  'reused': len(set(summary['reused_part_ids'] or []) & completed),
                  'unresolved': len(summary['unresolved_work'] or {}),
                  'remaining': len(planned.keys() - completed)},
        'requests': {'planned': len(requests), 'queued': sum(r['status'] == 'planned' and r['batch_id'] not in active_ids for r in requests),
                     'in_flight': len(active_ids), 'processed': sum(r['status'] == 'processed' for r in requests)},
        'attempts': {'in_flight': len(in_flight), 'received': states['received'], 'failed': states['known_failure'],
                     'unknown': states['unknown'] + (states['dispatched'] if terminal else 0)},
        'recovery_pending': len(summary['recovery_queue'] or {}), 'tokens': tokens,
        'initial_estimate': summary['initial_estimate'], 'stages': kinds,
        'current': current, 'activity': summary['activity'] or [], 'current_activity': summary['current_activity']}
