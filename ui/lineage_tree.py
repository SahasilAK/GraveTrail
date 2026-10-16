"""Lazy, bounded dependency branches; session state contains controls, never rendered trees."""
import re

import streamlit as st

from dataforge.models import stable_id
from ui.common import asset_label


def _text(value):
    """Keep imported names literal inside Markdown labels."""
    return re.sub(r"([\\`*_{}\[\]()<>#+.!|~-])", r"\\\1", str(value)).replace("\n", " ")


def render_tree(graph, asset, direction, depth=5, limit=150, key="tree", default_expansion=1):
    if asset not in graph.nodes:
        return
    # Scope tree styling to our container; source evidence expanders stay native.
    st.html("""<style>
    [class*="st-key-lineage_branches_"] {padding-left: 1.25rem;}
    [class*="st-key-lineage_branches_"] details {
        border: 0; background: transparent; border-radius: 0;
    }
    [class*="st-key-lineage_branches_"] summary {
        padding: .25rem 0; background: transparent; border: 0;
    }
    [class*="st-key-lineage_branches_"] summary p {font-size: 1rem;}
    [class*="st-key-lineage_branches_"] [data-testid="stExpanderDetails"] {
        margin-left: .75rem; padding: .25rem 0 .25rem 1.25rem;
        border-left: 1px solid color-mix(in srgb, currentColor 20%, transparent);
    }
    [class*="st-key-lineage_branches_"] [data-testid="stVerticalBlock"] {gap: .25rem;}
    [class*="st-key-lineage_branches_"] em {opacity: .75;}
    </style>""")
    st.markdown(f"**{direction.title()} lineage:** {_text(asset_label(graph.nodes[asset]))}")
    with st.container(horizontal=True, vertical_alignment="bottom"):
        if st.button("Expand all", key=key + "_expand", icon=":material/unfold_more:"):
            st.session_state[key + "_generation"] = st.session_state.get(key + "_generation", 0) + 1
            st.session_state[key + "_initial"] = depth
        if st.button("Collapse all", key=key + "_collapse", icon=":material/unfold_less:"):
            st.session_state[key + "_generation"] = st.session_state.get(key + "_generation", 0) + 1
            st.session_state[key + "_initial"] = 0
        details = st.toggle("Show relationship details", key=key + "_details")
    st.caption(f"Up to {depth} levels / {limit} entries. Levels measure distance from the selected table, not execution order.")
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
                st.caption(f"Cycle returns to {_text(asset_label(attrs))}; branch stops here.")
                continue
            edge = graph.graph[neighbor][node] if direction == "upstream" else graph.graph[node][neighbor]
            count = graph.graph.in_degree(neighbor) if direction == "upstream" else graph.graph.out_degree(neighbor)
            evidence = edge["evidence"]
            files = sorted({e.get("relative_path") or "unknown" for e in evidence})
            label = f"**{_text(asset_label(attrs))}**"
            if files:
                label += "  *via " + _text(", ".join(files)) + "*"
            label += f"  · level {level + 1}"
            if not count:
                st.markdown(":material/table: " + label)
                if details:
                    relationship_details(attrs, count, evidence)
                continue
            container = st.expander(label, expanded=level < initial, on_change="rerun",
                                    key=f"{key}_{generation}_{stable_id(*trail, neighbor)}")
            if not container.open:
                continue
            with container:
                if details:
                    relationship_details(attrs, count, evidence)
                if count and level + 1 < depth:
                    branch(neighbor, (*trail, neighbor), level + 1)
                elif count:
                    st.caption("Traversal depth reached. Increase depth to continue.")

    st.markdown(":material/table: **" + _text(asset_label(graph.nodes[asset])) + "**")
    with st.container(gap="xsmall", key="lineage_branches_" + stable_id(key)):
        branch(asset, (asset,), 0)
    if clipped[0]:
        st.info(f"Tree limited to {limit} visible entries. Collapse branches or select a closer asset.")
    elif remaining[0] == limit:
        st.caption("No dependencies in this direction.")


def relationship_details(attrs, count, evidence):
    st.caption(f"{_text(attrs.get('kind', 'asset'))} · {count} dependencies · {len(evidence)} evidence records")
    st.caption(", ".join(dict.fromkeys(
        _text(e.get("kind", "Reference")) + " [" + _text(e.get("status", "unknown")) + "]"
        for e in evidence)))
    confidence = min((e.get("confidence", 1) for e in evidence), default=1)
    st.caption(f"Minimum evidence confidence: {confidence:.0%}")
