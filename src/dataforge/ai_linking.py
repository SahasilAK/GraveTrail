"""Deterministic linking over validated checkpoints, with explicit ambiguous writers."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import replace

import networkx as nx

from dataforge.ai_analysis_store import _run, load_validation_checkpoint
from dataforge.models import canonical


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
