from __future__ import annotations

import json
import os
from pathlib import Path

import duckdb
import streamlit as st

from dataforge.asset_identity import asset_label
from dataforge.configuration import AnalysisPreferences, VisualizationSettings
from dataforge.exports import GRAPH_BODY, GRAPH_CSS, GRAPH_JS, graph_data, report_csv, report_html
from dataforge.graph import LineageGraph
from dataforge.storage_locations import allowed_homes, validate_home
from dataforge.store import Store

ROOT = Path(__file__).resolve().parents[1]


@st.cache_resource
def get_store(home: str) -> Store:
    return Store(home)


def context():
    return get_store(current_home()), st.session_state["workspace"]


def storage_homes():
    return allowed_homes(os.environ.get("DATAFORGE_HOME", str(ROOT / ".dataforge")),
                         os.environ.get("DATAFORGE_STORAGE_LOCATIONS", ""))


def current_home():
    homes = storage_homes()
    selected = st.session_state.get("dataforge_home", homes[0])
    if selected not in homes:
        st.session_state.clear()
        st.session_state["storage_notice"] = "Previous storage location is no longer allowed. Opened the default location."
        selected = homes[0]
    return validate_home(selected, homes)


def open_storage_home(selected):
    """Widget callback: validate/open first, then clear this session's old workspace controls."""
    try:
        home = validate_home(selected, storage_homes())
        get_store(home)
    except (ValueError, OSError, duckdb.Error):
        st.session_state["storage_error"] = "Cannot open this storage location. Check directory access and whether another process owns its database."
        return
    st.session_state.clear()
    st.session_state["dataforge_home"] = home
    st.session_state["storage_notice"] = "Storage location opened. Each location keeps its own workspaces and source files."


def allowed_roots():
    return [Path(p).resolve() for p in os.environ.get("DATAFORGE_ALLOWED_ROOTS", str(ROOT / "tests" / "fixtures")).split(os.pathsep) if p]


def title(name: str, description: str):
    st.title(name)
    st.caption(description)


def load_graph(store, workspace):
    latest = store.rows("SELECT run_id FROM analysis_runs WHERE workspace_id=? AND status='completed' ORDER BY created_at DESC LIMIT 1", [workspace])
    preferences = AnalysisPreferences.model_validate({k: store.setting(workspace, k, v)
        for k, v in AnalysisPreferences().model_dump().items()})
    if preferences.min_lineage_confidence > 0 or not preferences.include_inferred:
        st.caption(f"Lineage view filters: minimum confidence {preferences.min_lineage_confidence:.2f}; inferred relationships {'included' if preferences.include_inferred else 'hidden'}. Graph exports use these filters. Stored facts remain intact.")
    graph = _cached_graph(str(store.home), workspace, latest[0]["run_id"] if latest else "empty",
                          preferences.min_lineage_confidence, preferences.include_inferred)
    if graph.unresolved_edges:
        st.warning(f"{len(graph.unresolved_edges)} relationships reference missing assets and cannot be displayed. "
                   "Lineage is incomplete. Rebuild lineage in Lineage builder to regenerate asset metadata.")
    return graph


@st.cache_resource(max_entries=32, ttl=300)
def _cached_graph(home, workspace, revision, min_confidence=0., include_inferred=True):
    store = get_store(home)
    with store.lock:
        assets, edges = store.assets(workspace), store.edges(workspace)
        return LineageGraph(assets, edges, min_confidence, include_inferred)


def choose_asset(graph, key):
    query = st.text_input("Search tables, datasets or file assets", placeholder="e.g. orders or mart.customer_summary", key=f"asset_search_{key}")
    matches = graph.search(query)[:500]
    if not matches:
        st.info("No matching assets. Analyze source files in Lineage builder first.")
        return None
    if len(matches) > 1:
        st.caption(f"{len(matches)} matches. Choose the exact asset to avoid ambiguous names.")
    mapping = {a["asset_id"]: a for a in matches}
    # Identical labels across workspaces must not reuse the browser's old option index.
    choice_key = f"asset_choice_{key}_{st.session_state.get('workspace', '')}"
    if st.session_state.get(choice_key) not in mapping:
        st.session_state.pop(choice_key, None)
    return st.selectbox("Choose an exact asset", list(mapping), index=None,
        format_func=lambda k: f'{asset_label(mapping[k])}  [{mapping[k]["kind"]}{", temporary" if mapping[k]["temporary"] else ""}]',
        key=choice_key)


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
    ids = list(dict.fromkeys(file_ids))
    choices = {r["file_id"]: r["relative_path"] for r in store.rows(
        "SELECT file_id,relative_path FROM source_files WHERE file_id IN (" + ",".join("?" for _ in ids) + ") ORDER BY relative_path", ids)}
    if st.session_state.get(key + "_file") not in choices:
        st.session_state.pop(key + "_file", None)
    fid = st.selectbox("Source file", list(choices), format_func=choices.get, key=key + "_file")
    relevant = [e for e in evidence or [] if e.get("file_id") == fid]
    source_hash = relevant[0].get("source_hash") if relevant else None
    source = store.file(fid, source_hash)
    appearance = VisualizationSettings.from_store(store, source["workspace_id"])
    st.caption(f'{source["relative_path"]} | {source["encoding"]} | {source["line_count"]} lines | {source["file_size"]:,} bytes')
    st.download_button("Download original file", store.original(fid, source_hash), source["file_name"], key=key + "_download")
    if source_hash and source_hash != store.file(fid)["content_hash"]:
        st.warning("Showing the original analyzed version. A newer file is pending analysis in the inventory.")
    text = source["raw_content"]
    needle = st.text_input("Find in source", key=key + "_find")
    if needle:
        lines = [str(i) for i, line in enumerate(text.splitlines(), 1) if needle.casefold() in line.casefold()]
        st.caption("Matching lines: " + (", ".join(lines[:100]) if lines else "none"))
    language = "sql" if source["extension"] == ".sql" else "sas" if source["extension"] == ".sas" else "text"
    if relevant:
        st.markdown("**Relevant statements**")
        for e in {e["statement_id"]: e for e in relevant}.values():
            with st.expander(f'Lines {e["start_line"]}–{e["end_line"]}: {e.get("kind", e.get("operation_type", "Reference"))}', expanded=True):
                st.code(e["code"], language=language, line_numbers=appearance.source_line_numbers)
    complete = st.expander("Complete source", expanded=appearance.source_view_mode == "complete" or not relevant,
                           on_change="rerun", key=key + "_complete_" + source["workspace_id"])
    if complete.open:
        with complete:
            st.code(text, language=language, line_numbers=appearance.source_line_numbers, height=500)
    st.caption("Use the code block copy button to copy code. Line ranges above refer to the original file.")


_GRAPH = st.components.v2.component("dataforge_graph", html=GRAPH_BODY, css=GRAPH_CSS,
    js=GRAPH_JS + "\nexport default function(c){mountGraph(c.parentElement,c.data,v=>c.setStateValue('selection',v));}\n")


def graph_view(graph, key="graph", appearance=None):
    return _GRAPH(data=graph_data(graph, appearance), key=key, default={"selection": None},
                  on_selection_change=lambda: None, height="content")
