from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path

import duckdb
import streamlit as st

from dataforge.asset_identity import asset_label
from dataforge.configuration import AnalysisPreferences, VisualizationSettings
from dataforge.exports import GRAPH_BODY, GRAPH_CSS, GRAPH_JS, graph_data, report_csv, report_html
from dataforge.graph import LineageGraph
from dataforge.storage_locations import allowed_homes, validate_home
from dataforge.store import Store
from ui.lineage_navigation import ALL_ASSETS

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
    with st.container(key="page_heading"):
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
                   "Lineage is incomplete. Rebuild lineage in Analysis to regenerate asset metadata.")
    return graph


@st.cache_resource(max_entries=32, ttl=300)
def _cached_graph(home, workspace, revision, min_confidence=0., include_inferred=True):
    store = get_store(home)
    with store.lock:
        assets, edges = store.assets(workspace), store.edges(workspace)
        return LineageGraph(assets, edges, min_confidence, include_inferred)


def choose_asset(graph, key, allow_all=False):
    with st.container(horizontal=True, vertical_alignment="bottom"):
        with st.container(width=360, key="asset_query_" + key):
            query = st.text_input("Search tables, datasets or file assets", placeholder="e.g. orders or mart.customer_summary", key=f"asset_search_{key}", persist_state="session")
        matches = graph.search(query)[:500]
        if not matches and not allow_all:
            st.info("No matching assets. Import sources, then run Analysis to establish dependencies.")
            return None
        mapping = {a["asset_id"]: a for a in matches}
        choice_key = f"asset_choice_{key}_{st.session_state.get('workspace', '')}"
        shared_key = "exploration_asset_" + st.session_state.get("workspace", "")
        selected = st.session_state.get(choice_key) or st.session_state.get(shared_key)
        # Graph navigation may target an exact ID beyond the first 500 search matches.
        if selected in graph.nodes and query.casefold() in graph.nodes[selected]["name"].casefold():
            mapping[selected] = graph.nodes[selected]
        options = list(mapping) + ([ALL_ASSETS] if allow_all else [])
        if st.session_state.get(choice_key) not in options:
            st.session_state.pop(choice_key, None)
            if st.session_state.get(shared_key) in mapping:
                st.session_state[choice_key] = st.session_state[shared_key]

        def remember_asset():
            if st.session_state.get(choice_key) == ALL_ASSETS:
                return
            st.session_state[shared_key] = st.session_state.get(choice_key)
            for sibling in ("lineage", "columns", "impact"):
                sibling_key = f"asset_choice_{sibling}_{st.session_state.get('workspace', '')}"
                if sibling_key != choice_key:
                    st.session_state.pop(sibling_key, None)

        with st.container(width=360, key="asset_select_" + key):
            chosen = st.selectbox("Choose an exact asset", options, index=None,
                format_func=lambda k: "All" if k == ALL_ASSETS else f'{asset_label(mapping[k])}  [{mapping[k]["kind"]}{", temporary" if mapping[k]["temporary"] else ""}]',
                key=choice_key, persist_state="session", on_change=remember_asset)
    if len(matches) > 1:
        st.caption(f"{len(matches)} matches. Choose the exact asset to avoid ambiguous names.")
    return chosen


def downloads(rows, stem, include_html=True):
    with st.popover("Export report", icon=":material/download:"):
        st.download_button("Download CSV", lambda: report_csv(rows), stem + ".csv", "text/csv", key=stem + "_csv", on_click="ignore")
        st.download_button("Download JSON", lambda: json.dumps(rows, default=str, indent=2), stem + ".json", "application/json", key=stem + "_json", on_click="ignore")
        if include_html:
            st.download_button("Download HTML report", lambda: report_html(rows), stem + ".html", "text/html", key=stem + "_html", on_click="ignore")


def source_viewer(store, file_ids, key="source", evidence=None):
    if not file_ids:
        st.info("No source evidence in this selection.")
        return
    ids = list(dict.fromkeys(file_ids))
    choices = {r["file_id"]: r["relative_path"] for r in store.rows(
        "SELECT file_id,relative_path FROM source_files WHERE file_id IN (" + ",".join("?" for _ in ids) + ") ORDER BY relative_path", ids)}
    if not choices:
        st.warning("These source files are no longer available. Refresh the analysis or choose another asset.")
        return
    if st.session_state.get(key + "_file") not in choices:
        st.session_state.pop(key + "_file", None)
    # A new evidence scope must create a new browser control, even at the same option index.
    scope = sha256(json.dumps([ids, [(e.get("file_id"), e.get("source_hash")) for e in evidence or []]]).encode()).hexdigest()[:12]
    selected = st.session_state.get(key + "_file")
    fid = st.selectbox("Source file", list(choices), format_func=choices.get,
                       index=list(choices).index(selected) if selected in choices else 0,
                       key=f"{key}_choice_{st.session_state['workspace']}_{scope}")
    st.session_state[key + "_file"] = fid
    relevant = [e for e in evidence or [] if e.get("file_id") == fid]
    source_hash = relevant[0].get("source_hash") if relevant else None
    source = store.file(fid, source_hash)
    appearance = VisualizationSettings.from_store(store, source["workspace_id"])
    st.caption(f'{source["relative_path"]} · {source["encoding"]} · {source["line_count"]} lines · {source["file_size"]:,} bytes')
    st.download_button("Download original file", lambda: store.original(fid, source_hash), source["file_name"], key=key + "_download", on_click="ignore", icon=":material/download:")
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
    js=GRAPH_JS + "\nexport default function(c){return mountGraph(c.parentElement,c.data,v=>c.setStateValue('selection',v),v=>c.setTriggerValue('navigate',v));}\n")


def graph_view(graph, key="graph", appearance=None, on_navigate=None):
    from ui.themes import _loaded_preset

    return _GRAPH(data=graph_data(graph, appearance, theme=_loaded_preset()), key=key, default={"selection": None},
                  on_selection_change=lambda: None, on_navigate_change=on_navigate or (lambda: None), height="content")
