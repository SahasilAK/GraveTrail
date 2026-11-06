import json
from dataclasses import asdict

import streamlit as st

from dataforge.configuration import ParsingSettings
from dataforge.dbt.service import is_dbt
from dataforge.ingestion import Importer, ImportReport, Limits
from dataforge.services import explicit_source_dialect, set_source_dialect, source_dialect
from ui.common import allowed_roots, context, downloads, source_viewer, title
from ui.presentation import empty_state, section
from ui.workspace_settings import SQL_DIALECTS, dialect_label

SQL_SOURCE_TYPES = {'Use workspace settings': None, **{dialect_label(d): d for d in SQL_DIALECTS}}

title("Sources", "Bring your project into focus. Import source files, then inspect the inventory.")
store, w = context()
files = store.files(w)
mode = section("Source workspace", ["Import", "Inventory"], "sources_section_" + w)
if mode == "Import":
    with st.container(border=True, key="source_import"):
        st.subheader("Add source files", icon=":material/upload_file:")
        st.caption("SQL · SAS · CSV / original files are retained as evidence")
        mode = st.segmented_control("Input source", ["ZIP archive", "Folder upload", "Host directory"], default="ZIP archive")
        project_type = st.selectbox('Project type', ['SQL / SAS / CSV files', 'dbt project'])
        source_kind, dbt_options = ('dbt' if project_type == 'dbt project' else 'files'), None
        sql_dialect = None
        if source_kind == 'dbt':
            dbt_mode = st.selectbox('dbt analysis mode', ['source', 'enriched', 'artifact'])
            artifact_paths = st.text_area('Selected artifact paths (one per line)',
                placeholder='retail/target/manifest.json')
            include_packages = st.checkbox('Include supplied dbt package sources', value=False)
            dbt_options = {'mode': dbt_mode, 'artifact_paths': [p.strip() for p in artifact_paths.splitlines() if p.strip()],
                           'include_packages': include_packages}
            extensions = set()
            st.caption('dbt projects include configured models, YAML schemas, macros, seeds and tests. Profiles, secrets and unselected generated files are excluded.')
        else:
            extensions = {"." + x for x in st.multiselect("File types to analyze", ["sql", "sas", "csv"], default=["sql", "sas", "csv"])}
            if '.sql' in extensions:
                sql_dialect = SQL_SOURCE_TYPES[st.selectbox('SQL source type', SQL_SOURCE_TYPES,
                    help='Applies only to SQL files. Use workspace settings to let folder and extension rules select the dialect.')]
        entries, archive, directory = [], None, ""
        if mode == "ZIP archive":
            archive = st.file_uploader("Choose a ZIP archive", type=["zip"])
        elif mode == "Folder upload":
            entries = st.file_uploader("Choose a source folder", accept_multiple_files="directory")
        else:
            roots = allowed_roots()
            st.caption("Allowed roots: " + "; ".join(str(p) for p in roots))
            directory = st.text_input("Directory on application host", value=str(roots[0] / "scenario") if roots else "")
        st.caption("Source files are analyzed as text and never executed. Unsupported files are skipped and reported.")
        if st.button("Import into inventory", type="primary", disabled=not extensions and source_kind != 'dbt'):
            try:
                limits = Limits(max_file_bytes=int(store.setting(w, "max_file_mb", 20)) * 1024 * 1024,
                                max_files=int(store.setting(w, "max_files", 10000)))
                importer = Importer(store, w, allowed_roots(), limits)
                options = dict(source_kind=source_kind, dbt_options=dbt_options, sql_dialect=sql_dialect)
                status = st.empty()
                def progress(r: ImportReport) -> None:
                    """Show current file discovery and import totals.

                    Args:
                        r: Latest import report snapshot.
                    """
                    status.caption(f"Discovered {r.discovered}; accepted {r.accepted}; skipped {r.skipped}")
                if mode == "ZIP archive" and archive:
                    report = importer.zip(archive.getvalue(), extensions, progress, **options)
                elif mode == "Folder upload" and entries:
                    report = importer.files(((f.name, f.getvalue()) for f in entries), extensions, progress, **options)
                elif mode == "Host directory":
                    report = importer.directory(directory, extensions, progress, **options)
                else:
                    raise ValueError("Choose source files first")
                progress(report)
                st.session_state["import_report_" + w] = asdict(report)
                st.success(f"Imported {report.accepted} files. Open Analysis when you are ready to trace dependencies.")
            except Exception as exc:
                st.error(f"Import failed: {exc}")
        if "import_report_" + w in st.session_state:
            report = st.session_state["import_report_" + w]
            st.caption(f"Last import · {report['accepted']} accepted · {report['skipped']} skipped · {report['discovered']} discovered")
            st.page_link("ui/pages/analysis.py", label="Continue to Analysis", icon=":material/arrow_forward:")
            if report["diagnostics"]:
                with st.expander("Import diagnostics"):
                    st.text("\n".join(report["diagnostics"]))
else:
    if not files:
        empty_state("Your source library starts here", "Choose Import to add a ZIP archive, a folder or an allowed host directory.")
    else:
        st.subheader("Source inventory")
        pending = sum(f["parsing_status"] == "pending" for f in files)
        st.caption(f"{len(files):,} files · {pending:,} pending analysis")
        with st.container(horizontal=True, vertical_alignment="bottom"):
            search = st.text_input("Filter inventory", placeholder="Path, file name or status", key="inventory_search_" + w)
            st.page_link("ui/pages/analysis.py", label="Open Analysis", icon=":material/play_circle:")
        shown = [f for f in files if search.casefold() in (f["relative_path"] + " " + f["parsing_status"]).casefold()]
        config = ParsingSettings.from_store(store, w).model_dump()
        inventory = [{**{k: f[k] for k in ['relative_path', 'extension', 'file_size', 'encoding',
                                         'line_count', 'parsing_status', 'content_hash']},
                      'sql_source_type': dialect_label(source_dialect(f, config))
                      if f['extension'] == '.sql' and not is_dbt(f) else ''} for f in shown]
        st.dataframe(inventory, hide_index=True, column_config={"content_hash": None,
            "relative_path": "Source file", "extension": "Type", "file_size": "Bytes",
            "encoding": "Encoding", "line_count": "Lines", "parsing_status": "Status",
            'sql_source_type': 'SQL source type'}, alt="Imported source inventory")
        downloads(inventory, "inventory", include_html=False)
        if notice := st.session_state.pop('source_dialect_notice_' + w, None):
            st.success(notice)
        panel = st.expander("Inspect a source file", on_change="rerun", key="inventory_source_panel")
        if panel.open:
            with panel:
                source_viewer(store, [f["file_id"] for f in shown], "inventory_source")
                fid = st.session_state.get("inventory_source_file")
                source = next((f for f in shown if f['file_id'] == fid), None)
                if source:
                    if source['extension'] == '.sql' and not is_dbt(source):
                        explicit = explicit_source_dialect(source)
                        current = 'Use workspace settings' if explicit is None else dialect_label(explicit)
                        choice = st.selectbox('SQL source type', SQL_SOURCE_TYPES,
                            index=list(SQL_SOURCE_TYPES).index(current), key=f'inventory_dialect_{fid}_{explicit}')
                        if st.button('Save SQL source type', disabled=SQL_SOURCE_TYPES[choice] == explicit):
                            try:
                                set_source_dialect(store, w, fid, SQL_SOURCE_TYPES[choice])
                                st.session_state['source_dialect_notice_' + w] = 'SQL source type saved. Open Analysis to reanalyze this file.'
                                st.rerun()
                            except ValueError as exc:
                                st.error(str(exc))
                    with st.expander("File metadata"):
                        st.json(json.loads(source["metadata"]))
