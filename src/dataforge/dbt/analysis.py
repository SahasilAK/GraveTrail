"""Project model analysis adapted to the existing graph/column contracts."""

import sqlglot
from sqlglot import exp

from dataforge.dbt.evidence import evidence
from dataforge.dbt.models import DbtLimits, DbtProjectResult, DbtRelationship
from dataforge.dbt.resolution import asset_ref, resolve_bindings, resolve_reference
from dataforge.dbt.resources import DATA_TYPES, collect_resources, scan_python_model
from dataforge.dbt.templates import ReferenceCall, scan_template
from dataforge.models import AssetRef, Diagnostic, Operation, ParseResult, file_asset
from dataforge.parsers.sql import parse_sql, reachable_scopes
from dataforge.parsers.sql_transformations import extract_transformations


def parse_model_query(query, *, output, dialect, primary_evidence, relation_map,
                      expression_map=()):
    result = parse_sql(query, dialect)
    try:
        tree = sqlglot.parse_one(query, read=dialect or None)
        if not isinstance(tree, (exp.Select, exp.SetOperation)):
            raise ValueError('dbt model requires one query')
        derivations = extract_transformations(tree, query, sqlglot.Dialect.get_or_raise(dialect or None),
            reachable_scopes(tree), exp.to_table(output.name))
    except (sqlglot.errors.SqlglotError, ValueError, RecursionError):
        return ParseResult(assets=[output], diagnostics=[Diagnostic('Unsupported dbt query; column coverage is partial')])
    operations = result.operations or [Operation('SELECT', [], [], query, 1, 1)]
    for op in operations:
        op.sources = [relation_map.get(ref.name, ref) for ref in op.sources]
        op.targets = [output]
        op.code, op.start, op.end = primary_evidence.excerpt, primary_evidence.start_line, primary_evidence.end_line
        op.kind, op.method, op.derivations = 'DBT_MODEL_READ', 'dbt-parser', derivations
        for usage in op.usages:
            ref = relation_map.get(usage.table)
            if ref:
                usage.table, usage.table_identity = ref.name, ref.identity
        for d in op.derivations:
            if not d.get('scope'):
                d['target_table'], d['target_identity'] = output.name, output.identity
            for item in d.get('inputs', []):
                if not item.get('scope') and item['table'] in relation_map:
                    ref = relation_map[item['table']]
                    item['table'], item['table_identity'] = ref.name, ref.identity
    result.operations = operations
    result.assets.append(output)
    if isinstance(tree, exp.Select):
        names = [projection.alias_or_name for projection in tree.expressions]
        if all(names) and len(names) == len(set(names)) and not any(p.is_star for p in tree.expressions):
            result.metadata['declared_schemas'] = [{'table': output.name, 'asset_identity': output.identity,
                'columns': [{'name': name, 'type': 'unknown'} for name in names],
                'column_identifiers': names, 'operation_index': 0,
                'start_line': primary_evidence.start_line, 'end_line': primary_evidence.end_line,
                'origin': 'parsed_output'}]
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
    results = {s.file_id: ({'file_id': s.file_id, 'content_hash': s.content_hash,
        'relative_path': s.relative_path, 'extension': '.' + s.relative_path.rsplit('.', 1)[-1].lower()},
        ParseResult(metadata={'source_kind': 'dbt', 'dbt_project_id': snapshot.project_id,
                              'dbt_fingerprint': snapshot.fingerprint})) for s in snapshot.sources}
    relationships, diagnostics = [], [Diagnostic(w) for w in warnings]
    for resource in resources:
        source = resource.definition.source
        text = read_source(source)
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
        for expression in [*(meta.get('depends_on', []) if isinstance(meta.get('depends_on', []), list) else []),
                           meta.get('relation'), meta.get('model')]:
            if isinstance(expression, str) and ('ref(' in expression or 'source(' in expression):
                declared.extend(scan_template(expression if '{{' in expression else '{{ ' + expression + ' }}').calls)
        for call in declared:
            target = resolve_reference(resources, resource, call)
            if target:
                kind = ('test_of' if resource.resource_type in {'test', 'unit_test'} else
                        'exposure_of' if resource.resource_type == 'exposure' else
                        'data_read' if resource.resource_type == 'snapshot' else 'semantic_dependency')
                relationships.append(DbtRelationship(target.resource_id, resource.resource_id, kind, 'resolved',
                                                     (resource.definition,)))
                if resource.resource_type == 'snapshot':
                    parsed.operations.append(Operation('DBT_DEPENDENCY', [asset_ref(target)], [asset_ref(resource)],
                        resource.definition.excerpt, resource.definition.start_line, resource.definition.end_line,
                        method='dbt-declaration', evidence_key=resource.resource_id))
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
            parsed.diagnostics.append(Diagnostic('Python model column derivations are unsupported; dependencies only'))
        refs, replacements = {}, []
        for call in calls:
            if call.owner and call.owner != resource.name:
                continue
            target = resolve_reference(resources, resource, call)
            line_prefix = text[text.rfind('\n', 0, call.start) + 1:call.start]
            ordering = 'depends_on:' in line_prefix
            support = evidence(source, text, call.start, call.end)
            if target:
                candidate = call.conditional or resource.resource_type == 'macro'
                kind = ('declared_dependency' if ordering else 'test_of' if resource.resource_type in {'test', 'unit_test'}
                        else 'data_read')
                relationships.append(DbtRelationship(target.resource_id, resource.resource_id,
                    kind, 'candidate' if candidate else 'resolved', (support,)))
                if not candidate and not ordering and resource.resource_type in {'model', 'snapshot'}:
                    token = '__gt_dbt_' + target.resource_id
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
            parsed.operations.append(Operation('DBT_SEED', [AssetRef(file_asset(source.relative_path), kind='file')],
                [asset_ref(resource)], text, 1, max(1, len(text.splitlines())), method='dbt-parser'))
        if resource.resource_type not in {'model', 'snapshot', 'analysis', 'test'}:
            continue
        for warning in facts.diagnostics:
            parsed.diagnostics.append(Diagnostic(warning))
        if resource.metadata.get('language') == 'python':
            parsed.operations.append(Operation('DBT_DEPENDENCY', list(refs.values()), [asset_ref(resource)],
                text, 1, max(1, len(text.splitlines())), method='dbt-python'))
            continue
        unsupported = bool(facts.diagnostics)
        replacements_by_span = {(a, b): value for a, b, value in replacements}
        for start, end, body in facts.tags:
            if (start, end) not in replacements_by_span:
                if body.startswith('config(') or text[start:start + 2] == '{#':
                    replacements_by_span[start, end] = ''.join('\n' if c == '\n' else ' ' for c in text[start:end])
                else:
                    unsupported = True
        if unsupported:
            parsed.diagnostics.append(Diagnostic('Unexpanded macro or conditional SQL; column coverage is partial'))
            if refs and resource.resource_type in {'model', 'snapshot'}:
                parsed.operations.append(Operation('DBT_MODEL_READ', list(refs.values()), [asset_ref(resource)],
                    text, 1, max(1, len(text.splitlines())), method='dbt-parser'))
            continue
        query = text
        for (start, end), value in sorted(replacements_by_span.items(), reverse=True):
            query = query[:start] + value + query[end:]
        if resource.resource_type in {'analysis', 'test'}:
            continue
        model = parse_model_query(query, output=asset_ref(resource), dialect=snapshot.context.dialect,
            primary_evidence=resource.definition, relation_map=refs)
        offset = len(parsed.operations)
        parsed.metadata.setdefault('declared_schemas', []).extend({**record,
            'operation_index': offset + record['operation_index']} for record in model.metadata.get('declared_schemas', []))
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
                    key = '.'.join(components[index:])
                    physical.setdefault(key, []).append(asset_ref(resource))
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
        if resource.resource_type in DATA_TYPES and dependency_sources:
            ref = resource.definition
            parsed.operations.append(Operation('DBT_DEPENDENCY', dependency_sources, [asset_ref(resource)],
                ref.excerpt, ref.start_line, ref.end_line, method='dbt-manifest', evidence_key=uid + ':dependency'))
        query = node.get('compiled_code')
        if query and resource.resource_type == 'model' and node.get('language', 'sql') == 'sql':
            dialect = snapshot.context.dialect or {'postgres': 'postgres', 'snowflake': 'snowflake',
                'bigquery': 'bigquery', 'duckdb': 'duckdb', 'databricks': 'databricks',
                'spark': 'spark', 'redshift': 'redshift'}.get(document.data['metadata'].get('adapter_type'), '')
            model = parse_model_query(query, output=asset_ref(resource), dialect=dialect,
                primary_evidence=resource.definition, relation_map=physical)
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
                for derivation in op.derivations:
                    derivation.setdefault('coverage', []).append('Expression origin: supplied compiled SQL ' + generated.json_pointer)
            parsed.operations.extend(model.operations)
            parsed.diagnostics.extend(model.diagnostics)
    if len(relationships) > limits.max_relationships:
        raise ValueError('dbt relationship budget exceeded')
    parsed.diagnostics.append(Diagnostic('Artifact snapshot: compilation context cannot be certified from source text alone', severity='info'))
    return DbtProjectResult(snapshot, resources, tuple(relationships), resolve_bindings(resources, snapshot),
        tuple(results.values()), tuple(parsed.diagnostics), {'inventory': 'artifact_declared',
            'dependencies': 'artifact_declared', 'columns': 'partial', 'mode': 'artifact',
            'context_status': 'unverifiable', 'schema': 'manifest/v12'}, tuple(generated_evidence))
