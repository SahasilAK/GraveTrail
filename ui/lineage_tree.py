"""Lazy, bounded dependency branches; session state contains controls, never rendered trees."""
import streamlit as st

from dataforge.models import stable_id


def render_tree(graph, asset, direction, depth=5, limit=150, key="tree", default_expansion=1):
    with st.container(horizontal=True, vertical_alignment="bottom"):
        expanded_depth = st.number_input("Expand tree to depth", 1, depth, min(default_expansion or 1, depth),
                                         key=key + "_depth")
        if st.button("Expand to depth", key=key + "_expand"):
            st.session_state[key + "_generation"] = st.session_state.get(key + "_generation", 0) + 1
            st.session_state[key + "_initial"] = expanded_depth
        if st.button("Collapse tree", key=key + "_collapse"):
            st.session_state[key + "_generation"] = st.session_state.get(key + "_generation", 0) + 1
            st.session_state[key + "_initial"] = 0
    generation = st.session_state.get(key + "_generation", 0)
    initial = st.session_state.get(key + "_initial", default_expansion)
    remaining = [limit]
    clipped = [False]

    def branch(node, trail, level):
        neighbors = sorted(graph.graph.predecessors(node) if direction == "upstream"
                           else graph.graph.successors(node), key=lambda n: graph.nodes[n]["name"])
        for neighbor in neighbors:
            if remaining[0] <= 0:
                clipped[0] = True
                return
            remaining[0] -= 1
            attrs = graph.nodes[neighbor]
            if neighbor in trail:
                st.caption(f"Cycle returns to {attrs['name']}; branch stops here.")
                continue
            edge = graph.graph[neighbor][node] if direction == "upstream" else graph.graph[node][neighbor]
            count = graph.graph.in_degree(neighbor) if direction == "upstream" else graph.graph.out_degree(neighbor)
            label = f"{attrs['name']} • {count} dependencies • {attrs.get('kind', 'asset')}"
            container = st.expander(label, expanded=level < initial, on_change="rerun",
                                    key=f"{key}_{generation}_{stable_id(*trail, neighbor)}")
            if not container.open:
                continue
            with container:
                evidence = edge["evidence"]
                st.caption(f"{len(evidence)} evidence records; " + ", ".join(dict.fromkeys(
                    e.get("kind", "Reference") + " [" + e.get("status", "unknown") + "]" for e in evidence)))
                st.caption("Files: " + ", ".join(sorted({e.get("relative_path", "unknown") for e in evidence})))
                confidence = min((e.get("confidence", 1) for e in evidence), default=1)
                st.caption(f"Minimum evidence confidence: {confidence:.0%}")
                if count and level + 1 < depth:
                    branch(neighbor, (*trail, neighbor), level + 1)
                elif count:
                    st.caption("Traversal depth reached. Increase depth to continue.")

    if asset in graph.nodes:
        branch(asset, (asset,), 0)
    if clipped[0]:
        st.info(f"Tree limited to {limit} visible entries. Collapse branches or select a closer asset.")
    elif remaining[0] == limit:
        st.caption("No dependencies in this direction.")
