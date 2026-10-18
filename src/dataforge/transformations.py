"""Scoped static column derivations and bounded traversal, shared by every interface."""
from __future__ import annotations

import copy
import json
from collections import deque

from networkx import DiGraph, strongly_connected_components

from dataforge.configuration import ParsingSettings
from dataforge.models import AssetRef, canonical, stable_id

ROW_ROLES = {'row_filter', 'join'}
STATUSES = {'all', 'verified', 'inferred', 'unresolved'}


def column_key(name, case_sensitive=False):
    # Quoted identifiers retain their case; unquoted names follow workspace rules.
    return name.strip() if case_sensitive or name.startswith(('"', '`', '[')) else canonical(name)


def materialize_columns(workspace, run_id, results, resolver, schemas, config):
    rows = {'column_references': [], 'column_derivations': [], 'column_dependencies': []}
    references = {}
    for metadata, parsed in results:
        fid = metadata['file_id']
        for op_index, op in enumerate(parsed.operations):
            if op.method == 'llm':
                continue
            sid = stable_id(workspace, fid, str(op_index), metadata['content_hash'])
            oid = stable_id(sid, op.kind)
            outputs = {resolver.norm(t.name): resolver.resolve(t, metadata, parsed, 'output')[0]
                       for t in op.targets}

            def reference(table, name, scope='', version='', output=False):
                if scope:
                    # Scope records live under their output asset without polluting table lineage.
                    anchor = next(iter(outputs.values()), None)
                    if anchor is None:
                        anchor = resolver.resolve(op.sources[0], metadata, parsed)[0]
                    aid, inferred = anchor, False
                else:
                    aid = outputs.get(resolver.norm(table)) if output else None
                    if aid is None:
                        aid, inferred = resolver.resolve(AssetRef(table), metadata, parsed)
                    else:
                        inferred = False
                key = column_key(name, config['case_sensitive'])
                cid = stable_id(workspace, aid, key, sid if scope or version else '', scope, version)
                if not scope:
                    table = resolver.registry[aid][2]
                references[cid] = [cid, workspace, aid, table, name, key, scope, version]
                return cid, inferred or resolver.registry[aid][4] == 'unresolved'

            derivations = []
            for original in op.derivations:
                d = copy.deepcopy(original)
                # Only a single plain wildcard with consistent imported DDL has a stable order.
                if d.get('category') == 'wildcard' and d.get('wildcard_safe') and config['expand_wildcards']:
                    inputs = [i for i in d['inputs'] if i['role'] == 'value']
                    schema = None
                    if len(inputs) == 1 and not inputs[0].get('scope'):
                        aid, _ = resolver.resolve(AssetRef(inputs[0]['table']), metadata, parsed)
                        schema = schemas.get(aid)
                    if schema and schema.get('schema_status') == 'declared':
                        for position, col in enumerate(schema['columns']):
                            expanded = copy.deepcopy(d)
                            gaps = [c for c in d.get('coverage', [])
                                    if c != 'Wildcard requires trusted schema expansion']
                            expanded.update(target_column=col['name'], status='unresolved' if gaps else 'inferred',
                                            ordinal=d.get('ordinal', 0) + position,
                                            coverage=[*gaps, 'Expanded from imported DDL; runtime schema is unverified'])
                            for item in expanded['inputs']:
                                if item['role'] == 'value':
                                    item['column'] = col['name']
                            derivations.append(expanded)
                        continue
                # Explicit INSERT target DDL is an inferred positional mapping.
                if d.get('target_mapping_missing') and config['expand_wildcards']:
                    aid = outputs.get(resolver.norm(d['target_table']))
                    schema = schemas.get(aid, {})
                    columns = schema.get('columns', [])
                    if schema.get('schema_status') == 'declared' and len(columns) == d.get('projection_count'):
                        mapping_gaps = {'INSERT target column mapping requires an explicit list or trusted schema',
                                        'Output and projection cardinality mismatch',
                                        'Output column name cannot be established'}
                        gaps = [c for c in d.get('coverage', []) if c not in mapping_gaps]
                        d.update(target_column=columns[d['ordinal']]['name'], status='unresolved' if gaps else 'inferred',
                                 coverage=[*gaps, 'INSERT target mapped from imported DDL; runtime schema is unverified'])
                derivations.append(d)
            for index, d in enumerate(derivations):
                target, inferred = reference(d['target_table'], d['target_column'], d.get('scope', ''),
                                             d.get('target_version', ''), output=True)
                did = stable_id(oid, str(index), target, str(d.get('branch', 0)))
                status = d.get('status', 'unresolved')
                if inferred and status == 'verified':
                    status = 'inferred'
                dependencies = []
                for ordinal, item in enumerate(d.get('inputs', [])):
                    cid, uncertain = reference(item['table'], item.get('column', ''), item.get('scope', ''),
                                                item.get('version', ''))
                    if uncertain and status == 'verified':
                        status = 'inferred'
                    dependencies.append([stable_id(did, str(ordinal)), workspace, did, cid,
                                         item.get('role', 'value'), ordinal])
                rows['column_derivations'].append([did, workspace, target, d.get('expression', ''),
                    d.get('category', 'unknown'), status, sid, fid, oid, run_id,
                    d.get('branch', 0), d.get('ordinal', index), json.dumps(d.get('coverage', []))])
                rows['column_dependencies'].extend(dependencies)
    rows['column_references'] = list(references.values())
    return rows


def _asset(store, workspace, asset_id):
    if not store.rows('SELECT 1 FROM assets WHERE workspace_id=? AND asset_id=?', [workspace, asset_id]):
        raise ValueError('Asset does not exist in this workspace')


def column_catalog(store, workspace, asset_id, limit=500):
    if type(limit) is not int or not 1 <= limit <= 20000:
        raise ValueError('Column catalog limit must be 1–20000')
    with store.lock:
        _asset(store, workspace, asset_id)
        return store.rows('''SELECT column_id,asset_id,table_name AS "table",column_name,scope,version
            FROM column_references WHERE workspace_id=? AND asset_id=?
            ORDER BY scope,column_key,version,column_id LIMIT ?''', [workspace, asset_id, limit])


def _ref(row):
    return {k: row[k] for k in ('column_id', 'asset_id', 'column_name', 'scope', 'version')} | {'table': row['table_name']}


def trace_columns(store, workspace, asset_id, column, direction='upstream', depth=5, limit=200,
                  status='all', include_source=False):
    if direction not in {'upstream', 'downstream'} or status not in STATUSES:
        raise ValueError('Invalid direction or status')
    if type(depth) is not int or not 1 <= depth <= 30 or type(limit) is not int or not 1 <= limit <= 20000:
        raise ValueError('Use depth 1–30 and limit 1–20000')
    if not isinstance(column, str) or not column.strip() or len(column) > 1024:
        raise ValueError('Select a column name or exact column ID')
    with store.lock:
        _asset(store, workspace, asset_id)
        return _trace(store, workspace, asset_id, column, direction, depth, limit, status, include_source)


def _trace(store, w, aid, column, direction, depth, limit, status, include_source):
    analysis = store.rows('''SELECT c.run_id,r.configuration FROM column_analysis c JOIN analysis_runs r
        ON c.run_id=r.run_id AND c.workspace_id=r.workspace_id WHERE c.workspace_id=?''', [w])
    result = {'workspace_id': w, 'asset_id': aid, 'column': column, 'direction': direction,
              'depth': depth, 'derivations': [], 'paths': [], 'coverage': [], 'truncated': False,
              'complete': False, 'state': 'not_analyzed', 'run_id': analysis[0]['run_id'] if analysis else None}
    coverage = result['coverage']

    def boundary(reason, **context):
        marker = {'reason': reason, **context}
        if marker not in coverage:
            coverage.append(marker)

    if not analysis:
        boundary('reanalysis_required', message='Analyze sources to establish transformation coverage')
        return result
    run_id = analysis[0]['run_id']
    configuration = json.loads(analysis[0]['configuration'])
    current_settings = ParsingSettings.model_validate({k: store.setting(w, k, default)
        for k, default in ParsingSettings().model_dump().items()}).model_dump()
    if current_settings != configuration:
        boundary('analysis_settings_changed', message='Analyze again to apply changed parsing/identity settings')
    stale = store.rows('''SELECT count(*) AS n FROM source_files f WHERE workspace_id=? AND
        (parsing_status IN ('pending','failed') OR EXISTS (SELECT 1 FROM statements s WHERE
        s.workspace_id=f.workspace_id AND s.file_id=f.file_id AND s.content_hash<>f.content_hash))''', [w])[0]['n']
    if stale:
        boundary('analysis_stale', files=stale)
    diagnostic_count = store.rows("SELECT count(*) AS n FROM diagnostics WHERE workspace_id=? AND severity<>'info'", [w])[0]['n']
    if diagnostic_count:
        boundary('parser_diagnostics', count=diagnostic_count,
                 message='Analysis diagnostics may describe unmapped scopes; inspect Analysis diagnostics')
    case_sensitive = configuration.get('case_sensitive', False)
    candidates = store.rows('''SELECT * FROM column_references WHERE workspace_id=? AND asset_id=?
        AND (column_id=? OR (column_key=? AND scope='' AND version='')) LIMIT 3''',
        [w, aid, column, column_key(column, case_sensitive)])
    if len(candidates) != 1:
        result['state'] = 'unresolved' if len(candidates) > 1 else 'no_known_dependency'
        boundary('ambiguous_column' if candidates else 'column_not_established')
        unknown = store.rows('''SELECT d.derivation_id,d.coverage FROM column_derivations d
            JOIN column_references c ON d.target_column_id=c.column_id AND d.workspace_id=c.workspace_id
            WHERE d.workspace_id=? AND c.asset_id=? AND c.column_name IN ('*','')
            AND d.status='unresolved' LIMIT ?''', [w, aid, limit + 1])
        for item in unknown[:limit]:
            boundary('unresolved_scope', derivation_id=item['derivation_id'], details=json.loads(item['coverage']))
        if unknown:
            result['state'] = 'unresolved'
        if len(unknown) > limit:
            result['truncated'] = True
            boundary('item_limit')
        return result
    root = candidates[0]
    queue = deque([(root['column_id'], 0, 'value', ())])
    scheduled = {(root['column_id'], 'value')}
    discovered_edges = set()
    visited, emitted = set(), set()
    root_rows = []

    def scope_boundaries(column_id):
        gaps = store.rows('''SELECT d.derivation_id,d.coverage,d.statement_id,d.operation_id,
            s.content_hash AS source_hash FROM column_references current
            JOIN column_references scope ON current.workspace_id=scope.workspace_id
                AND current.asset_id=scope.asset_id AND current.scope=scope.scope
            JOIN column_derivations d ON d.target_column_id=scope.column_id AND d.workspace_id=scope.workspace_id
            JOIN statements s ON d.statement_id=s.statement_id AND d.workspace_id=s.workspace_id
            WHERE current.workspace_id=? AND current.column_id=? AND d.run_id=?
                AND scope.column_name IN ('*','') AND d.status='unresolved' LIMIT ?''', [w, column_id, run_id, limit + 1])
        for gap in gaps[:limit]:
            boundary('unresolved_scope', derivation_id=gap['derivation_id'], details=json.loads(gap['coverage']),
                     statement_id=gap['statement_id'], operation_id=gap['operation_id'], source_hash=gap['source_hash'])
        if len(gaps) > limit:
            boundary('item_limit')
            result['truncated'] = True
        return bool(gaps)

    while queue:
        cid, level, effect, ancestors = queue.popleft()
        if cid in ancestors:
            boundary('cycle', column_id=cid)
            continue
        if (cid, effect) in visited:
            continue
        visited.add((cid, effect))
        unknown_writes = scope_boundaries(cid)
        if direction == 'upstream':
            clause, params = 'd.target_column_id=?', [cid]
        else:
            clause = '''EXISTS (SELECT 1 FROM column_dependencies i WHERE i.workspace_id=d.workspace_id
                AND i.derivation_id=d.derivation_id AND i.source_column_id=?)'''
            params = [cid]
        remaining = max(1, limit - len(emitted))
        steps = store.rows('''SELECT d.* EXCLUDE(expression),substr(d.expression,1,12000) AS expression,
            length(d.expression)>12000 AS expression_truncated,s.start_line,s.end_line,s.content_hash AS source_hash,
            f.relative_path,o.method''' + (',substr(s.code,1,12000) AS code,length(s.code)>12000 AS source_truncated'
            if include_source else '') + ''' FROM column_derivations d
            JOIN statements s ON d.statement_id=s.statement_id AND d.workspace_id=s.workspace_id
            JOIN source_files f ON d.file_id=f.file_id AND d.workspace_id=f.workspace_id
            JOIN operations o ON d.operation_id=o.operation_id AND d.workspace_id=o.workspace_id
            WHERE d.workspace_id=? AND d.run_id=? AND ''' + clause + '''
            ORDER BY d.statement_id,d.ordinal,d.branch,d.derivation_id LIMIT ?''', [w, run_id, *params, remaining + 1])
        if not steps:
            continue
        if level >= depth:
            boundary('depth_limit', column_id=cid)
            result['truncated'] = True
            continue
        if len(steps) > remaining:
            boundary('item_limit')
            result['truncated'] = True
            steps = steps[:remaining]
        ambiguous = direction == 'upstream' and len({s['operation_id'] for s in steps}) > 1
        if ambiguous:
            boundary('multiple_writers', column_id=cid, message='Writer order is unknown; alternatives are not chained')
        for step in steps:
            if status != 'all' and step['status'] != status:
                boundary('status_filter', column_id=cid)
                continue
            did = step['derivation_id']
            multiple_writers = ambiguous or unknown_writes
            if direction == 'downstream':
                writers = store.rows('''SELECT DISTINCT operation_id FROM column_derivations
                    WHERE workspace_id=? AND run_id=? AND target_column_id=? LIMIT 2''',
                    [w, run_id, step['target_column_id']])
                multiple_writers = len(writers) > 1 or scope_boundaries(step['target_column_id'])
                if len(writers) > 1:
                    boundary('multiple_writers', column_id=step['target_column_id'],
                             message='Writer order is unknown; downstream chaining stops at this output')
            target = store.rows('SELECT * FROM column_references WHERE workspace_id=? AND column_id=?',
                                [w, step['target_column_id']])[0]
            inputs = store.rows('''SELECT c.*,i.role FROM column_dependencies i JOIN column_references c
                ON i.source_column_id=c.column_id AND i.workspace_id=c.workspace_id
                WHERE i.workspace_id=? AND i.derivation_id=? ORDER BY i.ordinal LIMIT ?''', [w, did, limit + 1])
            if len(inputs) > limit:
                inputs = inputs[:limit]
                boundary('input_limit', derivation_id=did)
                result['truncated'] = True
            if step['expression_truncated']:
                boundary('expression_limit', derivation_id=did)
                result['truncated'] = True
            if level == 0:
                root_rows.append(step)
            for warning in json.loads(step['coverage']):
                boundary('coverage_diagnostic', derivation_id=did, message=warning)
            if step['status'] == 'unresolved':
                boundary('unresolved_derivation', derivation_id=did)
            matched = [i for i in inputs if i['column_id'] == cid]
            next_effect = ('row_selection' if effect == 'row_selection' or any(i['role'] in ROW_ROLES for i in matched)
                           else 'value')
            if did not in emitted:
                if len(emitted) >= limit:
                    boundary('item_limit')
                    result['truncated'] = True
                    queue.clear()
                    break
                evidence_keys = ('file_id', 'statement_id', 'operation_id', 'relative_path',
                                 'start_line', 'end_line', 'source_hash', 'method')
                evidence = {k: step[k] for k in evidence_keys}
                if include_source:
                    # Source is lazy and capped, with exact original statement/version citation.
                    evidence['code'] = step['code'][:12000]
                    evidence['source_truncated'] = step['source_truncated']
                result['derivations'].append({k: step[k] for k in ('derivation_id', 'expression', 'category',
                    'status', 'run_id', 'branch', 'ordinal', 'expression_truncated')} | {'target': _ref(target),
                    'inputs': [_ref(i) | {'role': i['role']} for i in inputs],
                    'evidence': evidence, 'coverage': json.loads(step['coverage'])})
                emitted.add(did)
            if len(result['paths']) < limit * 2:
                result['paths'].append({'derivation_id': did, 'column_id': target['column_id'],
                    'parent_column_id': cid, 'depth': level + 1, 'effect': next_effect})
            else:
                boundary('path_limit')
                result['truncated'] = True
            if not multiple_writers:
                if direction == 'upstream':
                    following = [(i['column_id'], level + 1,
                        'row_selection' if effect == 'row_selection' or i['role'] in ROW_ROLES else 'value',
                        (*ancestors, cid)) for i in inputs]
                else:
                    following = [(target['column_id'], level + 1, next_effect, (*ancestors, cid))]
                for item in following:
                    if len(discovered_edges) < limit * 4:
                        discovered_edges.add((cid, item[0]))
                    else:
                        boundary('cycle_check_limit')
                        result['truncated'] = True
                    if item[0] in item[3]:
                        boundary('cycle', column_id=item[0])
                    elif (item[0], item[2]) not in scheduled:
                        if len(scheduled) >= limit * 2:
                            boundary('item_limit')
                            result['truncated'] = True
                            break
                        scheduled.add((item[0], item[2]))
                        queue.append(item)
        if len(visited) >= limit * 2:
            boundary('item_limit')
            result['truncated'] = True
            break
    discovered = DiGraph()
    discovered.add_edges_from(discovered_edges)
    for component in strongly_connected_components(discovered):
        if len(component) > 1 or any(discovered.has_edge(c, c) for c in component):
            boundary('cycle', column_id=min(component))
    result['state'] = ('unresolved' if any(s['status'] == 'unresolved' for s in root_rows)
                      or any(c['reason'] == 'unresolved_scope' for c in coverage) else
                       'constant' if direction == 'upstream' and root_rows
                       and all(s['category'] == 'constant' for s in root_rows) else
                       'known' if result['derivations'] else 'no_known_dependency')
    result['complete'] = not coverage and not result['truncated']
    return result
