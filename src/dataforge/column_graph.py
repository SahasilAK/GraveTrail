"""Pure, bounded column-trace scenes for the local interactive graph."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from networkx import DiGraph, lexicographical_topological_sort, strongly_connected_components

_SOURCE_FIELDS = {'expression', 'code', 'raw_content', 'statement_preview', 'content', 'original'}


def _coverage(value: Any) -> Any:
    """Copy coverage facts without accidentally forwarding source-bearing fields."""
    if isinstance(value, dict):
        return {key: _coverage(item) for key, item in value.items() if key not in _SOURCE_FIELDS}
    if isinstance(value, list):
        return [_coverage(item) for item in value]
    return value


def _column(reference: dict[str, Any], root_id: str | None) -> dict[str, Any]:
    cid = reference['column_id']
    name = reference.get('column_name') or '(rowset)'
    label = f"{reference.get('table', '')}.{name}".lstrip('.')
    qualifiers = [str(reference[key]) for key in ('scope', 'version') if reference.get(key)]
    if qualifiers:
        label += ' [' + ' · '.join(qualifiers) + ']'
    return {'id': f'column:{cid}', 'kind': 'column', 'column_id': cid, 'label': label,
            'status': 'reference', 'is_root': cid == root_id, 'width': 260, 'height': 64}


def _layout(nodes: dict[str, dict[str, Any]], edges: dict[str, dict[str, Any]]) -> dict[str, int]:
    """Position SCCs as a DAG, retaining every semantic node and cycle edge."""
    graph = DiGraph()
    graph.add_nodes_from(sorted(nodes))
    graph.add_edges_from((edge['source'], edge['target']) for edge in edges.values())
    components = sorted(tuple(sorted(group)) for group in strongly_connected_components(graph))
    owners = {node: index for index, group in enumerate(components) for node in group}
    condensed = DiGraph()
    condensed.add_nodes_from(range(len(components)))
    condensed.add_edges_from((owners[source], owners[target]) for source, target in graph.edges
                             if owners[source] != owners[target])
    layers, offsets = {}, defaultdict(int)
    for index in lexicographical_topological_sort(condensed, key=lambda i: components[i]):
        layer = max((layers[parent] + 1 for parent in condensed.predecessors(index)), default=0)
        layers[index] = layer
        group = components[index]
        cyclic = len(group) > 1 or any(graph.has_edge(node, node) for node in group)
        for node in group:
            nodes[node].update(x=40 + layer * 340, y=40 + offsets[layer], cycle=cyclic)
            offsets[layer] += 100
    for edge in edges.values():
        source, target = nodes[edge['source']], nodes[edge['target']]
        x1, y1 = source['x'] + source['width'], source['y'] + source['height'] // 2
        x2, y2 = target['x'], target['y'] + target['height'] // 2
        cyclic = owners[source['id']] == owners[target['id']] and source['cycle']
        edge['cycle'] = cyclic
        if x2 <= x1:
            # Route same-SCC/back edges around the right side of the boxes.
            bend = max(x1, x2 + target['width']) + 60
            edge['path'] = f'M {x1} {y1} C {bend} {y1}, {bend} {y2}, {x2} {y2}'
        else:
            middle = (x1 + x2) // 2
            edge['path'] = f'M {x1} {y1} C {middle} {y1}, {middle} {y2}, {x2} {y2}'
    return {'x': 0, 'y': 0,
            'width': max((n['x'] + n['width'] + 100 for n in nodes.values()), default=320),
            'height': max((n['y'] + n['height'] + 40 for n in nodes.values()), default=160)}


def build_column_scene(trace: dict[str, Any], root: dict[str, Any] | None, *, status: str = 'all',
                       max_nodes: int = 600, max_edges: int = 1200) -> dict[str, Any]:
    """Adapt an existing trace, keeping complete derivation units within display caps.

    ``root`` is a server-resolved catalog reference. Dependency arrows always follow
    input → transformation → output, independently of traversal direction. Effects
    come only from returned paths; downstream sibling inputs remain context.
    This function performs no catalog lookup, traversal, source access or analysis.
    """
    if status not in {'all', 'verified', 'inferred', 'unresolved'}:
        raise ValueError('Invalid status')
    if type(max_nodes) is not int or max_nodes < 1 or type(max_edges) is not int or max_edges < 0:
        raise ValueError('Scene caps require at least one node and a nonnegative edge count')
    root_id = root['column_id'] if root else None
    all_nodes = {}
    if root:
        all_nodes[f'column:{root_id}'] = _column(root, root_id)
    all_edges, units = {}, []
    paths = defaultdict(list)
    for path in trace.get('paths', []):
        paths[path['derivation_id']].append(path)
    for derivation in sorted(trace.get('derivations', []), key=lambda item: item['derivation_id']):
        did = derivation['derivation_id']
        node_id = f'derivation:{did}'
        all_nodes[node_id] = {'id': node_id, 'kind': 'transformation', 'derivation_id': did,
                              'label': derivation.get('category', 'unknown'),
                              'status': derivation.get('status', 'unresolved'),
                              'is_root': False, 'width': 260, 'height': 64}
        target = derivation['target']
        target_id = f"column:{target['column_id']}"
        all_nodes.setdefault(target_id, _column(target, root_id))
        unit_nodes = {node_id, target_id}
        unit_edges = set()
        roles = defaultdict(set)
        for item in derivation.get('inputs', []):
            source_id = f"column:{item['column_id']}"
            all_nodes.setdefault(source_id, _column(item, root_id))
            unit_nodes.add(source_id)
            roles[source_id].add(item.get('role', 'value'))
        derivation_paths = paths[did]
        for source, target_node in [(source, node_id) for source in sorted(roles)] + [(node_id, target_id)]:
            edge_key = json.dumps([source, target_node, did], separators=(',', ':'))
            edge_id = 'edge:' + hashlib.sha256(edge_key.encode()).hexdigest()[:24]
            matched = derivation_paths
            if source != node_id and trace.get('direction') == 'downstream':
                matched = [path for path in derivation_paths
                           if f"column:{path.get('parent_column_id')}" == source]
            context = source != node_id and trace.get('direction') == 'downstream' and not matched
            all_edges[edge_id] = {'id': edge_id, 'source': source, 'target': target_node,
                                  'derivation_id': did, 'roles': sorted(roles.get(source, set())),
                                  'effects': sorted({path['effect'] for path in matched if path.get('effect')}),
                                  'context_only': context}
            unit_edges.add(edge_id)
        units.append((unit_nodes, unit_edges))
    kept_nodes = {f'column:{root_id}'} if root else set()
    kept_edges = set()
    omitted_derivations = 0
    for unit_nodes, unit_edges in units:
        if len(kept_nodes | unit_nodes) > max_nodes or len(kept_edges | unit_edges) > max_edges:
            omitted_derivations += 1
            continue
        kept_nodes.update(unit_nodes)
        kept_edges.update(unit_edges)
    nodes = {node: all_nodes[node] for node in sorted(kept_nodes)}
    edges = {edge: all_edges[edge] for edge in sorted(kept_edges)}
    bounds = _layout(nodes, edges)
    # Stream the canonical snapshot into a fixed-size digest; never send its source text to the browser.
    digest = hashlib.sha256()
    encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    for chunk in encoder.iterencode({'trace': trace, 'root': root, 'status': status,
                                     'max_nodes': max_nodes, 'max_edges': max_edges}):
        digest.update(chunk.encode())
    return {'trace_key': digest.hexdigest(), 'nodes': list(nodes.values()), 'edges': list(edges.values()),
            'bounds': bounds, 'coverage': _coverage(trace.get('coverage', [])),
            'trace_complete': trace.get('complete', False), 'display_truncated': bool(omitted_derivations),
            'omitted_derivations': omitted_derivations, 'omitted_nodes': len(all_nodes) - len(nodes),
            'omitted_edges': len(all_edges) - len(edges)}
