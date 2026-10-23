"""Deterministic linking over validated checkpoints, with explicit ambiguous writers."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, replace

import networkx as nx

from dataforge.ai_analysis_store import _run, load_validation_checkpoint
from dataforge.models import canonical


def _resource_key(resource, file):
    name = resource.name.strip() if any(q in resource.name for q in '"`[') else canonical(resource.name)
    if resource.identity:
        return resource.identity
    scope = resource.scope or (file.file_id if resource.temporary or name.startswith(('work.', '#')) else '')
    return file.source_kind + ':' + scope + ':' + name


def build_operation_graph(file_extractions):
    """Versioned resources and operations, preserving parallel dependency roles."""
    graph, writers = nx.MultiDiGraph(), defaultdict(list)
    for file in file_extractions:
        for op in file.operations:
            oid = 'operation:' + op.operation_id
            graph.add_node(oid, kind='operation', operation_id=op.operation_id, file_id=file.file_id,
                           evidence=[r.model_dump() for r in op.evidence], limitations=op.limitations, order=op.order)
            for resource in op.writes:
                writers[_resource_key(resource, file)].append((file, op, resource))
    for key, entries in writers.items():
        for file, op, resource in entries:
            version = str(resource.version) if resource.version != '' else (op.operation_id if len(entries) > 1 else '')
            rid = key + ('@' + version if version else '')
            graph.add_node(rid, kind='resource', name=resource.name, identity=key, version=version,
                           external=False, unresolved=len(entries) > 1 and not resource.version,
                           evidence=[r.model_dump() for r in op.evidence])
            graph.add_edge('operation:' + op.operation_id, rid, role='write', evidence=[r.model_dump() for r in op.evidence])
    for file in file_extractions:
        for op in file.operations:
            oid = 'operation:' + op.operation_id
            reads = list(op.reads)
            from dataforge.ai_analysis_models import ResourceReference
            for derivation in op.derivations:
                for dependency in derivation.inputs:
                    if not any(r.name == dependency.table and str(r.version) == str(dependency.version) for r in reads):
                        reads.append(ResourceReference(name=dependency.table, scope=dependency.scope, version=dependency.version))
            for resource in reads:
                key = _resource_key(resource, file)
                entries = [e for e in writers.get(key, []) if e[1].operation_id != op.operation_id]
                if resource.version != '':
                    entries = [e for e in entries if str(e[2].version) == str(resource.version)]
                if len(entries) > 1 and op.order is not None:
                    preceding = [e for e in entries if e[0].file_id == file.file_id and e[1].order is not None and e[1].order < op.order]
                    if preceding:
                        last = max(e[1].order for e in preceding)
                        entries = [e for e in preceding if e[1].order == last]
                ambiguous = len(entries) > 1
                if len(entries) == 1:
                    _, producer, output = entries[0]
                    version = str(output.version) if output.version != '' else (producer.operation_id if len(writers[key]) > 1 else '')
                    rid = key + ('@' + version if version else '')
                else:
                    rid = key + ('@unresolved:' + op.operation_id if ambiguous else ('@' + str(resource.version) if resource.version != '' else ''))
                    graph.add_node(rid, kind='resource', name=resource.name, identity=key, version=str(resource.version),
                        external=not ambiguous, unresolved=ambiguous, evidence=[r.model_dump() for r in op.evidence])
                roles = [(i.role, d.fact_id, ordinal, i.column) for d in op.derivations for ordinal, i in enumerate(d.inputs)
                         if i.table == resource.name and str(i.version) == str(resource.version)] or [('rowset', '', 0, '')]
                for role, fact_id, ordinal, column in roles:
                    graph.add_edge(rid, oid, role=role, fact_id=fact_id, ordinal=ordinal, column=column,
                                   evidence=[r.model_dump() for r in op.evidence])
    return graph


@dataclass(frozen=True)
class UpstreamSlice:
    operation_ids: list[str]
    resource_ids: list[str]
    references: list[dict]
    external_inputs: list[str]
    unresolved: list[str]
    cycles: list[list[str]]
    execution_order: list[str] | None


def upstream_operations(graph, target_resource_id):
    if target_resource_id not in graph or graph.nodes[target_resource_id]['kind'] != 'resource':
        raise ValueError('Select an existing resource/version')
    nodes = nx.ancestors(graph, target_resource_id) | {target_resource_id}
    subgraph = graph.subgraph(nodes)
    cycles = [sorted(c) for c in nx.strongly_connected_components(subgraph) if len(c) > 1 or any(subgraph.has_edge(n, n) for n in c)]
    unresolved = sorted(n for n in nodes if graph.nodes[n].get('unresolved') or graph.nodes[n].get('limitations'))
    operations = sorted(graph.nodes[n]['operation_id'] for n in nodes if graph.nodes[n]['kind'] == 'operation')
    references = {json.dumps(ref, sort_keys=True): ref for n in nodes for ref in graph.nodes[n].get('evidence', [])}
    order = None
    operation_nodes = [n for n in nodes if graph.nodes[n]['kind'] == 'operation']
    known_order = all(nx.has_path(subgraph, a, b) or nx.has_path(subgraph, b, a) or
        (graph.nodes[a]['file_id'] == graph.nodes[b]['file_id'] and
         graph.nodes[a]['order'] is not None and graph.nodes[b]['order'] is not None and
         graph.nodes[a]['order'] != graph.nodes[b]['order'])
        for i, a in enumerate(operation_nodes) for b in operation_nodes[i+1:])
    if not cycles and not unresolved and known_order:
        order = [graph.nodes[n]['operation_id'] for n in nx.lexicographical_topological_sort(subgraph)
                 if graph.nodes[n]['kind'] == 'operation']
    return UpstreamSlice(operations, sorted(n for n in nodes if graph.nodes[n]['kind'] == 'resource'),
        [references[k] for k in sorted(references)], sorted(n for n in nodes if graph.nodes[n].get('external')),
        unresolved, cycles, order)


@dataclass(frozen=True)
class LinkedAnalysis:
    files: list
    graph: nx.MultiDiGraph
    unresolved: list[str]
    coverage: dict


def link_file_extractions(files, settings):
    graph = build_operation_graph(files)
    unresolved = sorted(n for n, data in graph.nodes(data=True) if data.get('unresolved'))
    return LinkedAnalysis(files, graph, unresolved, {'processed_files': len(files),
        'semantic_incomplete': sum(f.semantic_coverage != 'model_reported_complete' for f in files)})


def to_publication_results(linked, inventory):
    from dataforge.models import AssetRef, Diagnostic, Operation, ParseResult, Usage
    output = []
    for file in linked.files:
        metadata = inventory[file.file_id]
        source = metadata['source_text']
        parsed = ParseResult(metadata={'ai_protocol': 5, 'source_kind': file.source_kind,
            'semantic_coverage': file.semantic_coverage, 'provenance': file.provenance})
        for record in file.operations:
            own = [r for r in record.evidence if r.file_id == file.file_id]
            if not own:
                raise ValueError('operation_missing_file_evidence')
            start, end = min(r.start_offset for r in own), max(r.end_offset for r in own)
            oid = 'operation:' + record.operation_id
            inputs = list(dict.fromkeys(n for n, _ in linked.graph.in_edges(oid)))
            outputs = list(dict.fromkeys(n for _, n in linked.graph.out_edges(oid)))
            def asset(node):
                data = linked.graph.nodes[node]
                return AssetRef(data['name'], kind='unresolved' if data.get('unresolved') else 'table', identity=node)
            by_name = {linked.graph.nodes[n]['name']: n for n in [*inputs, *outputs]}
            dependencies = {(edge.get('fact_id'), edge.get('ordinal')): n
                for n, _, edge in linked.graph.in_edges(oid, data=True) if edge.get('fact_id')}
            derivations = []
            for fact in record.derivations:
                expression = fact.expression
                text = inventory[expression.file_id]['source_text'][expression.start_offset:expression.end_offset] if expression else ''
                derivations.append({'target_table': fact.target_table, 'target_column': fact.target_column,
                    'target_identity': by_name.get(fact.target_table, ''), 'target_version': fact.version,
                    'expression': text, 'category': fact.category, 'scope': fact.scope, 'branch': fact.branch,
                    'ordinal': fact.ordinal, 'status': 'unresolved' if fact.target_column == '*' or any(i.column == '*' for i in fact.inputs) else 'inferred',
                    'coverage': [*record.limitations, *(['unknown_wildcard_schema'] if fact.target_column == '*' or any(i.column == '*' for i in fact.inputs) else [])],
                    'inputs': [{**i.model_dump(), 'table_identity': dependencies.get((fact.fact_id, j), by_name.get(i.table, ''))}
                               for j, i in enumerate(fact.inputs)]})
            usages = [Usage(u.table, u.column, u.context, status='inferred', table_identity=by_name.get(u.table, '')) for u in record.usages]
            parsed.operations.append(Operation(record.kind, [asset(n) for n in inputs], [asset(n) for n in outputs],
                source[start:end], source.count('\n', 0, start) + 1, source.count('\n', 0, end) + 1,
                method='ai-project', confidence=.8, evidence_key=record.operation_id, usages=usages,
                derivations=derivations, warnings=record.limitations))
        parsed.diagnostics.extend(Diagnostic(reason) for reason in file.unresolved)
        if file.semantic_coverage != 'model_reported_complete':
            parsed.diagnostics.append(Diagnostic('AI semantic coverage is incomplete'))
        output.append(({k: v for k, v in metadata.items() if k != 'source_text'}, parsed))
    return output


def load_link_snapshot(store, workspace, run_id, units, context_hashes):
    _run(store, workspace, run_id)
    facts = []
    for unit in units:
        checkpoint = load_validation_checkpoint(store, workspace, run_id, unit, context_hashes[unit.unit_id])
        if not checkpoint:
            raise ValueError('missing_required_unit_checkpoint')
        facts.extend(checkpoint[0].accepted)
    return facts


def link_stored_facts(facts, *, case_sensitive=False):
    def norm(name):
        return name.strip() if case_sensitive or any(c in name for c in '\"`[') else canonical(name)
    def identity(fact, name):
        operation = fact.detail.get('operation', {})
        refs = [*operation.get('sources', []), *operation.get('targets', [])]
        matches = {r.get('identity') for r in refs if norm(r['name']) == norm(name) and r.get('identity')}
        if len(matches) == 1:
            return next(iter(matches))
        job = fact.detail.get('job_id', '') if name.lower().startswith(('work.', '#')) else ''
        return job + ':' + norm(name)
    producers, graph, links, unresolved = defaultdict(list), nx.DiGraph(), [], []
    tables = set()
    for fact in facts:
        if fact.status == 'unresolved':
            continue
        if fact.kind == 'table_edge':
            source, target = identity(fact, fact.source), identity(fact, fact.target)
            tables.add((source, target))
            graph.add_edge(source, target)
        elif fact.kind == 'derivation' and not fact.scope:
            producers[(identity(fact, fact.table), norm(fact.column), str(fact.version))].append(fact)
    seen = set()
    for fact in facts:
        if fact.kind != 'derivation' or fact.status == 'unresolved':
            continue
        for item in fact.inputs:
            if item.scope:
                continue
            key = (identity(fact, item.table), norm(item.column), str(item.version))
            candidates = [p for p in producers.get(key, []) if p.evidence_key != fact.evidence_key]
            writers = {p.evidence_key for p in candidates}
            if len(writers) > 1:
                unresolved.append({'unit_id': fact.unit_id, 'table': item.table, 'column': item.column,
                    'candidate_units': sorted({p.unit_id for p in candidates}),
                    'reason': 'multiple_writers_without_execution_order'})
            elif len(writers) == 1:
                producer = candidates[0]
                signature = (producer.unit_id, fact.unit_id, key, item.role)
                if signature not in seen:
                    seen.add(signature)
                    links.append({'producer': producer.unit_id, 'consumer': fact.unit_id,
                                  'table': item.table, 'column': item.column, 'role': item.role})
    cycles = sorted(sorted(component) for component in nx.strongly_connected_components(graph)
                    if len(component) > 1 or any(graph.has_edge(n, n) for n in component))
    fingerprint = hashlib.sha256(json.dumps([f.model_dump(exclude={'detail', 'evidence'}) for f in facts],
                                            sort_keys=True).encode()).hexdigest()
    return {'fingerprint': fingerprint, 'table_links': sorted(tables), 'column_links': links,
            'unresolved': unresolved, 'cycles': cycles, 'complete': not unresolved}


def compose_dbt_publication(projects, results, *, mode):
    """Keep structural inventory; persisted project snapshots use the chosen AI facts."""
    by_file = {m['file_id']: (m, parsed) for m, parsed in results}
    composed = []
    for project in projects:
        files = tuple(by_file[m['file_id']] for m, _ in project.file_results)
        accepted_pairs = {(s.identity, t.identity) for _, p in files for op in p.operations
                          for s in op.sources for t in op.targets if s.identity and t.identity}
        relations = tuple(r for r in project.relationships if mode == 'hybrid' or r.kind not in
                          {'data_read', 'artifact_dependency'} or
                          ('dbt:' + r.source_id, 'dbt:' + r.target_id) in accepted_pairs)
        composed.append(replace(project, file_results=files, relationships=relations,
                                coverage={**project.coverage, 'ai_mode': mode, 'columns': 'partial'}))
    return composed
