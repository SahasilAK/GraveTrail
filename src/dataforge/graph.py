"""Cycle-safe traversal and evidence-preserving temporary contraction."""
from __future__ import annotations

from collections import deque

import networkx as nx


class LineageGraph:
    def __init__(self, assets: list[dict], edges: list[dict]):
        self.graph = nx.DiGraph()
        self.truncated = False
        for a in assets:
            self.graph.add_node(a["asset_id"], **a)
        for e in edges:
            s, t = e["source_id"], e["target_id"]
            if self.graph.has_edge(s, t):
                self.graph[s][t]["evidence"].append(e)
            else:
                self.graph.add_edge(s, t, evidence=[e], intermediates=[])

    @property
    def nodes(self):
        return self.graph.nodes

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
        truncated = False
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
        return self._from_graph(self.graph.subgraph(seen).copy(), truncated)

    def cycles(self) -> list[list[str]]:
        return [sorted(c) for c in nx.strongly_connected_components(self.graph)
                if len(c) > 1 or self.graph.has_edge(next(iter(c)), next(iter(c)))]

    def simplified(self, edge_limit=20000, keep=()):
        graph = self.graph.copy()
        for node, attrs in list(graph.nodes(data=True)):
            if not attrs.get("temporary") or node in keep:
                continue
            inputs, outputs = list(graph.predecessors(node)), list(graph.successors(node))
            if not inputs or not outputs or graph.has_edge(node, node):
                continue
            if len(inputs) * len(outputs) + graph.number_of_edges() > edge_limit:
                continue
            for source in inputs:
                for target in outputs:
                    if source == node or target == node:
                        continue
                    left, right = graph[source][node], graph[node][target]
                    existing = graph[source][target] if graph.has_edge(source, target) else {}
                    evidence = {e["edge_id"]: e for e in [*existing.get("evidence", []), *left["evidence"], *right["evidence"]]}
                    intermediate = list(dict.fromkeys([*existing.get("intermediates", []),
                        *left.get("intermediates", []), attrs["name"], *right.get("intermediates", [])]))
                    graph.add_edge(source, target, evidence=list(evidence.values()), intermediates=intermediate)
            graph.remove_node(node)
        return self._from_graph(graph)

    def lineage_rows(self):
        components = list(nx.strongly_connected_components(self.graph))
        condensed = nx.condensation(self.graph, components)
        generations = {node: generation + 1 for generation, group in enumerate(nx.topological_generations(condensed)) for node in group}
        mapping = condensed.graph["mapping"]
        rows = []
        for source, target, attrs in self.graph.edges(data=True):
            for evidence in attrs["evidence"]:
                rows.append({"source": self.nodes[source]["name"], "target": self.nodes[target]["name"],
                    "logical_step": generations[mapping[target]], "operation": evidence.get("kind", ""),
                    "file": evidence.get("relative_path", ""), "start_line": evidence.get("start_line", 1),
                    "end_line": evidence.get("end_line", 1), "confidence": evidence.get("confidence", 1),
                    "method": evidence.get("method", ""), "status": evidence.get("status", ""),
                    "intermediates": ", ".join(attrs.get("intermediates", [])),
                    "file_id": evidence.get("file_id", ""), "statement_id": evidence.get("statement_id", "")})
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

    def path_report(self, asset, direction="upstream", limit=50, depth=15):
        """Bounded ordered paths over this topology, with evidence and explicit boundaries."""
        if direction not in {"upstream", "downstream"} or not 1 <= limit <= 500 or not 1 <= depth <= 30:
            raise ValueError("Use upstream/downstream, 1–500 paths and 1–30 depth")
        report = {"selected_asset": asset, "direction": direction, "max_paths": limit,
                  "max_depth": depth, "truncated": self.truncated, "paths": []}
        if asset not in self.graph:
            return report
        pending = deque([([asset], None)])
        fields = {"edge_id", "operation_id", "statement_id", "file_id", "relative_path", "source_hash",
                  "start_line", "end_line", "kind", "method", "status", "confidence"}
        while pending:
            path, boundary = pending.popleft()
            node = path[0] if direction == "upstream" else path[-1]
            neighbors = sorted(self.graph.predecessors(node) if direction == "upstream"
                               else self.graph.successors(node))
            if boundary is None:
                if not neighbors:
                    boundary = "root" if direction == "upstream" else "terminal"
                elif len(path) - 1 >= depth:
                    boundary = "depth"
                    report["truncated"] = True
            if boundary is not None:
                steps = []
                for source, target in zip(path, path[1:]):
                    edge = self.graph[source][target]
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
        return report
