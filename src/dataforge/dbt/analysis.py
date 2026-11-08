"""Project model analysis adapted to the existing graph/column contracts."""

import ast
import re
from bisect import bisect_right

from dataforge.dbt.evidence import evidence
from dataforge.dbt.models import DbtLimits, DbtProjectResult, DbtRelationship
from dataforge.dbt.resolution import asset_ref, relation_identifier, resolve_bindings, resolve_reference
from dataforge.dbt.resources import DATA_TYPES, collect_resources, scan_python_model
from dataforge.dbt.templates import ReferenceCall, expression_macros, scan_template
from dataforge.models import AssetRef, Diagnostic, Operation, ParseResult, file_asset
from dataforge.parsers.sql import parse_sql


def rewrite_query(text, replacements):
    chunks, starts, ends, originals = [], [], [], []
    cursor = generated = 0
    for (start, end), value in sorted(replacements.items()):
        chunks.extend((text[cursor:start], value))
        generated += start - cursor
        starts.append(generated)
        generated += len(value)
        ends.append(generated)
        originals.append((start, end))
        cursor = end
    chunks.append(text[cursor:])

    def original_offset(offset, end=False):
        index = bisect_right(ends, offset) - 1
        if index + 1 < len(starts) and starts[index + 1] < offset < ends[index + 1]:
            return originals[index + 1][end]
        if index + 1 < len(starts) and offset == starts[index + 1]:
            return originals[index + 1][0]
        return offset + (originals[index][1] - ends[index] if index >= 0 else 0)

    return ''.join(chunks), original_offset


def layout(output, support, columns=None):
    return {'table': output.name, 'asset_identity': output.identity, 'columns': columns,
            'query_layout': columns is None, 'operation_index': 0,
            'start_line': support.start_line, 'end_line': support.end_line}


def projection(output, column, expression, inputs=(), *, category='direct', gap=None, **flags):
    return {'target_table': output.name, 'target_identity': output.identity, 'target_column': column,
            'scope': '', 'expression': expression, 'inputs': list(inputs), 'category': category,
            'status': 'unresolved' if gap else 'verified', 'coverage': [gap] if gap else [], **flags}


def value(ref, column):
    return {'table': ref.name, 'table_identity': ref.identity, 'column': column, 'role': 'value'}


def wildcard(output, source, code, **flags):
    return projection(output, '*', code, [value(source, '*')], category='wildcard',
                      gap='Wildcard requires trusted schema expansion', wildcard_safe=True, scoped_wildcard=True, **flags)


def snapshot_runtime(output, code):
    return projection(output, '*', code, category='unsupported', scope='snapshot-runtime',
                      gap='Snapshot history and system columns require runtime evidence')


def python_passthrough(text):
    try:
        module = ast.parse(text)
    except (SyntaxError, RecursionError):
        return False
    match module.body:
        case [ast.FunctionDef(name='model', decorator_list=[],
                args=ast.arguments(posonlyargs=[], args=[ast.arg(arg='dbt'), ast.arg()],
                                   vararg=None, kwonlyargs=[], kwarg=None, defaults=[]), body=[
                ast.Return(value=ast.Call(func=ast.Attribute(value=ast.Name(id='dbt'), attr='ref'),
                                          args=args, keywords=keywords))])]:
            return (len(args) in {1, 2} and all(isinstance(arg, ast.Constant) and isinstance(arg.value, str) for arg in args)
                    and all(keyword.arg in {'v', 'version'} and isinstance(keyword.value, ast.Constant)
                            for keyword in keywords))
        case _:
            return False


def parse_model_query(query, *, output, dialect, primary_evidence, relation_map,
                      expression_map=None, macro_spans=None, fallback_sources=(), ambiguous_relations=(),
                      opaque_spans=None, compiled=False):
    result = parse_sql(query, dialect, query_output=output,
                       fold_query_identifiers=compiled and dialect == 'postgres')
    opaque_used = set()

    def bind(item):
        if not item.get('scope') and (ref := relation_map.get(item['table'])):
            item['table'], item['table_identity'] = ref.name, ref.identity

    for op in result.operations:
        generated = op.code
        op.sources = [relation_map.get(ref.name, ref) for ref in op.sources if ref.name not in ambiguous_relations]
        op.code, op.start, op.end = primary_evidence.excerpt, primary_evidence.start_line, primary_evidence.end_line
        op.kind, op.method = 'DBT_MODEL_READ', 'dbt-parser'
        op.usages = [usage for usage in op.usages if usage.table not in ambiguous_relations]
        for usage in op.usages:
            ref = relation_map.get(usage.table)
            if ref:
                usage.table, usage.table_identity = ref.name, ref.identity
        for d in op.derivations:
            if not d.get('scope'):
                d['target_table'], d['target_identity'] = output.name, output.identity
            offset = d.pop('_expression_offset', None)
            if expression_map and d['expression']:
                start = offset + len(query) - len(query.lstrip()) if offset is not None else None
                if start is not None and generated[offset:offset + len(d['expression'])] == d['expression']:
                    expression = d['expression']
                    end = start + len(expression)
                    left, right = expression_map(start), expression_map(end, True)
                    d['expression'] = op.code[left:right]
                    d['evidence_notes'] = [f'Static dbt macro expands to {value.strip()}'
                                           for (a, b), value in (macro_spans or {}).items() if left < b and a < right]
                    token = (opaque_spans or {}).get(left)
                    if token and re.fullmatch(rf'{token}\(\)\s+as\s+[A-Za-z_]\w*', expression, re.I):
                        opaque_used.add(left)
                        d['category'] = 'expression'
                        d['status'] = 'unresolved'
                        d['coverage'] = [gap for gap in d['coverage'] if token not in gap.casefold()]
                        d['coverage'].append('Aliased dbt macro expression requires compiled SQL for value lineage')
                elif d['expression'] not in op.code:
                    d['expression'] = op.code
            ambiguous = set()

            def bind_group(items):
                blocked = {item['table'] for item in items
                           if not item.get('scope') and item['table'] in ambiguous_relations}
                ambiguous.update(blocked)
                if not blocked:
                    for item in items:
                        bind(item)
                return not blocked

            for key in ('inputs', 'schema_controls'):
                if key in d:
                    d[key] = [item for item in d[key] if bind_group([item])]
            if 'unqualified_columns' in d:
                d['unqualified_columns'] = [column for column in d['unqualified_columns'] if bind_group(column['sources'])]
            if 'lateral_choices' in d:
                d['lateral_choices'] = [choice for choice in d['lateral_choices'] if bind_group([choice, *choice['inputs']])]
            if 'pivot_grouping' in d and not bind_group([d['pivot_grouping']]):
                del d['pivot_grouping']
            if ambiguous:
                d['status'] = 'unresolved'
                d['coverage'].extend(f'Ambiguous compiled dbt relation {name}' for name in sorted(ambiguous))
    result.assets.append(output)
    if opaque_spans:
        if opaque_used != opaque_spans.keys():
            # An opaque tag in a relation or clause can change sibling bindings.
            result.operations.clear()
        else:
            result.diagnostics.append(Diagnostic('Aliased dbt macro expression has partial column coverage',
                                                 primary_evidence.start_line))
            for op in result.operations:
                for d in op.derivations:
                    if d['status'] != 'unresolved':
                        d['status'] = 'inferred'
                        d.setdefault('evidence_notes', []).append(
                            'Sibling lineage assumes the aliased dbt macro produces one value')
    if result.operations and result.operations[0].derivations and not opaque_spans:
        result.metadata['declared_schemas'] = [layout(output, primary_evidence)]
    elif not result.operations:
        gap = 'Unsupported dbt query. Column coverage is partial'
        support = primary_evidence
        result.operations.append(Operation('DBT_MODEL_READ', list(fallback_sources), [output],
            support.excerpt, support.start_line, support.end_line, method='dbt-parser',
            derivations=[projection(output, '*', support.excerpt, gap=gap)]))
        result.diagnostics.append(Diagnostic(gap, support.start_line))
    return result


def analyze_dbt_project(snapshot, read_source, limits=None):
    limits = limits or DbtLimits()
    manifests = [s for s in snapshot.sources if s.file_id in snapshot.context.artifact_file_ids and
                 (s.relative_path.endswith('/manifest.json') or s.relative_path == 'manifest.json')]
    if manifests and (snapshot.context.mode != 'source' or not any(s.relative_path.endswith('dbt_project.yml') for s in snapshot.sources)):
        if len(manifests) != 1:
            raise ValueError('Select exactly one dbt manifest per project context')
        return analyze_manifest_project(snapshot, read_source, manifests[0], limits)
    resources, warnings = collect_resources(snapshot, read_source)
    expand_macro = expression_macros(resources)
    custom_alias = any(r.enabled and r.resource_type == 'macro' and r.name == 'generate_alias_name' for r in resources)
    results = {s.file_id: ({'file_id': s.file_id, 'content_hash': s.content_hash,
        'relative_path': s.relative_path, 'extension': '.' + s.relative_path.rsplit('.', 1)[-1].lower()},
        ParseResult(metadata={'source_kind': 'dbt', 'dbt_project_id': snapshot.project_id,
                              'dbt_fingerprint': snapshot.fingerprint})) for s in snapshot.sources}
    relationships, diagnostics = [], [Diagnostic(w) for w in warnings]
    for resource in resources:
        source = resource.definition.source
        original = read_source(source)
        snapshot_sql = resource.resource_type == 'snapshot' and source.relative_path.endswith('.sql')
        text = resource.definition.excerpt if snapshot_sql else original
        base_offset = resource.definition.start_offset if snapshot_sql else 0
        parsed = results[source.file_id][1]
        if not resource.enabled:
            continue
        if resource.resource_type in DATA_TYPES:
            parsed.assets.append(asset_ref(resource))
            parsed.metadata.setdefault('dbt_asset_metadata', {})['dbt:' + resource.resource_id] = {
                'dbt_resource_id': resource.resource_id, 'resource_type': resource.resource_type,
                'package_name': resource.package_name, 'version': resource.version, **resource.metadata}
            asset_metadata = parsed.metadata['dbt_asset_metadata']['dbt:' + resource.resource_id]
            if 'columns' in asset_metadata:
                asset_metadata['documented_columns'] = asset_metadata.pop('columns')
        facts = scan_template(text, variables=snapshot.context.public_vars)
        declared = []
        meta = resource.metadata
        if resource.resource_type in {'metric', 'saved_query'}:
            params = meta.get('type_params', {}) if resource.resource_type == 'metric' else meta.get('query_params', {})
            measure = params.get('measure')
            measure = measure.get('name') if isinstance(measure, dict) else measure
            dependencies = []
            if isinstance(measure, str):
                dependencies.extend(r for r in resources if r.resource_type == 'semantic_model' and
                    any(m.get('name') == measure for m in r.metadata.get('measures', [])))
            for metric in params.get('metrics', []):
                name = metric.get('name') if isinstance(metric, dict) else metric
                dependencies.extend(r for r in resources if r.resource_type == 'metric' and r.name == name)
            for target in dependencies:
                relationships.append(DbtRelationship(target.resource_id, resource.resource_id,
                    'semantic_dependency', 'resolved', (resource.definition,)))
        depends_on = meta.get('depends_on')
        expressions = [(expression, False) for expression in depends_on] if isinstance(depends_on, list) else []
        expressions.extend(((meta.get('relation'), True), (meta.get('model'), False)))
        for expression, payload in expressions:
            if isinstance(expression, str) and ('ref(' in expression or 'source(' in expression):
                calls = scan_template(expression if '{{' in expression else '{{ ' + expression + ' }}').calls
                declared.extend((call, payload and len(calls) == 1 and not call.conditional) for call in calls)
        for call, payload in declared:
            target = resolve_reference(resources, resource, call)
            if target:
                kind = ('test_of' if resource.resource_type in {'test', 'unit_test'} else
                        'exposure_of' if resource.resource_type == 'exposure' else
                        'data_read' if resource.resource_type == 'snapshot' else 'semantic_dependency')
                relationships.append(DbtRelationship(target.resource_id, resource.resource_id, kind, 'resolved',
                                                     (resource.definition,)))
                if resource.resource_type == 'snapshot':
                    output, upstream = asset_ref(resource), asset_ref(target)
                    records = []
                    if payload:
                        metadata_names = {'dbt_scd_id', 'dbt_updated_at', 'dbt_valid_from', 'dbt_valid_to', 'dbt_is_deleted'}
                        configured = meta.get('config', {}).get('snapshot_meta_column_names')
                        if isinstance(configured, dict):
                            metadata_names.update(name.casefold() for name in configured.values() if isinstance(name, str))
                        records = [wildcard(output, upstream, resource.definition.excerpt,
                                            wildcard_exclude=sorted(metadata_names)),
                                   snapshot_runtime(output, resource.definition.excerpt)]
                    parsed.operations.append(Operation('DBT_DEPENDENCY', [upstream], [output],
                        resource.definition.excerpt, resource.definition.start_line, resource.definition.end_line,
                        method='dbt-declaration', evidence_key=resource.resource_id, derivations=records))
        if resource.resource_type in {'test', 'unit_test'} and isinstance(meta.get('model'), str) and '(' not in meta['model']:
            call = ReferenceCall('source', tuple(meta['source_args']), {}, 0, 0) if meta.get('source_args') else ReferenceCall('ref', (meta['model'],), {}, 0, 0)
            target = resolve_reference(resources, resource, call)
            if target:
                relationships.append(DbtRelationship(target.resource_id, resource.resource_id, 'test_of', 'resolved',
                                                     (resource.definition,)))
        if source.relative_path.endswith(('.yml', '.yaml')):
            continue
        calls = facts.calls
        if resource.metadata.get('language') == 'python':
            python_calls, _ = scan_python_model(text, source)
            calls = [ReferenceCall(n, a, k, 0, len(text), conditional) for n, a, k, _, conditional in python_calls]
        refs, replacements = {}, []
        for call in calls:
            if call.owner and call.owner != resource.name:
                continue
            target = resolve_reference(resources, resource, call)
            line_prefix = text[text.rfind('\n', 0, call.start) + 1:call.start]
            ordering = 'depends_on:' in line_prefix
            support = evidence(source, original, base_offset + call.start, base_offset + call.end)
            if target:
                candidate = call.conditional or resource.resource_type == 'macro'
                kind = ('declared_dependency' if ordering else 'test_of' if resource.resource_type in {'test', 'unit_test'}
                        else 'data_read')
                relationships.append(DbtRelationship(target.resource_id, resource.resource_id,
                    kind, 'candidate' if candidate else 'resolved', (support,)))
                if not candidate and not ordering and resource.resource_type in {'model', 'snapshot'}:
                    token = '__gt_dbt_' + target.resource_id
                    identifier = relation_identifier(target)
                    if (target.resource_type == 'source' or not custom_alias) and re.fullmatch(r'[A-Za-z_]\w*', identifier):
                        if target.metadata.get('config', {}).get('materialized') == 'ephemeral':
                            identifier = '__dbt__cte__' + identifier
                        token += '.' + identifier
                    refs[token] = asset_ref(target)
                    replacements.append((call.start, call.end, token))
            elif call.name in {'ref', 'source'}:
                parsed.diagnostics.append(Diagnostic('Unresolved or dynamic dbt reference', support.start_line, symbol=call.name))
            elif call.name not in {'config', 'var', 'env_var', 'target', 'this', 'is_incremental', 'run_query'}:
                matches = [r for r in resources if r.resource_type == 'macro' and
                    (r.package_name + '.' + r.name == call.name or r.name == call.name)]
                if len(matches) == 1:
                    relationships.append(DbtRelationship(matches[0].resource_id, resource.resource_id,
                        'macro_call', 'resolved', (support,)))
        if resource.resource_type == 'seed':
            csv_file, output = AssetRef(file_asset(source.relative_path), kind='file'), asset_ref(resource)
            names = resource.metadata['seed_header']
            valid = (names and all(name and name == name.strip() and name != '*' for name in names)
                     and len({name.casefold() for name in names}) == len(names))
            records = ([projection(output, name, '', [value(csv_file, name)], category='seed') for name in names]
                       if valid else [projection(output, '*', '', gap='Seed header does not establish unique columns')])
            if valid:
                parsed.metadata.setdefault('declared_schemas', []).append({
                    **layout(output, resource.definition, [{'name': name, 'type': 'unknown'} for name in names]),
                    'operation_index': len(parsed.operations), 'origin': 'seed_header'})
            parsed.operations.append(Operation('DBT_SEED', [csv_file], [output], text, 1,
                max(1, len(text.splitlines())), method='dbt-parser', derivations=records))
        if resource.resource_type in {'model', 'snapshot', 'analysis', 'test'}:
            parsed.diagnostics.extend(Diagnostic(warning) for warning in facts.diagnostics)
        if resource.resource_type not in {'model', 'snapshot'}:
            continue
        if resource.metadata.get('language') == 'python':
            output = asset_ref(resource)
            if len(refs) == 1 and python_passthrough(text):
                records = [wildcard(output, next(iter(refs.values())), text)]
                parsed.metadata.setdefault('declared_schemas', []).append({
                    **layout(output, resource.definition), 'operation_index': len(parsed.operations)})
            else:
                gap = 'Python model coverage is limited to dependencies for this form'
                parsed.diagnostics.append(Diagnostic(gap))
                records = [projection(output, '*', text, gap=gap)]
            parsed.operations.append(Operation('DBT_DEPENDENCY', list(refs.values()), [output],
                text, 1, max(1, len(text.splitlines())), method='dbt-python', derivations=records))
            continue
        unsupported = bool(facts.diagnostics)
        macro_spans = {}
        opaque_spans = {}
        expression_calls = {call.start for call in calls if not call.conditional and call.name not in {'ref', 'source'}}
        replacements_by_span = {(a, b): value for a, b, value in replacements}
        for start, end, body in facts.tags:
            if (start, end) not in replacements_by_span:
                if (body.startswith('config(') or text[start:start + 2] == '{#'
                        or snapshot_sql and (body.startswith('snapshot ') or body == 'endsnapshot')):
                    replacements_by_span[start, end] = ''.join('\n' if c == '\n' else ' ' for c in text[start:end])
                else:
                    aliased = text[start:start + 2] == '{{' and re.match(r'\s+as\s+[\w"`\[]', text[end:], re.I)
                    expansion = expand_macro(body, resource.package_name) if aliased else None
                    if expansion and re.search(r'[+*/-]', expansion) and not any(c in expansion for c in ('--', '/*', '*/')):
                        replacements_by_span[start, end] = macro_spans[start, end] = expansion
                    elif aliased and start in expression_calls:
                        token = f'__gt_dbt_opaque_{start}'
                        if token in text.casefold():
                            unsupported = True
                        else:
                            opaque_spans[start] = token
                            replacements_by_span[start, end] = token + '()'
                    else:
                        unsupported = True
        if unsupported:
            gap = 'Unexpanded macro or conditional SQL. Column coverage is partial'
            parsed.diagnostics.append(Diagnostic(gap))
            if resource.resource_type in {'model', 'snapshot'}:
                output = asset_ref(resource)
                parsed.operations.append(Operation('DBT_MODEL_READ', list(refs.values()), [output],
                    text, resource.definition.start_line, resource.definition.end_line, method='dbt-parser',
                    derivations=[projection(output, '*', text, gap=gap)]))
            continue
        query, expression_map = rewrite_query(text, replacements_by_span)
        model = parse_model_query(query, output=asset_ref(resource), dialect=snapshot.context.dialect,
            primary_evidence=resource.definition, relation_map=refs, expression_map=expression_map,
            macro_spans=macro_spans, fallback_sources=refs.values(), opaque_spans=opaque_spans)
        offset = len(parsed.operations)
        if resource.resource_type == 'model':
            parsed.metadata.setdefault('declared_schemas', []).extend({**record,
                'operation_index': offset + record['operation_index']} for record in model.metadata.get('declared_schemas', []))
        elif snapshot_sql:
            for operation in model.operations:
                operation.derivations.append(snapshot_runtime(operation.targets[0], operation.code))
        parsed.operations.extend(model.operations)
        parsed.diagnostics.extend(model.diagnostics)
    if len(relationships) > limits.max_relationships:
        raise ValueError('dbt project relationship budget exceeded')
    for _, parsed in results.values():
        diagnostics.extend(parsed.diagnostics)
    if diagnostics:
        next(iter(results.values()))[1].diagnostics.extend(d for d in diagnostics if d not in next(iter(results.values()))[1].diagnostics)
    return DbtProjectResult(snapshot, resources, tuple(relationships), resolve_bindings(resources, snapshot),
        tuple(results.values()), tuple(diagnostics), {'inventory': 'complete',
            'dependencies': 'partial' if diagnostics else 'complete',
            'columns': 'partial' if diagnostics else 'parsed_sql', 'mode': snapshot.context.mode})


def analyze_manifest_project(snapshot, read_source, manifest_source, limits):
    from dataclasses import replace

    from dataforge.dbt.artifacts import artifact_evidence, bind_artifacts, manifest_resources, read_artifact
    document = read_artifact(manifest_source, read_source(manifest_source))
    resources, nodes = manifest_resources(document, snapshot)
    auxiliary = [read_artifact(s, read_source(s)) for s in snapshot.sources
                 if s.file_id in snapshot.context.artifact_file_ids and
                 (s.relative_path.endswith(('/catalog.json', '/run_results.json')) or
                  s.relative_path in {'catalog.json', 'run_results.json'})]
    observations = bind_artifacts([document, *auxiliary])
    resources = tuple(replace(r, metadata={**r.metadata, **observations.get(r.unique_id, {})}) for r in resources)
    by_uid = {r.unique_id: r for r in resources}
    nodes = {uid: (by_uid[uid], node, section) for uid, (_, node, section) in nodes.items()}
    by_path = {s.relative_path: s for s in snapshot.sources}
    for resource, node, _ in nodes.values():
        from pathlib import PurePosixPath

        from dataforge.ingestion import safe_relative
        original_path = node.get('original_file_path', '')
        try:
            path = safe_relative(str(PurePosixPath(snapshot.root_path) / safe_relative(original_path)))
        except ValueError:
            continue
        if path in by_path and isinstance(node.get('raw_code'), str):
            if read_source(by_path[path]).replace('\r\n', '\n').strip() != node['raw_code'].replace('\r\n', '\n').strip():
                raise ValueError('dbt manifest source mismatch; use source-only mode or a matching artifact')
    results = {s.file_id: ({'file_id': s.file_id, 'content_hash': s.content_hash,
        'relative_path': s.relative_path, 'extension': '.' + s.relative_path.rsplit('.', 1)[-1]},
        ParseResult(metadata={'source_kind': 'dbt', 'dbt_project_id': snapshot.project_id,
                              'dbt_fingerprint': snapshot.fingerprint})) for s in snapshot.sources}
    parsed = results[manifest_source.file_id][1]
    cataloged = set()
    for catalog in auxiliary:
        if catalog.kind != 'catalog' or catalog.data.get('errors'):
            continue
        catalog_result = results[catalog.source.file_id][1]
        for section in ('nodes', 'sources'):
            for uid, entry in catalog.data.get(section, {}).items():
                resource = by_uid[uid]
                columns = entry.get('columns')
                if (resource.resource_type not in DATA_TYPES or not resource.enabled
                        or not isinstance(columns, dict) or not columns):
                    continue
                if not all(isinstance(c, dict) and c.get('name') == name and name.strip() and name != '*'
                           and type(c.get('index')) is int and isinstance(c.get('type'), str)
                           for name, c in columns.items()):
                    continue
                ordered = sorted(columns.values(), key=lambda c: c['index'])
                indices = [c['index'] for c in ordered]
                if indices[0] not in {0, 1} or indices != list(range(indices[0], indices[0] + len(indices))):
                    continue
                support = artifact_evidence(catalog, (section, uid, 'columns'))
                output = asset_ref(resource)
                catalog_result.metadata.setdefault('declared_schemas', []).append({
                    **layout(output, support, [{'name': c['name'], 'type': c['type']} for c in ordered]),
                    'operation_index': len(catalog_result.operations), 'origin': 'dbt_catalog'})
                catalog_result.operations.append(Operation('DBT_CATALOG', [], [output], support.excerpt,
                    support.start_line, support.end_line, method='dbt-catalog', evidence_key=uid))
                cataloged.add(uid)
    parsed.metadata['dbt_asset_metadata'] = {'dbt:' + r.resource_id: {**r.metadata,
        'dbt_resource_id': r.resource_id, 'resource_type': r.resource_type, 'package_name': r.package_name,
        'dbt_context_status': 'artifact_snapshot'} for r in resources}
    for metadata in parsed.metadata['dbt_asset_metadata'].values():
        if 'columns' in metadata:
            metadata['documented_columns'] = metadata.pop('columns')
    relationships, generated_evidence = [], []
    physical = {}
    for resource in resources:
        if resource.resource_type in DATA_TYPES and resource.enabled:
            parsed.assets.append(asset_ref(resource))
            meta = resource.metadata
            identifier = meta.get('identifier', meta.get('alias', resource.name))
            components = [meta.get('database'), meta.get('schema'), identifier]
            for index in range(3):
                if all(isinstance(p, str) and p for p in components[index:]):
                    key = '.'.join('"' + p.replace('"', '""') + '"' if '.' in p else p for p in components[index:])
                    physical.setdefault(key, []).append(asset_ref(resource))
    ambiguous_relations = {key for key, refs in physical.items() if len(refs) > 1}
    physical = {key: refs[0] for key, refs in physical.items() if len(refs) == 1}
    for uid, (resource, node, section) in nodes.items():
        if not resource.enabled:
            continue
        dependency_sources = []
        for category in ('nodes', 'macros'):
            for index, parent_uid in enumerate(node.get('depends_on', {}).get(category, [])):
                parent = nodes.get(parent_uid)
                if parent is None or not parent[0].enabled:
                    parsed.diagnostics.append(Diagnostic('Missing or disabled manifest dependency', symbol=parent_uid))
                    continue
                parent_resource = parent[0]
                support = artifact_evidence(document, (section, uid, 'depends_on', category, index))
                kind = ('macro_call' if category == 'macros' else 'artifact_dependency'
                        if resource.resource_type in DATA_TYPES and parent_resource.resource_type in DATA_TYPES
                        else 'test_of' if resource.resource_type in {'test', 'unit_test'} else 'semantic_dependency')
                relationships.append(DbtRelationship(parent_resource.resource_id, resource.resource_id,
                    kind, 'resolved', (support,)))
                if kind == 'artifact_dependency':
                    dependency_sources.append(asset_ref(parent_resource))
        query = node.get('compiled_code')
        model_query = resource.resource_type in {'model', 'snapshot'}
        compiled = model_query and isinstance(query, str) and query.strip() and node.get('language', 'sql') == 'sql'
        if resource.resource_type in DATA_TYPES and (dependency_sources or model_query and not compiled):
            ref = resource.definition
            output = asset_ref(resource)
            records = ([projection(output, '*', ref.excerpt, gap='Supplied dbt artifact has no compiled SQL for this model')]
                       if model_query and not compiled else [])
            parsed.operations.append(Operation('DBT_DEPENDENCY', dependency_sources, [asset_ref(resource)],
                ref.excerpt, ref.start_line, ref.end_line, method='dbt-manifest', evidence_key=uid + ':dependency',
                derivations=records))
        if compiled:
            dialect = snapshot.context.dialect or {'postgres': 'postgres', 'snowflake': 'snowflake',
                'bigquery': 'bigquery', 'duckdb': 'duckdb', 'databricks': 'databricks',
                'spark': 'spark', 'redshift': 'redshift'}.get(document.data['metadata'].get('adapter_type'), '')
            model = parse_model_query(query, output=asset_ref(resource), dialect=dialect,
                primary_evidence=resource.definition, relation_map=physical, ambiguous_relations=ambiguous_relations,
                compiled=True)
            generated = artifact_evidence(document, (section, uid, 'compiled_code'), origin='compiled_sql')
            generated_evidence.append((resource.resource_id, generated))
            direct = {ref.identity for ref in dependency_sources}
            # The manifest owns ephemeral hops; retain proven external reads and
            # direct logical reads without flattening its transitive dependencies.
            for op in model.operations:
                op.evidence_key = uid + ':compiled'
                op.table_pairs = [(i, 0) for i, ref in enumerate(op.sources)
                                  if not ref.identity or ref.identity in direct]
                op.warnings.append('Expressions are from supplied compiled SQL; source mapping is unavailable')
                if resource.resource_type == 'snapshot':
                    op.derivations.append(snapshot_runtime(op.targets[0], op.code))
                for derivation in op.derivations:
                    derivation.setdefault('evidence_notes', []).append(
                        'Expression comes from supplied compiled SQL at ' + generated.json_pointer)
            if uid not in cataloged and resource.resource_type == 'model':
                offset = len(parsed.operations)
                parsed.metadata.setdefault('declared_schemas', []).extend({**record,
                    'operation_index': offset + record['operation_index']}
                    for record in model.metadata.get('declared_schemas', []))
            parsed.operations.extend(model.operations)
            parsed.diagnostics.extend(model.diagnostics)
    if len(relationships) > limits.max_relationships:
        raise ValueError('dbt relationship budget exceeded')
    parsed.diagnostics.append(Diagnostic('Artifact snapshot: compilation context cannot be certified from source text alone', severity='info'))
    return DbtProjectResult(snapshot, resources, tuple(relationships), resolve_bindings(resources, snapshot),
        tuple(results.values()), tuple(parsed.diagnostics), {'inventory': 'artifact_declared',
            'dependencies': 'artifact_declared', 'columns': 'partial', 'mode': 'artifact',
            'context_status': 'unverifiable', 'schema': 'manifest/v12'}, tuple(generated_evidence))
