"""Bounded durable project analysis checkpoints and accepted offline facts.

Callers own the publication transaction. No network or parser cache writes occur here.
"""
from __future__ import annotations

import json

from dataforge.asset_identity import source_job
from dataforge.models import ParseResult, stable_id

MAX_JSON_BYTES = 16 * 1024 * 1024
TERMINAL = {'committed', 'blocked', 'failed', 'cancelled', 'stale', 'interrupted', 'awaiting_continuation'}


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
    old = store.rows('SELECT workspace_id,configuration,summary FROM ai_analysis_runs WHERE run_id=?', [run_id])
    if old and old[0]['workspace_id'] != workspace:
        raise ValueError('Analysis run belongs to another workspace')
    previous = old[0] if old else {}
    accepted = None
    if accepted_results is not None:
        accepted = '[]'
        config = configuration or json.loads(previous.get('configuration', '{}'))
        store.execute('DELETE FROM ai_analysis_snapshots WHERE workspace_id=? AND run_id=?', [workspace, run_id])
        for metadata, parsed in accepted_results:
            header = {'metadata': {k: metadata[k] for k in
                ('file_id', 'content_hash', 'relative_path', 'extension', 'encoding')},
                'job_id': source_job(metadata, config), 'result': parsed.to_dict()}
            operations = header['result'].pop('operations')
            _save_snapshot_part(store, workspace, run_id, metadata, 0, header)
            source = store.snapshot_content(metadata)
            for index, operation in enumerate(operations, 1):
                code = operation.pop('code')
                start = source.find(code, sum(len(line) for line in source.splitlines(keepends=True)[:max(0, operation['start'] - 1)]))
                if start < 0:
                    raise ValueError('Accepted operation differs from immutable original source')
                operation['source_span'] = [start, start + len(code)]
                _save_snapshot_part(store, workspace, run_id, metadata, index, operation)
    if old:
        updates = {'mode': mode, 'status': status}
        if manifest is not None:
            updates['manifest'] = _json(manifest)
        if configuration is not None:
            updates['configuration'] = _json(configuration)
        if summary is not None:
            updates['summary'] = _json({**json.loads(previous['summary']), **summary})
        if analysis_run_id is not None:
            updates['analysis_run_id'] = analysis_run_id
        if accepted is not None:
            updates['accepted_results'] = accepted
        store.execute('UPDATE ai_analysis_runs SET ' + ','.join(key + '=?' for key in updates)
            + ',updated_at=now() WHERE workspace_id=? AND run_id=?', [*updates.values(), workspace, run_id])
        return
    values = [run_id, workspace, analysis_run_id or previous.get('analysis_run_id'), mode, status,
              _json(manifest) if manifest is not None else previous.get('manifest', '{}'),
              _json(configuration) if configuration is not None else previous.get('configuration', '{}'),
              _json({**json.loads(previous.get('summary', '{}')), **summary}) if summary is not None else previous.get('summary', '{}'),
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
        "('committed','blocked','failed','cancelled','stale','interrupted','awaiting_continuation')" +
        (' AND workspace_id=?' if workspace else ''), [workspace] if workspace else [])


def recover_interrupted_runs(store):
    """Explicit startup recovery only; never resumes provider work."""
    store.execute("UPDATE ai_analysis_runs SET status='interrupted',updated_at=now() WHERE status NOT IN "
        "('committed','blocked','failed','cancelled','stale','interrupted','awaiting_continuation')")


def save_claim_decisions(store, workspace, run_id, claims, *, supports=()):
    _run(store, workspace, run_id)
    source_cache = {}
    for claim in claims:
        payload = claim.get('payload', {})
        evidence = payload.get('evidence') if isinstance(payload, dict) else None
        if isinstance(evidence, dict) and 'quote' in evidence:
            from dataforge.ai_analysis_models import EvidenceCitation
            citation = EvidenceCitation.model_validate(evidence)
            if citation.file_id not in source_cache:
                metadata = store.file(citation.file_id)
                if metadata['workspace_id'] != workspace or metadata['content_hash'] != citation.content_hash:
                    raise ValueError('Claim source identity changed')
                source_cache[citation.file_id] = metadata['encoding'], store.snapshot_content(metadata)
            encoding, code = source_cache[citation.file_id]
            if code[citation.start_offset:citation.end_offset] != citation.quote:
                raise ValueError('Claim citation differs from immutable source')
            payload = {**payload, 'evidence': {k: v for k, v in evidence.items() if k != 'quote'},
                       '_evidence_reference_version': 2, '_source_encoding': encoding}
        store.execute('''INSERT INTO ai_analysis_claims VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(run_id,claim_id) DO UPDATE SET status=excluded.status,payload=excluded.payload,reasons=excluded.reasons''',
            [claim['claim_id'], workspace, run_id, claim.get('unit_id', ''), claim.get('kind', ''),
             claim.get('status', 'unresolved'), _json(payload), _json(claim.get('reasons', []))])
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
    for run in store.rows("SELECT run_id,manifest,accepted_results FROM ai_analysis_runs WHERE workspace_id=? AND status='committed' ORDER BY created_at DESC,run_id DESC", [workspace]):
        represented = {item['metadata']['file_id'] for item in _accepted_items(store, workspace, run, hydrate=False)}
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
        for item in _accepted_items(store, workspace, run, hydrate=False):
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
            saved_item = next(x for x in _accepted_items(store, workspace, run, file_id=fid) if x['metadata']['file_id'] == fid)
            accepted[fid] = (current, ParseResult.from_dict(saved_item['result']))
    return accepted


def accepted_file_ids(store, workspace):
    """Committed scope, including stale items; used to refuse silent scope downgrades."""
    return {item['metadata']['file_id']
        for run in store.rows("SELECT run_id,accepted_results FROM ai_analysis_runs WHERE workspace_id=? AND status='committed'", [workspace])
        for item in _accepted_items(store, workspace, run, hydrate=False)}


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


def load_analysis_report(store, workspace, run_id=None, *, include_source=True):
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
    result['claims'] = store.rows("SELECT * FROM ai_analysis_claims WHERE workspace_id=? AND run_id=? AND kind != 'checkpoint'", [workspace, row['run_id']])
    quotes = {}
    for claim in result['claims']:
        claim['reasons'] = json.loads(claim['reasons'])
        if not include_source:
            claim.pop('payload', None)
            continue
        claim['payload'] = json.loads(claim['payload'])
        payload = claim['payload']
        if payload.pop('_evidence_reference_version', None) == 2:
            encoding = payload.pop('_source_encoding')
            evidence = payload['evidence']
            key = (evidence['content_hash'], encoding, evidence['start_offset'], evidence['end_offset'])
            if key not in quotes:
                source = store.snapshot_content({'content_hash': key[0], 'encoding': encoding})
                if not 0 <= key[2] < key[3] <= len(source):
                    raise ValueError('Claim reference is outside original source')
                quotes[key] = source[key[2]:key[3]]
            evidence['quote'] = quotes[key]
    return result


def _save_snapshot_part(store, workspace, run_id, metadata, part, payload):
    store.execute('INSERT INTO ai_analysis_snapshots VALUES (?,?,?,?,?,?)',
        [run_id, workspace, metadata['file_id'], part, metadata['content_hash'], _json(payload)])


def _accepted_items(store, workspace, run, *, hydrate=True, file_id=None):
    where = 'workspace_id=? AND run_id=?'
    args = [workspace, run['run_id']]
    if file_id is not None:
        where += ' AND file_id=?'
        args.append(file_id)
    if not hydrate:
        where += ' AND part=0'
    rows = store.rows('SELECT file_id,part,content_hash,payload FROM ai_analysis_snapshots WHERE '
                     + where + ' ORDER BY file_id,part', args)
    if not rows:
        yield from json.loads(run['accepted_results'])
        return
    current = None
    source = None
    for row in rows:
        payload = json.loads(row['payload'])
        if row['part'] == 0:
            if current is not None:
                yield current
            current = payload
            current['result']['operations'] = []
            source = store.snapshot_content(current['metadata']) if hydrate else None
        elif current is not None and current['metadata']['file_id'] == row['file_id']:
            start, end = payload.pop('source_span')
            if not hydrate:
                continue
            if not 0 <= start < end <= len(source):
                raise ValueError('Invalid accepted operation reference')
            payload['code'] = source[start:end]
            current['result']['operations'].append(payload)
        else:
            raise ValueError('Incomplete accepted file snapshot')
    if current is not None:
        yield current


def save_validation_checkpoint(store, workspace, run_id, unit, context_hash, validated, *, reviewed=False,
                               record_id=None, cache=None):
    """Only locally validated claims survive; no rejected provider body is retained."""
    header = validated.model_dump(exclude={'accepted'})
    # Minimal host operation shapes; source text is referenced, never copied per claim.
    for asset in header['assets']:
        _compact_host(asset)
    for group in ('rejected', 'unresolved'):
        for decision in header[group]:
            decision['evidence'] = None
    accepted_ids = []
    with store.transaction():
        for fact in validated.accepted:
            payload = fact.model_dump()
            payload['evidence'] = {'unit_id': unit.unit_id}
            _compact_host(payload['detail'])
            accepted_ids.append(fact.candidate_id)
            save_claim_decisions(store, workspace, run_id, [{'claim_id': 'stage:' + fact.candidate_id,
                'unit_id': unit.unit_id, 'kind': 'checkpoint', 'status': 'staged', 'payload': payload}])
        header.update(accepted_ids=accepted_ids, reviewed=reviewed, cache=cache, checkpoint_version=2)
        save_unit_result(store, workspace, run_id, unit.unit_id, file_id=unit.file_id,
            content_hash=unit.content_hash, start_char=unit.start_offset, end_char=unit.end_offset,
            context_hash=context_hash, status='staged', record_id=record_id, result=header)


def _compact_host(detail):
    if detail.get('operation'):
        detail['operation'] = {k: v for k, v in detail['operation'].items()
                               if k not in {'code', 'usages', 'derivations'}}


def load_validation_checkpoint(store, workspace, run_id, unit, context_hash):
    from dataforge.ai_analysis_models import EvidenceCitation, ValidationReport
    rows = store.rows('SELECT * FROM ai_analysis_units WHERE workspace_id=? AND run_id=? AND unit_id=?',
                      [workspace, run_id, unit.unit_id])
    if not rows:
        return None
    row = rows[0]
    if (row['context_hash'] != context_hash or row['content_hash'] != unit.content_hash
            or row['file_id'] != unit.file_id):
        raise ValueError('source_or_configuration_changed')
    header = json.loads(row['result'])
    if header.get('checkpoint_version') != 2:
        return None
    source = store.snapshot_content(store.file(unit.file_id))
    def hydrate(detail):
        if detail.get('operation'):
            start, end = detail['operation_span']
            if not unit.start_offset <= start < end <= unit.end_offset:
                raise ValueError('Checkpoint operation outside immutable unit')
            detail['operation']['code'] = source[start:end]
    for asset in header['assets']:
        hydrate(asset)
    claims = {r['claim_id'][6:]: json.loads(r['payload']) for r in store.rows(
        "SELECT claim_id,payload FROM ai_analysis_claims WHERE workspace_id=? AND run_id=? AND unit_id=? AND kind='checkpoint'",
        [workspace, run_id, unit.unit_id])}
    accepted = []
    for cid in header['accepted_ids']:
        payload = claims[cid]
        payload['evidence'] = EvidenceCitation.from_unit(unit).model_dump()
        hydrate(payload['detail'])
        accepted.append(payload)
    validated = ValidationReport.model_validate({k: v for k, v in header.items()
        if k in ValidationReport.model_fields} | {'accepted': accepted})
    return validated, header['reviewed'], row['record_id'], header.get('cache')
