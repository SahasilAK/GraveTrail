"""Cycle-safe traversal and evidence-preserving temporary contraction."""
from __future__ import annotations

from collections import deque

import networkx as nx

from dataforge.asset_identity import asset_job, asset_label


class LineageGraph:
    def __init__(self, assets: list[dict], edges: list[dict], min_confidence=0., include_inferred=True):
        self.graph = nx.DiGraph()
        self.graph.graph["unresolved_edges"] = []
        self.truncated = False
        for a in assets:
            self.graph.add_node(a["asset_id"], **a)
        for e in edges:
            if e.get("confidence", 1.) < min_confidence or (not include_inferred and e.get("status") == "inferred"):
                continue
            s, t = e["source_id"], e["target_id"]
            if s not in self.graph or t not in self.graph:
                # NetworkX otherwise invents empty nodes that break every asset consumer.
                self.unresolved_edges.append(e)
                self.truncated = True
                continue
            if e.get('status') == 'unresolved':
                self.unresolved_edges.append(e)
                continue
            if self.graph.has_edge(s, t):
                self.graph[s][t]["evidence"].append(e)
            else:
                self.graph.add_edge(s, t, evidence=[e], intermediates=[])

    @property
    def nodes(self):
        return self.graph.nodes

    @property
    def unresolved_edges(self):
        return self.graph.graph.get("unresolved_edges", [])

    @classmethod
    def _from_graph(cls, graph, truncated=False):
        instance = cls([], [])
        instance.graph = graph
        instance.truncated = truncated
        return instance

    def search(self, query: str) -> list[dict]:
        return [a for _, a in self.graph.nodes(data=True) if query.casefold() in a["name"].casefold()]

    def focus(self, asset: str, direction="upstream", depth=5, limit=200):
        if asset not in self.graph:
            return self._from_graph(nx.DiGraph())
        seen = {asset}
        queue = deque([(asset, 0)])
        truncated = self.truncated
        while queue:
            node, level = queue.popleft()
            if level >= depth:
                continue
            neighbors = []
            if direction in {"upstream", "combined"}:
                neighbors.extend(self.graph.predecessors(node))
            if direction in {"downstream", "combined"}:
                neighbors.extend(self.graph.successors(node))
            for neighbor in sorted(set(neighbors)):
                if neighbor not in seen:
                    if len(seen) >= limit:
                        truncated = True
                        continue
                    seen.add(neighbor)
                    queue.append((neighbor, level + 1))
        for node in seen:
            neighbors = set()
            if direction in {'upstream', 'combined'}:
                neighbors.update(self.graph.predecessors(node))
            if direction in {'downstream', 'combined'}:
                neighbors.update(self.graph.successors(node))
            if neighbors - seen:
                truncated = True
                break
        graph = self.graph.subgraph(seen).copy()
        graph.graph['unresolved_edges'] = [edge for edge in self.unresolved_edges
            if edge.get('source_id') not in self.graph or edge.get('target_id') not in self.graph
            or (direction in {'upstream', 'combined'} and edge.get('target_id') in seen)
            or (direction in {'downstream', 'combined'} and edge.get('source_id') in seen)]
        return self._from_graph(graph, truncated)

    def cycles(self) -> list[list[str]]:
        return [sorted(c) for c in nx.strongly_connected_components(self.graph)
                if len(c) > 1 or self.graph.has_edge(next(iter(c)), next(iter(c)))]

    def simplified(self, edge_limit=20000, keep=(), *, preserve_paths=False, evidence_limit=None):
        evidence_count = sum(len(attrs['evidence']) for _, _, attrs in self.graph.edges(data=True))
        if evidence_limit is not None and evidence_count > evidence_limit:
            raise ValueError('Temporary-stage evidence limit exceeded; include temporary stages or narrow workspace')
        graph = self.graph.copy()
        for node, attrs in list(graph.nodes(data=True)):
            if not attrs.get("temporary") or node in keep:
                continue
            if any(node in (e['source_id'], e['target_id']) for e in self.unresolved_edges):
                # Retain the exact location of uncertainty even with parallel accepted support.
                continue
            inputs, outputs = list(graph.predecessors(node)), list(graph.successors(node))
            if not inputs or not outputs or graph.has_edge(node, node):
                continue
            if len(inputs) * len(outputs) + graph.number_of_edges() > edge_limit:
                continue
            # Parallel routes cannot become an apparently sequential list of intermediates.
            if preserve_paths and any(graph.has_edge(source, target) for source in inputs for target in outputs):
                continue
            if evidence_limit is not None:
                removed = sum(len(graph[s][t]['evidence']) for s, t in
                    {*graph.in_edges(node), *graph.out_edges(node)})
                added = sum(len(graph[source][node]['evidence']) + len(graph[node][target]['evidence'])
                    for source in inputs for target in outputs)
                if evidence_count - removed + added > evidence_limit:
                    raise ValueError('Temporary-stage evidence limit exceeded; include temporary stages or narrow workspace')
                evidence_count += added - removed
            for source in inputs:
                for target in outputs:
                    if source == node or target == node:
                        continue
                    left, right = graph[source][node], graph[node][target]
                    existing = graph[source][target] if graph.has_edge(source, target) else {}
                    evidence = {e["edge_id"]: e for e in [*existing.get("evidence", []), *left["evidence"], *right["evidence"]]}
                    intermediate = list(dict.fromkeys([*existing.get("intermediates", []),
                        *left.get("intermediates", []), asset_label(attrs), *right.get("intermediates", [])]))
                    graph.add_edge(source, target, evidence=list(evidence.values()), intermediates=intermediate)
            graph.remove_node(node)
        return self._from_graph(graph, self.truncated)

    def lineage_rows(self):
        components = list(nx.strongly_connected_components(self.graph))
        condensed = nx.condensation(self.graph, components)
        generations = {node: generation + 1 for generation, group in enumerate(nx.topological_generations(condensed)) for node in group}
        mapping = condensed.graph["mapping"]
        rows = []
        for source, target, attrs in self.graph.edges(data=True):
            for evidence in attrs["evidence"]:
                rows.append({"source": self.nodes[source]["name"], "target": self.nodes[target]["name"],
                    "source_job": asset_job(self.nodes[source]) or "", "target_job": asset_job(self.nodes[target]) or "",
                    "logical_step": generations[mapping[target]], "operation": evidence.get("kind", ""),
                    "file": evidence.get("relative_path", ""), "start_line": evidence.get("start_line", 1),
                    "end_line": evidence.get("end_line", 1), "confidence": evidence.get("confidence", 1),
                    "method": evidence.get("method", ""), "status": evidence.get("status", ""),
                    "intermediates": ", ".join(attrs.get("intermediates", [])),
                    "file_id": evidence.get("file_id", ""), "statement_id": evidence.get("statement_id", "")})
        for evidence in self.unresolved_edges:
            source, target = evidence['source_id'], evidence['target_id']
            if source not in self.nodes or target not in self.nodes:
                continue
            rows.append({'source': self.nodes[source]['name'], 'target': self.nodes[target]['name'],
                'source_job': asset_job(self.nodes[source]) or '', 'target_job': asset_job(self.nodes[target]) or '',
                'logical_step': generations[mapping[target]], 'operation': evidence.get('kind', ''),
                'file': evidence.get('relative_path', ''), 'start_line': evidence.get('start_line', 1),
                'end_line': evidence.get('end_line', 1), 'confidence': evidence.get('confidence', 1),
                'method': evidence.get('method', ''), 'status': 'unresolved', 'intermediates': '',
                'file_id': evidence.get('file_id', ''), 'statement_id': evidence.get('statement_id', '')})
        return sorted(rows, key=lambda r: (r["logical_step"], r["source"], r["file"]))

    def root_paths(self, target, limit=50, depth=15):
        paths = []
        queue = deque([[target]])
        while queue and len(paths) < limit:
            path = queue.popleft()
            parents = [p for p in self.graph.predecessors(path[0]) if p not in path]
            if not parents or len(path) >= depth:
                paths.append(path)
            else:
                # Bound pending paths as well as returned paths in dense DAGs.
                for parent in parents[:max(0, limit - len(queue) - len(paths))]:
                    queue.append([parent, *path])
        return paths

    def path_report(self, asset, direction="upstream", limit=50, depth=15, *,
                    max_relationships=None, max_evidence=None, include_code=False):
        """Bounded ordered paths over this topology, with evidence and explicit boundaries."""
        if direction not in {"upstream", "downstream"} or not 1 <= limit <= 500 or not 1 <= depth <= 30:
            raise ValueError("Use upstream/downstream, 1–500 paths and 1–30 depth")
        if any(value is not None and (type(value) is not int or value < 1)
               for value in [max_relationships, max_evidence]):
            raise ValueError('Path relationship/evidence limits must be positive integers')
        report = {"selected_asset": asset, "direction": direction, "max_paths": limit,
                  "max_depth": depth, "truncated": self.truncated, "paths": [],
                  'complete': not self.truncated, 'boundaries': []}
        if asset not in self.graph:
            return report
        pending = deque([([asset], None)])
        fields = {"edge_id", "operation_id", "statement_id", "file_id", "relative_path", "source_hash",
                  "start_line", "end_line", "kind", "method", "status", "confidence", "source_id", "target_id"}
        if include_code:
            fields.add('code')
        relationship_count = evidence_count = 0
        while pending:
            path, boundary = pending.popleft()
            node = path[0] if direction == "upstream" else path[-1]
            neighbors = sorted(self.graph.predecessors(node) if direction == "upstream"
                               else self.graph.successors(node))
            uncertain = [e for e in self.unresolved_edges if
                         e.get('target_id' if direction == 'upstream' else 'source_id') == node]
            if uncertain:
                report['complete'] = False
                for evidence in uncertain:
                    citation = {k: v for k, v in evidence.items() if k in fields}
                    if citation not in report['boundaries']:
                        report['boundaries'].append(citation)
                        if max_evidence is not None and evidence_count + len(report['boundaries']) > max_evidence:
                            raise ValueError('Path evidence limit exceeded; narrow the selection')
            blocked = [e for e in uncertain if not self.graph.has_edge(e['source_id'], e['target_id'])]
            if boundary is None:
                if not neighbors:
                    boundary = 'unresolved' if blocked else "root" if direction == "upstream" else "terminal"
                elif len(path) - 1 >= depth:
                    boundary = "depth"
                    report["truncated"] = True
                elif blocked and len(report['paths']) + len(pending) < limit:
                    pending.append((path, 'unresolved'))
            if boundary is not None:
                if boundary == 'cycle':
                    report['truncated'] = True
                if max_relationships is not None:
                    remaining = max_relationships - relationship_count
                    if len(path) > 1 and remaining == 0:
                        report['truncated'] = True
                        break
                    if len(path) - 1 > remaining:
                        path = path[-remaining - 1:] if direction == 'upstream' else path[:remaining + 1]
                        boundary = 'relationship_limit'
                        report['truncated'] = True
                steps = []
                for source, target in zip(path, path[1:]):
                    edge = self.graph[source][target]
                    evidence_count += len(edge['evidence'])
                    if max_evidence is not None and evidence_count + len(report['boundaries']) > max_evidence:
                        raise ValueError('Path evidence limit exceeded; narrow the selection')
                    relationship_count += 1
                    steps.append({"source": self.nodes[source]["name"], "target": self.nodes[target]["name"],
                        "source_id": source, "target_id": target, "intermediates": edge.get("intermediates", []),
                        "evidence": [{k: v for k, v in e.items() if k in fields} for e in edge["evidence"]]})
                report["paths"].append({"path_id": len(report["paths"]) + 1, "node_ids": path,
                    "nodes": [self.nodes[n]["name"] for n in path], "boundary": boundary, "steps": steps})
            else:
                for neighbor in neighbors:
                    if len(report["paths"]) + len(pending) >= limit:
                        report["truncated"] = True
                        break
                    candidate = [neighbor, *path] if direction == "upstream" else [*path, neighbor]
                    pending.append((candidate, "cycle" if neighbor in path else None))
        report['complete'] = report['complete'] and not report['truncated']
        return report
