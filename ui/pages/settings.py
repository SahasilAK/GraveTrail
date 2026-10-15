import json

import sqlglot
import streamlit as st

from dataforge.configuration import (
    AnalysisPreferences,
    ParsingSettings,
    VisualizationSettings,
    export_workspace_configuration,
    import_workspace_configuration,
)
from ui.common import allowed_roots, context, title

title("Settings", "Configure analysis, storage, resource budgets and source-code privacy.")
store, w = context()
if notice := st.session_state.pop("settings_notice_" + w, None):
    st.success(notice)
tab = st.segmented_control("Settings section", ["Parsing and lineage", "Storage and workspaces", "Performance", "Visualization", "Security and privacy", "LLM providers"], default="Parsing and lineage")
if tab == "Parsing and lineage":
    if notice := st.session_state.pop("parsing_notice_" + w, None):
        st.success(notice)
    with st.form("parsing_settings"):
        dialects = [""] + sorted(k for k in sqlglot.Dialect.classes if k)
        dialect = st.selectbox("Default SQL dialect", dialects, index=dialects.index(store.setting(w, "dialect", "")), format_func=lambda x: x or "Generic SQL")
        case = st.checkbox("Case-sensitive asset identities", value=store.setting(w, "case_sensitive", False))
        expand = st.checkbox("Expand plain SQL wildcards using consistent declared schemas", value=store.setting(w, "expand_wildcards", True))
        mappings = st.text_area("SAS library mappings (JSON)", json.dumps(store.setting(w, "library_mappings", {}), indent=2), help='Example: {"src": "catalog.raw"}')
        macros = st.text_area("Static SAS macro values (JSON)", json.dumps(store.setting(w, "macros", {}), indent=2))
        folders = st.text_area("SQL dialect by folder prefix (JSON)", json.dumps(store.setting(w, "dialect_by_folder", {}), indent=2))
        extension_dialects = st.text_area("SQL dialect by extension (JSON)", json.dumps(store.setting(w, "dialect_by_extension", {}), indent=2), help="Use .sql or .sas keys. SAS overrides apply to PROC SQL only. Folder overrides take precedence.")
        confidence = st.slider("Minimum lineage confidence in graph views", 0., 1., float(store.setting(w, "min_lineage_confidence", 0.)), step=.05)
        inferred = st.checkbox("Include inferred relationships in graph views", store.setting(w, "include_inferred", True))
        diagnostic_modes = ["all", "warnings_errors", "errors"]
        diagnostic_mode = st.selectbox("Visible parsing diagnostics", diagnostic_modes,
            index=diagnostic_modes.index(store.setting(w, "diagnostic_visibility", "all")))
        reanalysis_modes = ["changed", "all"]
        reanalysis_mode = st.selectbox("Analyze button mode", reanalysis_modes,
            index=reanalysis_modes.index(store.setting(w, "reanalysis_mode", "changed")),
            format_func=lambda x: "Reuse unchanged parser results" if x == "changed" else "Reparse selected/all files")
        st.caption("Filters affect displayed graphs and their exports; stored evidence and diagnostics are retained. Inferred relationships never become verified through a threshold.")
        if st.form_submit_button("Save parsing settings"):
            try:
                data = {"dialect": dialect, "case_sensitive": case, "expand_wildcards": expand}
                for key, value in [("library_mappings", mappings), ("macros", macros), ("dialect_by_folder", folders), ("dialect_by_extension", extension_dialects)]:
                    obj = json.loads(value)
                    if not isinstance(obj, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in obj.items()):
                        raise ValueError("Mappings must be JSON objects with string keys and values")
                    if key == "dialect_by_folder" and any(v not in dialects for v in obj.values()):
                        raise ValueError("Unknown SQL dialect in folder mappings")
                    data[key] = obj
                data = ParsingSettings.model_validate(data).model_dump()
                data.update(AnalysisPreferences(min_lineage_confidence=confidence, include_inferred=inferred,
                    diagnostic_visibility=diagnostic_mode, reanalysis_mode=reanalysis_mode).model_dump())
                with store.transaction():
                    for key, value in data.items():
                        store.set_setting(w, key, value)
                st.session_state["parsing_notice_" + w] = "Parsing settings saved. Analyze files to apply changes."
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
elif tab == "Storage and workspaces":
    st.code(str(store.home), language=None)
    size = (store.home / "dataforge.duckdb").stat().st_size
    st.metric("Database size", f"{size / 1024 / 1024:.2f} MB")
    st.caption("Set DATAFORGE_HOME before startup to select a different storage directory. Each home has an independent database.")
    workspace = next(a for a in store.workspaces() if a["workspace_id"] == w)
    if notice := st.session_state.pop("workspace_notice", None):
        st.success(notice)
    with st.form("workspace_details_" + w):
        name = st.text_input("Active workspace name", workspace["name"], max_chars=200)
        description = st.text_area("Workspace description", workspace["description"], max_chars=2000)
        if st.form_submit_button("Save workspace details"):
            try:
                store.update_workspace(w, name, description)
                st.session_state["workspace_notice"] = "Workspace details saved"
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    st.download_button("Export workspace configuration", export_workspace_configuration(store, w), "workspace.json", "application/json")
    st.caption("Transfers parsing, resource and graph settings. Excludes provider profiles, credentials, privacy permissions, source files and analysis history. Use Builder/source bundles to transfer source files.")
    config_file = st.file_uploader("Import workspace configuration", type=["json"])
    if config_file and st.button("Create workspace from configuration"):
        try:
            import_workspace_configuration(store, config_file.getvalue())
            st.success("Workspace created. Select it in the sidebar.")
        except (ValueError, KeyError, TypeError) as exc:
            st.error(f"Configuration import failed: {exc}")
    st.subheader("Ingestion history")
    st.dataframe(store.rows("SELECT created_at,source,report FROM ingestion_runs WHERE workspace_id=? ORDER BY created_at DESC", [w]), hide_index=True)
    from ui.workspace_history import render as render_history
    render_history(store, w)
    from ui.temporary_cleanup import render as render_temporary_cleanup
    render_temporary_cleanup(store, w)
    with st.expander("Delete active workspace"):
        confirmation = st.text_input("Type the active workspace name to delete its inventory and analysis")
        if st.button("Delete workspace", disabled=confirmation != workspace["name"]):
            store.delete_workspace(w)
            st.session_state.pop("workspace", None)
            st.rerun()
elif tab == "Performance":
    with st.form("performance"):
        max_file = st.number_input("Maximum file size (MB)", 1, 100, int(store.setting(w, "max_file_mb", 20)))
        max_files = st.number_input("Maximum files per import", 1, 100000, int(store.setting(w, "max_files", 10000)))
        workers = st.number_input("Parsing workers", 1, 8, int(store.setting(w, "parse_workers", 1)))
        llm_workers = st.number_input("Maximum concurrent AI requests per workspace", 1, 4, int(store.setting(w, "llm_concurrency", 1)))
        chunk_chars = st.number_input("AI context chunk size (characters)", 500, 100000, int(store.setting(w, "llm_chunk_chars", 4000)), step=500)
        if st.form_submit_button("Save resource limits"):
            store.set_setting(w, "max_file_mb", max_file)
            store.set_setting(w, "max_files", max_files)
            store.set_setting(w, "parse_workers", workers)
            store.set_setting(w, "llm_concurrency", llm_workers)
            store.set_setting(w, "llm_chunk_chars", chunk_chars)
            st.session_state["settings_notice_" + w] = "Resource limits saved"
            st.rerun()
    st.caption("Imports also enforce 100 MB compressed / 200 MB total and a 200:1 ZIP expansion ratio. Analysis reuses content hashes on every refresh.")
    st.caption("AI requests are also capped at eight across this app process. Busy requests are refused immediately. Chunking is an offline preview; each selected chunk requires its own explicit request. Provider budgets still apply.")
    if st.button("Clear parser cache"):
        store.execute("DELETE FROM parse_cache")
        st.success("Parser cache cleared; stored lineage and source inventory retained")
elif tab == "Visualization":
    from ui.themes import render_theme_picker
    render_theme_picker()
    st.subheader("Graph and source defaults")
    appearance = VisualizationSettings.from_store(store, w)
    with st.form("visualization_" + w):
        limit = st.number_input("Maximum graph nodes", 10, 1000, int(store.setting(w, "graph_limit", 150)))
        depth = st.slider("Default traversal depth", 1, 30, int(store.setting(w, "traversal_depth", 5)))
        tree_depth = st.slider("Default tree expansion depth", 0, 30, int(store.setting(w, "tree_expansion_depth", 1)))
        directions = ["upstream", "downstream", "combined"]
        direction = st.selectbox("Default graph direction", directions, index=directions.index(appearance.graph_direction))
        collapse = st.checkbox("Collapse temporary steps by default", appearance.collapse_temporary)
        labels = ["compact", "full", "hidden"]
        label = st.selectbox("Graph labels", labels, index=labels.index(appearance.graph_labels),
                             help="Full names fit inside wider nodes. Tooltips and evidence always retain exact names.")
        palettes = ["semantic", "neutral"]
        palette = st.selectbox("Node palette", palettes, index=palettes.index(appearance.graph_palette),
                               help="Semantic colors distinguish sources, temporary and unresolved assets. Neutral uses one fill.")
        edge_width = st.slider("Edge width", 1, 5, appearance.graph_edge_width)
        source_modes = ["complete", "relevant"]
        source_mode = st.selectbox("Default source view", source_modes, index=source_modes.index(appearance.source_view_mode),
                                   format_func=lambda x: "Complete source expanded" if x == "complete" else "Relevant statements first")
        line_numbers = st.checkbox("Show source line numbers", appearance.source_line_numbers)
        if st.form_submit_button("Save visualization settings"):
            values = VisualizationSettings(graph_direction=direction, collapse_temporary=collapse,
                graph_labels=label, graph_palette=palette, graph_edge_width=edge_width,
                source_view_mode=source_mode, source_line_numbers=line_numbers).model_dump()
            with store.transaction():
                for key, value in {**values, "graph_limit": limit, "traversal_depth": depth,
                                    "tree_expansion_depth": tree_depth}.items():
                    store.set_setting(w, key, value)
            for key in ("graph_direction_" + w, "graph_collapse_" + w, "lineage_source_complete_" + w):
                st.session_state.pop(key, None)
            st.session_state["settings_notice_" + w] = "Visualization settings saved"
            st.rerun()
    st.caption("Defaults apply when opening Explorer. Graph appearance is included in offline HTML/JSON and safe workspace configuration transfers. Switch light/dark appearance from the application menu.")
elif tab == "Security and privacy":
    from dataforge.logging_config import configure_logging
    with st.form("application_logging"):
        levels = ["DEBUG", "INFO", "WARNING", "ERROR"]
        log_level = st.selectbox("Application log level", levels,
            index=levels.index(store.setting("__application__", "log_level", "INFO")))
        st.caption("Applies across workspaces in this data home and survives restart. Source content and credentials remain excluded from structured event fields; full AI interaction storage is controlled separately below.")
        if st.form_submit_button("Save logging level"):
            configure_logging(log_level)
            store.set_setting("__application__", "log_level", log_level)
            st.session_state["settings_notice_" + w] = "Application logging level saved"
            st.rerun()
    st.caption("Host directory access is restricted to these configured roots:")
    st.code("\n".join(str(p) for p in allowed_roots()), language=None)
    st.caption("Configure DATAFORGE_ALLOWED_ROOTS before startup; use the operating system path separator between roots.")
    with st.form("privacy"):
        external = st.checkbox("Enable external LLM requests", value=store.setting(w, "external_llm", False))
        full = st.checkbox("Allow complete source files in LLM context", value=store.setting(w, "allow_full_source", False))
        max_context = st.number_input("Maximum source context characters", 500, 100000, int(store.setting(w, "max_context_chars", 8000)), step=500)
        redact = st.checkbox("Redact likely secrets", value=store.setting(w, "redact_secrets", True))
        history = st.checkbox("Store full AI interaction context locally", value=store.setting(w, "llm_history", False))
        retention = st.number_input("AI record retention days", 1, 3650, int(store.setting(w, "llm_retention_days", 30)))
        if st.form_submit_button("Save privacy settings"):
            for k, v in [("external_llm", external), ("allow_full_source", full), ("max_context_chars", max_context),
                         ("redact_secrets", redact), ("llm_history", history), ("llm_retention_days", retention)]:
                store.set_setting(w, k, v)
            st.session_state["settings_notice_" + w] = "Privacy settings saved"
            st.rerun()
else:
    from ui.provider_settings import render
    render(store, w)
