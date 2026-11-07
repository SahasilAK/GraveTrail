"""Scoped static column derivations and bounded traversal, shared by every interface."""
from __future__ import annotations

import copy
import json
from collections import defaultdict, deque
from typing import Any

from networkx import DiGraph, strongly_connected_components
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from dataforge.asset_identity import AssetResolver
from dataforge.configuration import ParsingSettings
from dataforge.models import AssetRef, ParseResult, column_key, operation_ids, stable_id
from dataforge.parsers.sql_transformations import identifier
from dataforge.schemas import query_output_layouts
from dataforge.store import Store

ROW_ROLES = {'row_filter', 'join', 'row_membership', 'quality_drop', 'delete_condition', 'truncate_condition'}
CONTROL_ROLES = {'quality_warn', 'quality_fail', 'match_key', 'sequence', 'system_sequence',
                 'ignore_null_update', 'history'}
STATUSES = {'all', 'verified', 'inferred', 'unresolved'}
INSERT_MAPPING_GAPS = {'INSERT target column mapping requires an explicit list or trusted schema',
                       'Output and projection cardinality mismatch', 'Output column name cannot be established'}


def _sql_name(name: str) -> str:
    return name.removeprefix('"').removesuffix('"').replace('""', '"').casefold()


def _path_effect(effect: str, roles: set[str]) -> str:
    if effect == 'row_selection' or roles & ROW_ROLES:
        return 'row_selection'
    if effect == 'control' or roles & CONTROL_ROLES:
        return 'control'
    return effect


def _struct_members(schema: dict[str, Any], path: list[str]) -> list[str]:
    columns = [c for c in schema['columns'] if c['name'].casefold() == path[0].casefold()]
    if len(columns) != 1:
        return []
    try:
        datatype = exp.DataType.build(columns[0]['type'])
    except (ParseError, TokenError, ValueError):
        return []
    for field in path[1:]:
        if not datatype.is_type(exp.DType.STRUCT):
            return []
        members = [c for c in datatype.expressions if isinstance(c, exp.ColumnDef)
                   and c.name.casefold() == field.casefold()]
        if len(members) != 1 or not isinstance(members[0].kind, exp.DataType):
            return []
        datatype = members[0].kind
    if not datatype.is_type(exp.DType.STRUCT) or not all(isinstance(c, exp.ColumnDef) for c in datatype.expressions):
        return []
    members = [identifier(c.this) for c in datatype.expressions]
    return members if len({_sql_name(name) for name in members}) == len(members) else []


def materialize_columns(workspace: str, run_id: str, results: list[tuple[dict[str, Any], ParseResult]],
                        resolver: AssetResolver, schemas: dict[str, Any], query_layouts: dict[str, list[str]],
                        config: dict[str, Any]) -> dict[str, list[list[Any]]]:
    """Build column lineage rows from parsed operations and known schemas.

    Args:
        workspace: Workspace identifier used in generated row identities.
        run_id: Analysis run identifier attached to derivation rows.
        results: File metadata and parse results to materialize.
        resolver: Resolver used to map table references to assets.
        schemas: Imported schema metadata indexed by asset identifier.
        query_layouts: Output names inferred from single imported query definitions.
        config: Parsing and identity settings used during materialization.

    Returns:
        Row collections for column references, derivations, and dependencies."""
    rows = {'column_references': [], 'column_derivations': [], 'column_dependencies': []}
    references = {}
    for metadata, parsed in results:
        fid = metadata['file_id']
        for op_index, op in enumerate(parsed.operations):
            if op.method == 'llm':
                continue
            sid, oid = operation_ids(workspace, metadata, op_index, op)
            outputs = {t.identity or resolver.norm(t.name): resolver.resolve(t, metadata, parsed, 'output')[0]
                       for t in op.targets}

            def declared(table, identity=''):
                aid, _ = resolver.resolve(AssetRef(table, identity=identity), metadata, parsed)
                schema = schemas.get(aid, {})
                return schema if schema.get('schema_status') == 'declared' else {}

            def read_layout(table, identity=''):
                aid, _ = resolver.resolve(AssetRef(table, identity=identity), metadata, parsed)
                return schemas.get(aid, {}).get('column_identifiers') or query_layouts.get(aid, [])

            def reference(table, name, scope='', version='', output=False, identity=''):
                if scope:
                    # Scope records live under their output asset without polluting table lineage.
                    anchor = next(iter(outputs.values()), None)
                    if anchor is None:
                        anchor = resolver.resolve(op.sources[0], metadata, parsed)[0]
                    aid, inferred = anchor, False
                else:
                    aid = outputs.get(identity or resolver.norm(table)) if output else None
                    if aid is None:
                        aid, inferred = resolver.resolve(AssetRef(table, identity=identity), metadata, parsed)
                    else:
                        inferred = False
                key = column_key(name, config['case_sensitive'])
                cid = stable_id(workspace, aid, key, sid if scope or version else '', scope, version)
                if not scope:
                    table = resolver.registry[aid][2]
                references[cid] = [cid, workspace, aid, table, name, key, scope, version]
                return cid, inferred or resolver.registry[aid][4] == 'unresolved'

            derivations = []
            scoped_layouts = (query_output_layouts(op.derivations, read_layout, config['case_sensitive'])
                              if config['expand_wildcards'] else {})

            def scoped_names(scope):
                return scoped_layouts.get(scope) or [prior['target_column'] for prior in derivations
                                                     if prior.get('scope') == scope]

            union_offsets = defaultdict(int)
            physical = [d for d in op.derivations if not d.get('scope')]
            wildcard_insert = op.kind == 'INSERT' and any(d.get('category') == 'wildcard' for d in physical)
            single_insert_wildcard = (len(physical) == 1 and physical[0].get('target_mapping_missing')
                                      and physical[0].get('projection_count') == 1)
            for original in op.derivations:
                d = copy.deepcopy(original)
                positional_layout = d.get('positional_layout')
                union_layout = scoped_layouts.get(d['scope']) if 'union_projection' in d else None
                if union_layout:
                    offset_key = d['scope'], d['branch']
                    offset = union_offsets[offset_key]
                    d['coverage'] = [gap for gap in d['coverage'] if gap not in {
                        'Set operation wildcard positions require trusted schema expansion',
                        'Output and projection cardinality mismatch', 'Output column name cannot be established',
                    }]
                    if d['category'] != 'wildcard':
                        d.update(target_column=union_layout[offset], ordinal=offset,
                                 status='unresolved' if d['coverage'] else 'inferred')
                        union_offsets[offset_key] += 1
                elif 'union_projection' in d:
                    d['wildcard_safe'] = False
                if (wildcard_insert and not (positional_layout or d.get('target_by_name'))
                        and not d.get('scope') and not single_insert_wildcard):
                    d.update(target_column='*', status='unresolved')
                    d['coverage'].append('INSERT wildcard target layout is unresolved')
                    derivations.append(d)
                    continue
                if d.get('scoped_columns') and config['expand_wildcards']:
                    missing = False
                    for item in d['scoped_columns']:
                        layout = scoped_names(item['scope'])
                        matches = [name for name in layout if column_key(name, config['case_sensitive'])
                                   == column_key(item['column'], config['case_sensitive'])]
                        if len(matches) != 1 or '*' in layout:
                            missing = True
                        else:
                            dependency = {**item, 'column': matches[0]}
                            if dependency not in d['inputs']:
                                d['inputs'].append(dependency)
                    if not missing:
                        d['coverage'].remove('Intermediate wildcard requires a complete output layout')
                        d['status'] = 'unresolved' if d['coverage'] else 'inferred'
                if d.get('unqualified_columns') and config['expand_wildcards']:
                    missing = False
                    for item in d['unqualified_columns']:
                        matches = []
                        for source in item['sources']:
                            if scope := source.get('scope'):
                                names = scoped_names(scope)
                            else:
                                names = read_layout(source['table'], source.get('table_identity', ''))
                            if not names or '*' in names:
                                break
                            for name in names:
                                if column_key(name, config['case_sensitive']) == column_key(item['column'], config['case_sensitive']):
                                    matches.append({**source, 'column': name, 'role': item['role']})
                        else:
                            if len(matches) == 1:
                                if matches[0] not in d['inputs']:
                                    d['inputs'].append(matches[0])
                                continue
                        missing = True
                    if not missing:
                        d['coverage'].remove('Unresolved or ambiguous column ownership requires complete source schemas')
                        d['status'] = 'unresolved' if d['coverage'] else 'inferred'
                choices = d.get('lateral_choices', [])
                if choices and config['expand_wildcards']:
                    unknown = False
                    for choice in choices:
                        schema = declared(choice['table'])
                        if not schema:
                            unknown = True
                            continue
                        matches = [name for name in schema['column_identifiers']
                                   if _sql_name(name) == _sql_name(choice['column'])]
                        if len(matches) > 1:
                            unknown = True
                            continue
                        dependencies = ([{'table': choice['table'], 'column': matches[0], 'role': choice['role']}]
                                        if matches else choice['inputs'])
                        d['inputs'].extend(item for item in dependencies if item not in d['inputs'])
                        if not matches:
                            d['coverage'].extend(choice['coverage'])
                    if not unknown:
                        d['coverage'].remove('Lateral column alias precedence requires trusted source schema')
                        d['status'] = 'unresolved' if d['coverage'] else 'inferred'
                controls = d.get('schema_controls', [])
                if controls and config['expand_wildcards']:
                    unresolved = False
                    for control in controls:
                        schema = declared(control['table'])
                        names = [name for name in schema.get('column_identifiers', [])
                                 if _sql_name(name) not in control['payload_exclude']]
                        excluded = set(control['exclude'])
                        if not names or not excluded <= {_sql_name(name) for name in names}:
                            unresolved = True
                            continue
                        d['inputs'].extend({'table': control['table'], 'column': name, 'role': control['role']}
                                           for name in names if _sql_name(name) not in excluded)
                    if not unresolved:
                        d['coverage'].remove('AUTO CDC control wildcard requires trusted source schema')
                        d['status'] = 'unresolved' if d['coverage'] else 'inferred'
                if pivot := d.get('pivot_grouping'):
                    schema = declared(pivot['table'])
                    if schema and config['expand_wildcards']:
                        grouping = [name for name in schema['column_identifiers'] if _sql_name(name) not in pivot['exclude']]
                        if _sql_name(pivot['output']) in {_sql_name(name) for name in grouping}:
                            d['coverage'].append('PIVOT generated name conflicts with an input grouping column')
                            # Neither candidate is uniquely addressable in the SQL.
                            d['inputs'] = []
                        else:
                            d['inputs'].extend({'table': pivot['table'], 'column': name, 'role': 'value_selection'}
                                               for name in grouping)
                            d['coverage'].remove('PIVOT grouping requires trusted input schema')
                            d['status'] = 'unresolved' if d['coverage'] else 'inferred'
                if d.get('category') == 'wildcard' and d.get('wildcard_safe') and config['expand_wildcards']:
                    inputs = [i for i in d['inputs'] if i['role'] == 'value']
                    schema, source_names = {}, []
                    if len(inputs) == 1 and not inputs[0].get('scope'):
                        schema = declared(inputs[0]['table'], inputs[0].get('table_identity', ''))
                        source_names = schema.get('column_identifiers', [])
                        if schema and d.get('struct_path'):
                            source_names = _struct_members(schema, d['struct_path'])
                        elif d.get('scoped_wildcard') and not d.get('struct_path'):
                            source_names = read_layout(inputs[0]['table'], inputs[0].get('table_identity', ''))
                    elif len(inputs) == 1 and d.get('scoped_wildcard') and not d.get('struct_path'):
                        source_names = scoped_names(inputs[0]['scope'])
                    excluded = set(d.get('wildcard_exclude', []))
                    keys = ({_sql_name(name) for name in source_names} if d.get('databricks_wildcard') else
                            {column_key(name, config['case_sensitive']) for name in source_names})
                    if (d.get('wildcard_require_exclusions') and not excluded <= keys
                            or set(d.get('wildcard_reserved', [])) & (keys - excluded)
                            or d.get('scoped_wildcard') and len(keys) != len(source_names)
                            or '*' in source_names):
                        source_names = []
                    source_names = [name for name in source_names if _sql_name(name) not in excluded]
                    if source_names:
                        target_names = source_names
                        if union_layout:
                            target_names = union_layout[offset:offset + len(source_names)]
                            union_offsets[offset_key] += len(source_names)
                        if d.get('target_mapping_missing') and not positional_layout:
                            target_schema = schemas.get(outputs.get(resolver.norm(d['target_table'])), {})
                            if (target_schema.get('schema_status') != 'declared'
                                    or len(target_schema['columns']) != len(schema['columns'])):
                                derivations.append(d)
                                continue
                            target_names = target_schema['column_identifiers']
                        for position, source_name in enumerate(source_names):
                            expanded = copy.deepcopy(d)
                            gaps = [c for c in d.get('coverage', [])
                                    if c != 'Wildcard requires trusted schema expansion'
                                    and not (d.get('target_mapping_missing') and c in INSERT_MAPPING_GAPS)]
                            expanded.update(target_column=target_names[position], status='unresolved' if gaps else 'inferred',
                                            ordinal=(offset if union_layout else d.get('ordinal', 0)) + position,
                                            coverage=[*gaps, 'Expanded from imported DDL; runtime schema is unverified'
                                                      if schema else 'Expanded from an imported query output layout'])
                            for item in expanded['inputs']:
                                if item['role'] == 'value':
                                    prefix = item['column'].removesuffix('.*') if d.get('struct_path') else ''
                                    item['column'] = f'{prefix}.{source_name}' if prefix else source_name
                            derivations.append(expanded)
                        continue
                # Explicit INSERT target DDL is an inferred positional mapping.
                if d.get('target_mapping_missing') and not positional_layout and config['expand_wildcards']:
                    aid = outputs.get(resolver.norm(d['target_table']))
                    schema = schemas.get(aid, {})
                    columns = schema.get('columns', [])
                    if schema.get('schema_status') == 'declared' and len(columns) == d.get('projection_count'):
                        gaps = [c for c in d.get('coverage', []) if c not in INSERT_MAPPING_GAPS]
                        d.update(target_column=schema['column_identifiers'][d['ordinal']], status='unresolved' if gaps else 'inferred',
                                 coverage=[*gaps, 'INSERT target mapped from imported DDL; runtime schema is unverified'])
                derivations.append(d)
            positional = defaultdict(list)
            for d in derivations:
                if d.get('positional_layout'):
                    positional[d.get('branch', 0)].append(d)
                if d.get('target_by_name'):
                    schema = schemas.get(outputs.get(resolver.norm(d['target_table'])), {})
                    names = {_sql_name(name) for name in schema.get('column_identifiers', [])}
                    if names and d['target_column'] != '*' and _sql_name(d['target_column']) not in names:
                        d.update(target_column='*', status='unresolved')
                        d['coverage'].append('Named output is absent from the declared target schema')
            for branch in positional.values():
                schema = schemas.get(outputs.get(resolver.norm(branch[0]['target_table'])), {})
                names = branch[0].get('insert_target_names', schema.get('column_identifiers', []))
                layout_unknown = any(gap in {
                    'Wildcard requires trusted schema expansion', 'Set operation branch cardinality mismatch',
                    'UNION branch cardinality mismatch', 'Set operation wildcard positions require trusted schema expansion',
                    'Set operation BY NAME layout is not resolved', 'INSERT partition layout is not resolved',
                } for d in branch for gap in d['coverage'])
                layout_gap = ('INSERT source column order or count cannot be established' if layout_unknown else
                              'INSERT target schema is unavailable or ambiguous' if not names else
                              'INSERT source and target column counts differ' if len(names) != len(branch) else '')
                for ordinal, d in enumerate(branch):
                    if layout_gap or not config['expand_wildcards']:
                        d.update(target_column='*', status='unresolved')
                        d['coverage'].append(layout_gap or 'Trusted schema expansion is disabled')
                    else:
                        gaps = [c for c in d['coverage'] if c not in INSERT_MAPPING_GAPS and not c.startswith('Expanded from')]
                        d.update(target_column=names[ordinal], status='unresolved' if gaps else 'inferred',
                                 ordinal=ordinal, coverage=[*gaps, 'INSERT target mapped from imported DDL; runtime schema is unverified'])
            for index, d in enumerate(derivations):
                target, inferred = reference(d['target_table'], d['target_column'], d.get('scope', ''),
                                             d.get('target_version', ''), output=True, identity=d.get('target_identity', ''))
                did = stable_id(oid, str(index), target, str(d.get('branch', 0)))
                status = d.get('status', 'unresolved')
                if (inferred or op.method == 'ai-project') and status == 'verified':
                    status = 'inferred'
                dependencies = []
                for ordinal, item in enumerate(d.get('inputs', [])):
                    cid, uncertain = reference(item['table'], item.get('column', ''), item.get('scope', ''),
                                                item.get('version', ''), identity=item.get('table_identity', ''))
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


def _asset(store: Store, workspace: str, asset_id: str) -> None:
    """Raise when an asset does not belong to the given workspace.

    Raises:
        ValueError: If the supplied value violates the operation constraints."""
    if not store.rows('SELECT 1 FROM assets WHERE workspace_id=? AND asset_id=?', [workspace, asset_id]):
        raise ValueError('Asset does not exist in this workspace')


def column_catalog(store: Store, workspace: str, asset_id: str, limit: int=500) -> list[dict[str, Any]]:
    """List known columns for an asset in stable catalog order.

    Args:
        store: Database access object.
        workspace: Workspace containing the asset.
        asset_id: Asset whose column references should be listed.
        limit: Maximum number of catalog rows to return.

    Returns:
        Column reference rows.

    Raises:
        ValueError: If the limit is outside the supported range or the asset is missing."""
    if type(limit) is not int or not 1 <= limit <= 20000:
        raise ValueError('Column catalog limit must be 1–20000')
    with store.lock:
        _asset(store, workspace, asset_id)
        return store.rows('''SELECT column_id,asset_id,table_name AS "table",column_name,scope,version
            FROM column_references WHERE workspace_id=? AND asset_id=?
            ORDER BY scope,column_key,version,column_id LIMIT ?''', [workspace, asset_id, limit])


def _ref(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a database column row into a public reference object."""
    return {k: row[k] for k in ('column_id', 'asset_id', 'column_name', 'scope', 'version')} | {'table': row['table_name']}


def trace_columns(store: Store, workspace: str, asset_id: str, column: str, direction: str='upstream', depth: int=5, limit: int=200,
                  status: str='all', include_source: bool=False) -> dict[str, Any]:
    """Trace column derivations upstream or downstream within an asset.

    Args:
        store: Database access object.
        workspace: Workspace containing the asset.
        asset_id: Asset containing the selected column.
        column: Column name or exact column identifier.
        direction: Traversal direction, either ``upstream`` or ``downstream``.
        depth: Maximum number of derivation levels to traverse.
        limit: Maximum number of derivations and supporting rows to inspect.
        status: Derivation status filter, or ``all`` to include every status.
        include_source: Whether to include capped source text in evidence.

    Returns:
        Trace results, paths, coverage details, and completeness state.

    Raises:
        ValueError: If the direction, status, depth, limit, or column is invalid."""
    if direction not in {'upstream', 'downstream'} or status not in STATUSES:
        raise ValueError('Invalid direction or status')
    if type(depth) is not int or not 1 <= depth <= 30 or type(limit) is not int or not 1 <= limit <= 20000:
        raise ValueError('Use depth 1–30 and limit 1–20000')
    if not isinstance(column, str) or not column.strip() or len(column) > 1024:
        raise ValueError('Select a column name or exact column ID')
    with store.lock:
        _asset(store, workspace, asset_id)
        return _trace(store, workspace, asset_id, column, direction, depth, limit, status, include_source)


def _trace(store: Store, w: str, aid: str, column: str, direction: str, depth: int, limit: int, status: str, include_source: bool) -> dict[str, Any]:
    """Traverse derivations and collect bounded lineage evidence."""
    from dataforge.services import PARSER_VERSION

    analysis = store.rows('''SELECT c.run_id,c.parser_version,r.configuration FROM column_analysis c JOIN analysis_runs r
        ON c.run_id=r.run_id AND c.workspace_id=r.workspace_id WHERE c.workspace_id=?''', [w])
    result = {'workspace_id': w, 'asset_id': aid, 'column': column, 'direction': direction,
              'depth': depth, 'derivations': [], 'paths': [], 'coverage': [], 'truncated': False,
              'complete': False, 'state': 'not_analyzed', 'run_id': analysis[0]['run_id'] if analysis else None}
    coverage = result['coverage']

    def boundary(reason: str, **context: Any) -> None:
        """Add a coverage marker once, preserving the first-seen order."""
        marker = {'reason': reason, **context}
        if marker not in coverage:
            coverage.append(marker)

    if not analysis:
        boundary('reanalysis_required', message='Analyze sources to establish transformation coverage')
        return result
    run_id = analysis[0]['run_id']
    if analysis[0]['parser_version'] != PARSER_VERSION:
        boundary('reanalysis_required', message='Analyze again to refresh column identity and schema mappings')
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

    def scope_boundaries(column_id: str) -> bool:
        """Record unresolved scoped writes associated with a column."""
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
            next_effect = effect
            if direction == 'downstream' and effect != 'row_selection':
                roles = store.rows('''SELECT DISTINCT role FROM column_dependencies WHERE workspace_id=?
                    AND derivation_id=? AND source_column_id=?''', [w, did, cid])
                next_effect = _path_effect(effect, {row['role'] for row in roles})
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
            if not multiple_writers and step['status'] != 'unresolved':
                if direction == 'upstream':
                    following = [(i['column_id'], level + 1, _path_effect(effect, {i['role']}),
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
