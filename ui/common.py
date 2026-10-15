from __future__ import annotations

import json
import os
from pathlib import Path

import streamlit as st

from dataforge.exports import GRAPH_BODY, GRAPH_CSS, GRAPH_JS, graph_data, report_csv, report_html
from dataforge.graph import LineageGraph
from dataforge.store import Store

ROOT = Path(__file__).resolve().parents[1]


@st.cache_resource
def get_store(home: str) -> Store:
    return Store(home)


def context():
    return get_store(os.environ.get("DATAFORGE_HOME", str(ROOT / ".dataforge"))), st.session_state["workspace"]


def allowed_roots():
    return [Path(p).resolve() for p in os.environ.get("DATAFORGE_ALLOWED_ROOTS", str(ROOT / "tests" / "fixtures")).split(os.pathsep) if p]


def title(name: str, description: str):
    st.title(name)
    st.caption(description)


def load_graph(store, workspace):
    # Parsing is cached in DuckDB; graph construction touches metadata and evidence only.
    return LineageGraph(store.assets(workspace), store.edges(workspace))


def choose_asset(graph, key):
    query = st.text_input("Search tables, datasets or file assets", placeholder="e.g. orders or mart.customer_summary", key=f"asset_search_{key}")
    matches = graph.search(query)[:500]
    if not matches:
        st.info("No matching assets. Analyze source files in Lineage builder first.")
        return None
    if len(matches) > 1:
        st.caption(f"{len(matches)} matches. Choose the exact asset to avoid ambiguous names.")
    mapping = {a["asset_id"]: a for a in matches}
    return st.selectbox("Choose an exact asset", list(mapping), index=None,
        format_func=lambda k: f'{mapping[k]["name"]}  [{mapping[k]["kind"]}{", temporary" if mapping[k]["temporary"] else ""}]',
        key=f"asset_choice_{key}")


def downloads(rows, stem, include_html=True):
    with st.container(horizontal=True):
        st.download_button("Download CSV", report_csv(rows), stem + ".csv", "text/csv", key=stem + "_csv")
        st.download_button("Download JSON", json.dumps(rows, default=str, indent=2), stem + ".json", "application/json", key=stem + "_json")
        if include_html:
            st.download_button("Download HTML report", report_html(rows), stem + ".html", "text/html", key=stem + "_html")


def source_viewer(store, file_ids, key="source", evidence=None):
    if not file_ids:
        st.info("No source evidence in this selection.")
        return
    choices = {fid: store.file(fid)["relative_path"] for fid in dict.fromkeys(file_ids)}
    fid = st.selectbox("Source file", list(choices), format_func=choices.get, key=key + "_file")
    source = store.file(fid)
    st.caption(f'{source["relative_path"]} | {source["encoding"]} | {source["line_count"]} lines | {source["file_size"]:,} bytes')
    st.download_button("Download original file", store.original(fid), source["file_name"], key=key + "_download")
    text = source["raw_content"]
    needle = st.text_input("Find in source", key=key + "_find")
    if needle:
        lines = [str(i) for i, line in enumerate(text.splitlines(), 1) if needle.casefold() in line.casefold()]
        st.caption("Matching lines: " + (", ".join(lines[:100]) if lines else "none"))
    relevant = [e for e in evidence or [] if e.get("file_id") == fid]
    language = "sql" if source["extension"] == ".sql" else "sas" if source["extension"] == ".sas" else "text"
    if relevant:
        st.markdown("**Relevant statements**")
        for e in {e["statement_id"]: e for e in relevant}.values():
            with st.expander(f'Lines {e["start_line"]}–{e["end_line"]}: {e.get("kind", e.get("operation_type", "Reference"))}', expanded=True):
                st.code(e["code"], language=language, line_numbers=True)
    st.markdown("**Complete source**")
    st.code(text, language=language, line_numbers=True, height=500)
    st.caption("Use the code block copy button to copy code. Line ranges above refer to the original file.")


_GRAPH = st.components.v2.component("dataforge_graph", html=GRAPH_BODY, css=GRAPH_CSS,
    js=GRAPH_JS + "\nexport default function(c){mountGraph(c.parentElement,c.data,v=>c.setStateValue('selection',v));}\n")


def graph_view(graph, key="graph"):
    return _GRAPH(data=graph_data(graph), key=key, default={"selection": None},
                  on_selection_change=lambda: None, height="content")
