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
from dataforge.settings_service import save_ui_settings
from ui.common import allowed_roots, open_storage_home, storage_homes


def render_parsing(store, w):
    if notice := st.session_state.pop("parsing_notice_" + w, None):
        st.success(notice)
    with st.form("parsing_settings_" + w):
        st.subheader("Parsing defaults")
        dialects = [""] + sorted(k for k in sqlglot.Dialect.classes if k)
        dialect = st.selectbox("Default SQL dialect", dialects, index=dialects.index(store.setting(w, "dialect", "")), format_func=lambda x: x or "Generic SQL")
        case = st.checkbox("Case-sensitive asset identities", value=store.setting(w, "case_sensitive", False))
        expand = st.checkbox("Expand plain SQL wildcards using consistent declared schemas", value=store.setting(w, "expand_wildcards", True))
        csv_sample_rows = st.number_input("CSV sample rows", 0, 100, int(store.setting(w, "csv_sample_rows", 25)),
            help="Retained preview rows and sampled type inference. Zero disables sampling; complete original files and row counting remain available.")
        with st.expander("Advanced mappings & job identities"):
            mappings = st.text_area("SAS library mappings (JSON)", json.dumps(store.setting(w, "library_mappings", {}), indent=2), help='Example: {"src": "catalog.raw"}')
            macros = st.text_area("Static SAS macro values (JSON)", json.dumps(store.setting(w, "macros", {}), indent=2))
            folders = st.text_area("SQL dialect by folder prefix (JSON)", json.dumps(store.setting(w, "dialect_by_folder", {}), indent=2))
            extension_dialects = st.text_area("SQL dialect by extension (JSON)", json.dumps(store.setting(w, "dialect_by_extension", {}), indent=2), help="Use .sql or .sas keys. SAS overrides apply to PROC SQL only. Folder overrides take precedence.")
            default_job = st.text_input("Default job/session ID", store.setting(w, "default_job", "workspace"), max_chars=64)
            job_folders = st.text_area("Job/session by folder prefix (JSON)", json.dumps(store.setting(w, "job_by_folder", {}), indent=2),
                help='Example: {"jobs/one/":"one", "jobs/two/":"two"}. Only genuine temporary assets are separated; persistent tables remain shared. This does not infer runtime order.')
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
                data = {"dialect": dialect, "case_sensitive": case, "expand_wildcards": expand, "default_job": default_job,
                        "csv_sample_rows": csv_sample_rows}
                for key, value in [("library_mappings", mappings), ("macros", macros), ("dialect_by_folder", folders), ("dialect_by_extension", extension_dialects), ("job_by_folder", job_folders)]:
                    obj = json.loads(value)
                    if not isinstance(obj, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in obj.items()):
                        raise ValueError("Mappings must be JSON objects with string keys and values")
                    if key == "dialect_by_folder" and any(v not in dialects for v in obj.values()):
                        raise ValueError("Unknown SQL dialect in folder mappings")
                    data[key] = obj
                data = ParsingSettings.model_validate(data).model_dump()
                data.update(AnalysisPreferences(min_lineage_confidence=confidence, include_inferred=inferred,
                    diagnostic_visibility=diagnostic_mode, reanalysis_mode=reanalysis_mode).model_dump())
                with store.lock:
                    save_ui_settings(store, w, 'parsing', {k: v for k, v in data.items() if k in ParsingSettings.model_fields})
                    save_ui_settings(store, w, 'analysis', {k: v for k, v in data.items() if k in AnalysisPreferences.model_fields})
                st.session_state["parsing_notice_" + w] = "Parsing settings saved. Analyze files to apply changes."
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


def render_resources(store, w):
    with st.form("performance_" + w):
        max_file = st.number_input("Maximum file size (MB)", 1, 100, int(store.setting(w, "max_file_mb", 20)))
        max_files = st.number_input("Maximum files per import", 1, 100000, int(store.setting(w, "max_files", 10000)))
        workers = st.number_input("Parsing workers", 1, 8, int(store.setting(w, "parse_workers", 1)))
        llm_workers = st.number_input("Maximum concurrent AI requests per workspace", 1, 4, int(store.setting(w, "llm_concurrency", 1)))
        chunk_chars = st.number_input("AI context chunk size (characters)", 500, 100000, int(store.setting(w, "llm_chunk_chars", 4000)), step=500,
            help="Manual assistance only. Project AI analysis preserves complete units and calculates its full request budget automatically.")
        if st.form_submit_button("Save resource limits"):
            save_ui_settings(store, w, 'resources', {'max_file_mb': max_file, 'max_files': max_files,
                'parse_workers': workers, 'llm_concurrency': llm_workers, 'llm_chunk_chars': chunk_chars})
            st.session_state["settings_notice_" + w] = "Resource limits saved"
            st.rerun()
    st.caption("Imports also enforce 100 MB compressed / 200 MB total and a 200:1 ZIP expansion ratio. Analysis reuses content hashes on every refresh.")
    st.caption("AI requests are also capped at eight across this app process. Busy requests are refused immediately. Manual assistance previews chunks offline; each selected chunk needs an explicit request. Project AI builds calculate complete-unit budgets automatically. Provider budgets still apply.")
    st.caption('Clear the shared parser cache with a preview and confirmation in Data management → Cleanup & recovery.')


def render_appearance(store, w):
    from ui.themes import render_theme_picker
    render_theme_picker()
    st.subheader("Graph and source defaults")
    st.caption("Save a starting view; you can still adjust it during an investigation.")
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
            save_ui_settings(store, w, 'visualization', {**values, "graph_limit": limit,
                "traversal_depth": depth, "tree_expansion_depth": tree_depth})
            for key in ("graph_direction_" + w, "graph_collapse_" + w, "lineage_source_complete_" + w):
                st.session_state.pop(key, None)
            st.session_state["settings_notice_" + w] = "Visualization settings saved"
            st.rerun()
    st.caption("Defaults apply when opening Lineage. Graph appearance is included in offline HTML/JSON and safe workspace configuration transfers. Choose a light or dark theme preset above.")


def render_privacy(store, w):
    from dataforge.logging_config import save_application_logging
    with st.form("application_logging"):
        levels = ["DEBUG", "INFO", "WARNING", "ERROR"]
        log_level = st.selectbox("Application log level", levels,
            index=levels.index(store.setting("__application__", "log_level", "INFO")))
        st.caption("Applies across workspaces in this data home and survives restart. Source content and credentials remain excluded from structured event fields; full AI interaction storage is controlled separately below.")
        if st.form_submit_button("Save logging level"):
            save_application_logging(store, log_level)
            st.session_state["settings_notice_" + w] = "Application logging level saved"
            st.rerun()
    st.caption("Host directory access is restricted to these configured roots:")
    st.code("\n".join(str(p) for p in allowed_roots()), language=None)
    st.caption("Configure DATAFORGE_ALLOWED_ROOTS before startup; use the operating system path separator between roots.")
    with st.form("privacy_" + w):
        external = st.checkbox("Enable external LLM requests", value=store.setting(w, "external_llm", False))
        full = st.checkbox("Allow complete source files in LLM context", value=store.setting(w, "allow_full_source", False))
        max_context = st.number_input("Maximum source context characters", 500, 100000, int(store.setting(w, "max_context_chars", 8000)), step=500)
        redact = st.checkbox("Redact likely secrets", value=store.setting(w, "redact_secrets", True))
        history = st.checkbox("Store full AI interaction context locally", value=store.setting(w, "llm_history", False))
        retention = st.number_input("AI record retention days", 1, 3650, int(store.setting(w, "llm_retention_days", 30)))
        if st.form_submit_button("Save privacy settings"):
            save_ui_settings(store, w, 'privacy', {'external_llm': external, 'allow_full_source': full,
                'max_context_chars': max_context, 'redact_secrets': redact, 'llm_history': history,
                'llm_retention_days': retention})
            st.session_state["settings_notice_" + w] = "Privacy settings saved"
            st.rerun()


def render_storage(store, w):
    st.code(str(store.home), language=None)
    size = (store.home / "dataforge.duckdb").stat().st_size
    st.metric("Database size", f"{size / 1024 / 1024:.2f} MB")
    homes = storage_homes()
    selected_home = st.selectbox("Storage location", homes, index=homes.index(str(store.home)))
    st.button("Open storage location", disabled=selected_home == str(store.home),
              on_click=open_storage_home, args=(selected_home,))
    if error := st.session_state.pop("storage_error", None):
        st.error(error)
    st.caption("Startup allowlist: DATAFORGE_HOME plus DATAFORGE_STORAGE_LOCATIONS (absolute directories separated by the OS path separator, maximum eight). Opening a location changes this browser session; workspaces and source files stay in their existing directories.")
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
    st.caption("Transfers parsing, resource and graph settings. Excludes provider profiles, credentials, privacy permissions, source files and analysis history. Use Lineage source bundles to transfer source files.")
    config_file = st.file_uploader("Import workspace configuration", type=["json"])
    if config_file and st.button("Create workspace from configuration"):
        try:
            import_workspace_configuration(store, config_file.getvalue())
            st.success("Workspace created. Select it in the sidebar.")
        except (ValueError, KeyError, TypeError) as exc:
            st.error(f"Configuration import failed: {exc}")
