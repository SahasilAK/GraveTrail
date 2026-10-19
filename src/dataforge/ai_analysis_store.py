"""Bounded durable project analysis checkpoints and accepted offline facts.

Callers own the publication transaction. No network or parser cache writes occur here.
"""
from __future__ import annotations

import json

from dataforge.asset_identity import source_job
from dataforge.models import ParseResult, stable_id

MAX_JSON_BYTES = 16 * 1024 * 1024
TERMINAL = {'committed', 'blocked', 'failed', 'cancelled', 'stale', 'interrupted'}


def _json(value):
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    if len(encoded.encode('utf-8')) > MAX_JSON_BYTES:
        raise ValueError('AI analysis checkpoint exceeds 16 MB')
    return encoded


def save_run(store, workspace, run_id, *, mode, status='planning', manifest=None,
             configuration=None, summary=None, analysis_run_id=None, accepted_results=None):
    if mode not in {'ai', 'hybrid', 'parser'}:
        raise ValueError('Unknown analysis mode')
    if status not in TERMINAL | {'planning', 'extracting', 'validating', 'reconciling', 'reviewing', 'ready'}:
        raise ValueError('Unknown AI analysis state')
    old = store.rows('SELECT * FROM ai_analysis_runs WHERE run_id=?', [run_id])
    if old and old[0]['workspace_id'] != workspace:
        raise ValueError('Analysis run belongs to another workspace')
    previous = old[0] if old else {}
    accepted = None if accepted_results is None else _json([
        {'metadata': {k: m[k] for k in ('file_id', 'content_hash', 'relative_path', 'extension', 'encoding')},
         'job_id': source_job(m, configuration or json.loads(previous.get('configuration', '{}'))),
         'result': parsed.to_dict()} for m, parsed in accepted_results])
    values = [run_id, workspace, analysis_run_id or previous.get('analysis_run_id'), mode, status,
              _json(manifest) if manifest is not None else previous.get('manifest', '{}'),
              _json(configuration) if configuration is not None else previous.get('configuration', '{}'),
              _json(summary) if summary is not None else previous.get('summary', '{}'),
              accepted if accepted is not None else previous.get('accepted_results', '[]')]
    store.execute('''INSERT INTO ai_analysis_runs
        (run_id,workspace_id,analysis_run_id,mode,status,manifest,configuration,summary,accepted_results)
        VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET
        analysis_run_id=excluded.analysis_run_id,mode=excluded.mode,status=excluded.status,
        manifest=excluded.manifest,configuration=excluded.configuration,summary=excluded.summary,
        accepted_results=excluded.accepted_results,updated_at=now()''', values)


def save_unit_result(store, workspace, run_id, unit_id, *, file_id, content_hash,
                     start_char=0, end_char=0, context_hash='', status='completed', record_id=None, result=None):
    _run(store, workspace, run_id)
    if type(start_char) is not int or type(end_char) is not int or not 0 <= start_char <= end_char:
        raise ValueError('Invalid unit coordinates')
    store.execute('''INSERT INTO ai_analysis_units VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(run_id,unit_id) DO UPDATE SET status=excluded.status,record_id=excluded.record_id,result=excluded.result''',
        [unit_id, workspace, run_id, file_id, content_hash, start_char, end_char, context_hash, status, record_id, _json(result or {})])


def _run(store, workspace, run_id):
    if not store.rows('SELECT 1 FROM ai_analysis_runs WHERE workspace_id=? AND run_id=?', [workspace, run_id]):
        raise ValueError('Analysis run does not belong to workspace')


def active_project_runs(store, workspace=''):
    return store.rows("SELECT run_id,workspace_id,status FROM ai_analysis_runs WHERE status NOT IN "
        "('committed','blocked','failed','cancelled','stale','interrupted')" +
        (' AND workspace_id=?' if workspace else ''), [workspace] if workspace else [])


def recover_interrupted_runs(store):
    """Explicit startup recovery only; never resumes provider work."""
    store.execute("UPDATE ai_analysis_runs SET status='interrupted',updated_at=now() WHERE status NOT IN "
        "('committed','blocked','failed','cancelled','stale','interrupted')")


def save_claim_decisions(store, workspace, run_id, claims, *, supports=()):
    _run(store, workspace, run_id)
    for claim in claims:
        store.execute('''INSERT INTO ai_analysis_claims VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(run_id,claim_id) DO UPDATE SET status=excluded.status,payload=excluded.payload,reasons=excluded.reasons''',
            [claim['claim_id'], workspace, run_id, claim.get('unit_id', ''), claim.get('kind', ''),
             claim.get('status', 'unresolved'), _json(claim.get('payload', {})), _json(claim.get('reasons', []))])
    for support in supports:
        fact_tables = {'edge': ('edges', 'edge_id'), 'usage': ('column_usages', 'usage_id'),
                       'derivation': ('column_derivations', 'derivation_id')}
        if support['fact_type'] not in fact_tables:
            raise ValueError('Support fact type must be edge, usage or derivation')
        claim_id = support.get('claim_id', '')
        if claim_id and not store.rows('SELECT 1 FROM ai_analysis_claims WHERE workspace_id=? AND run_id=? AND claim_id=?',
                                      [workspace, run_id, claim_id]):
            raise ValueError('Support claim does not belong to this run/workspace')
        for kind, (table, key) in fact_tables.items():
            established = store.rows(f'SELECT workspace_id FROM {table} WHERE {key}=?', [support['fact_id']])
            if established and (kind != support['fact_type'] or established[0]['workspace_id'] != workspace):
                raise ValueError('Support fact belongs to a different workspace or fact type')
        sid = support.get('support_id') or stable_id(run_id, support['fact_type'], support['fact_id'],
                                                    support.get('claim_id', ''), support.get('engine', 'ai'))
        store.execute('''INSERT INTO analysis_fact_support VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(support_id) DO NOTHING''', [sid, workspace, run_id, support['fact_type'], support['fact_id'],
            support.get('claim_id', ''), support.get('engine', 'ai'), support.get('record_id'), _json(support.get('payload', {}))])


def inherited_context_sources(store, workspace, file_ids):
    """Carry declaration dependencies with preserved per-file representations."""
    remaining, sources = set(file_ids), {}
    for run in store.rows("SELECT manifest,accepted_results FROM ai_analysis_runs WHERE workspace_id=? AND status='committed' ORDER BY created_at DESC,run_id DESC", [workspace]):
        represented = {item['metadata']['file_id'] for item in json.loads(run['accepted_results'])}
        if remaining & represented:
            manifest = json.loads(run['manifest'])
            for entry in manifest if isinstance(manifest, list) else manifest.get('sources', []):
                sources[(entry['file_id'], entry['content_hash'])] = entry
            remaining -= represented
        if not remaining:
            break
    return list(sources.values())


def load_accepted_file_results(store, workspace, config=None):
    """Latest committed representation per file; stale evidence is never rehydrated."""
    inventory = {m['file_id']: m for m in store.files(workspace)}
    accepted, seen = {}, set()
    for run in store.rows("SELECT * FROM ai_analysis_runs WHERE workspace_id=? AND status='committed' ORDER BY created_at DESC,run_id DESC", [workspace]):
        configuration = json.loads(run['configuration'])
        manifest = json.loads(run['manifest'])
        # The immutable context catalog can cite another file's declarations. Revalidate
        # its evidence as well as the direct source before permitting offline reuse.
        context_current = True
        entries = manifest if isinstance(manifest, list) else manifest.get('sources', [])
        for entry in entries:
            current = inventory.get(entry.get('file_id'))
            if (not current or current['content_hash'] != entry.get('content_hash')
                    or current['relative_path'] != entry.get('path', current['relative_path'])):
                context_current = False
                break
        for item in json.loads(run['accepted_results']):
            saved = item['metadata']
            fid = saved['file_id']
            if fid in seen:
                continue
            seen.add(fid)
            current = inventory.get(fid)
            if (not current or not context_current or (config is not None and configuration != config)
                    or any(current[k] != saved[k] for k in ('content_hash', 'relative_path', 'extension'))
                    or item['job_id'] != source_job(current, config or configuration)):
                continue
            # Verify immutable source bytes still exist and match before reusing evidence.
            store.snapshot_content(current)
            accepted[fid] = (current, ParseResult.from_dict(item['result']))
    return accepted


def accepted_file_ids(store, workspace):
    """Committed scope, including stale items; used to refuse silent scope downgrades."""
    return {item['metadata']['file_id']
        for run in store.rows("SELECT accepted_results FROM ai_analysis_runs WHERE workspace_id=? AND status='committed'", [workspace])
        for item in json.loads(run['accepted_results'])}


def attach_published_support(store, workspace, run_id, results, claims):
    """Bind accepted normalized claims to exact existing published fact rows.

    An absent/ambiguous match remains a reviewable claim, never guessed provenance.
    Call after publication in the same transaction; return the number of matched claims.
    """
    from dataforge.asset_identity import AssetResolver
    from dataforge.models import AssetRef, column_key, operation_ids

    run = store.rows('SELECT configuration FROM ai_analysis_runs WHERE workspace_id=? AND run_id=?', [workspace, run_id])
    if not run:
        raise ValueError('Analysis run does not belong to workspace')
    config = json.loads(run[0]['configuration'])
    resolver = AssetResolver(workspace, results, config)
    operations = {}
    for metadata, parsed in results:
        for index, operation in enumerate(parsed.operations):
            if operation.evidence_key:
                operations[(metadata['file_id'], operation.evidence_key)] = (metadata, parsed, index, operation)
    supports = []
    for claim in claims:
        if claim.get('status') != 'accepted':
            continue
        payload = claim.get('payload', {})
        if isinstance(payload, str):
            payload = json.loads(payload)
        evidence = payload.get('evidence', {})
        match = operations.get((evidence.get('file_id'), payload.get('evidence_key')))
        if match is None:
            continue
        metadata, parsed, index, operation = match
        _, oid = operation_ids(workspace, metadata, index, operation)
        kind = payload.get('kind')
        matches = []
        if kind == 'table_edge':
            sources = [ref for ref in operation.sources if resolver.norm(ref.name) == resolver.norm(payload.get('source', ''))]
            targets = [ref for ref in operation.targets if resolver.norm(ref.name) == resolver.norm(payload.get('target', ''))]
            if len(sources) != 1 or len(targets) != 1:
                continue
            source = resolver.resolve(sources[0], metadata, parsed, 'input')[0]
            target = resolver.resolve(targets[0], metadata, parsed, 'output')[0]
            matches = store.rows('SELECT edge_id AS fact_id FROM edges WHERE workspace_id=? AND operation_id=? AND source_id=? AND target_id=?',
                                 [workspace, oid, source, target])
            fact_type = 'edge'
        elif kind == 'direct_usage':
            aid = resolver.resolve(AssetRef(payload.get('table', '')), metadata, parsed)[0]
            matches = store.rows('''SELECT usage_id AS fact_id,column_name FROM column_usages
                WHERE workspace_id=? AND operation_id=? AND asset_id=? AND context=?''',
                [workspace, oid, aid, payload.get('operation', '')])
            matches = [row for row in matches if column_key(row['column_name'], config.get('case_sensitive', False))
                       == column_key(payload.get('column', ''), config.get('case_sensitive', False))]
            fact_type = 'usage'
        elif kind == 'derivation':
            if payload.get('scope'):
                anchor = operation.targets[0] if operation.targets else operation.sources[0]
                aid = resolver.resolve(anchor, metadata, parsed, 'output' if operation.targets else 'reference')[0]
            else:
                targets = [ref for ref in operation.targets if resolver.norm(ref.name) == resolver.norm(payload.get('table', ''))]
                if len(targets) != 1:
                    continue
                aid = resolver.resolve(targets[0], metadata, parsed, 'output')[0]
            matches = store.rows('''SELECT d.derivation_id AS fact_id FROM column_derivations d
                JOIN column_references c ON d.target_column_id=c.column_id AND d.workspace_id=c.workspace_id
                WHERE d.workspace_id=? AND d.operation_id=? AND c.asset_id=? AND c.column_key=?
                AND c.scope=? AND c.version=? AND d.branch=? AND d.ordinal=? AND d.expression=?''',
                [workspace, oid, aid, column_key(payload.get('column', ''), config.get('case_sensitive', False)),
                 payload.get('scope', ''), str(payload.get('version', '')), payload.get('branch', 0),
                 payload.get('ordinal', 0), payload.get('expression', '')])
            fact_type = 'derivation'
        else:
            continue
        if len(matches) != 1:
            continue
        supports.append({'fact_type': fact_type, 'fact_id': matches[0]['fact_id'],
            'claim_id': claim['claim_id'], 'engine': payload.get('origin', 'ai'),
            'record_id': claim.get('record_id') or payload.get('record_id') or None,
            'payload': {'evidence_key': operation.evidence_key, 'unit_id': payload.get('unit_id', '')}})
    save_claim_decisions(store, workspace, run_id, [], supports=supports)
    return len(supports)


def refresh_published_support(store, workspace, results):
    """Rebind durable accepted evidence to this committed graph, pruning stale IDs."""
    store.execute('DELETE FROM analysis_fact_support WHERE workspace_id=?', [workspace])
    count = 0
    for run in store.rows("SELECT run_id FROM ai_analysis_runs WHERE workspace_id=? AND status='committed'", [workspace]):
        claims = store.rows("SELECT * FROM ai_analysis_claims WHERE workspace_id=? AND run_id=? AND status='accepted'",
                            [workspace, run['run_id']])
        count += attach_published_support(store, workspace, run['run_id'], results, claims)
    return count


def load_analysis_report(store, workspace, run_id=None):
    rows = store.rows('SELECT * FROM ai_analysis_runs WHERE workspace_id=?' +
                     (' AND run_id=?' if run_id else '') + ' ORDER BY created_at DESC,run_id DESC LIMIT 1',
                     [workspace, run_id] if run_id else [workspace])
    if not rows:
        return None
    row = rows[0]
    result = {k: v for k, v in row.items() if k != 'accepted_results'}
    for key in ('manifest', 'configuration', 'summary'):
        result[key] = json.loads(result[key])
    result['units'] = store.rows('SELECT * EXCLUDE(result) FROM ai_analysis_units WHERE workspace_id=? AND run_id=?', [workspace, row['run_id']])
    result['claims'] = store.rows('SELECT * FROM ai_analysis_claims WHERE workspace_id=? AND run_id=?', [workspace, row['run_id']])
    for claim in result['claims']:
        for key in ('payload', 'reasons'):
            claim[key] = json.loads(claim[key])
    return result
