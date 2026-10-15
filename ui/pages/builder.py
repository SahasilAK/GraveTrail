import json
from dataclasses import asdict

import streamlit as st

from dataforge.ingestion import Importer, Limits
from dataforge.services import analyze
from ui.common import allowed_roots, context, downloads, source_viewer, title

title("Lineage builder", "Import source files, inspect the inventory, then build evidence-backed lineage.")
store, w = context()
mode = st.segmented_control("Input source", ["ZIP archive", "Folder upload", "Host directory"], default="ZIP archive")
extensions = {"." + x for x in st.multiselect("File types to analyze", ["sql", "sas", "csv"], default=["sql", "sas", "csv"])}
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
if st.button("Import into inventory", type="primary", disabled=not extensions):
    try:
        limits = Limits(max_file_bytes=int(store.setting(w, "max_file_mb", 20)) * 1024 * 1024,
                        max_files=int(store.setting(w, "max_files", 10000)))
        importer = Importer(store, w, allowed_roots(), limits)
        status = st.empty()
        def progress(r):
            status.caption(f"Discovered {r.discovered}; accepted {r.accepted}; skipped {r.skipped}")
        if mode == "ZIP archive" and archive:
            report = importer.zip(archive.getvalue(), extensions, progress)
        elif mode == "Folder upload" and entries:
            report = importer.files(((f.name, f.getvalue()) for f in entries), extensions, progress)
        elif mode == "Host directory":
            report = importer.directory(directory, extensions, progress)
        else:
            raise ValueError("Choose source files first")
        progress(report)
        st.session_state["import_report_" + w] = asdict(report)
        st.success(f"Imported {report.accepted} files. Analyze the inventory below.")
    except Exception as exc:
        st.error(f"Import failed: {exc}")
if "import_report_" + w in st.session_state:
    report = st.session_state["import_report_" + w]
    st.write({k: v for k, v in report.items() if k != "diagnostics"})
    if report["diagnostics"]:
        with st.expander("Import diagnostics"):
            st.text("\n".join(report["diagnostics"]))
files = store.files(w)
if files:
    st.divider()
    st.subheader("Master file inventory")
    search = st.text_input("Filter inventory", placeholder="Path, file name or status")
    shown = [f for f in files if search.casefold() in (f["relative_path"] + " " + f["parsing_status"]).casefold()]
    inventory = [{k: f[k] for k in ["relative_path", "extension", "file_size", "encoding", "line_count", "parsing_status", "content_hash"]} for f in shown]
    st.dataframe(inventory, hide_index=True)
    downloads(inventory, "inventory", include_html=False)
    paths = {f["file_id"]: f["relative_path"] for f in files}
    selected = st.multiselect("Files to analyze (leave empty for all)", list(paths), format_func=paths.get)
    with st.container(horizontal=True):
        run = st.button("Analyze selected" if selected else "Analyze all files", type="primary")
        rebuild = st.button("Rebuild all lineage")
        validate = st.button("Validate stored lineage")
    if run or rebuild:
        try:
            bar = st.progress(0, text="Reading inventory")
            result = analyze(store, w, selected or None if not rebuild else None, force=rebuild,
                             progress=lambda p, text: bar.progress(p, text=text))
            st.success(f"Analysis complete: {result['assets']} assets, {result['edges']} dependencies. "
                       f"Parsed {result['analyzed']}; reused {result['cached']} cached files in {result['duration']:.2f}s.")
            st.session_state["last_analysis"] = result
        except Exception as exc:
            st.error(f"Analysis failed ({type(exc).__name__}). Previous committed lineage was retained.")
    if validate:
        invalid = [e for e in store.edges(w) if not e["code"] or e["start_line"] < 1 or not 0 <= e["confidence"] <= 1]
        (st.error if invalid else st.success)(f"Validation: {len(invalid)} invalid evidence records")
    diagnostics = store.diagnostics(w)
    if diagnostics:
        with st.expander(f"Parsing diagnostics ({len(diagnostics)})", expanded=True):
            st.dataframe([{k: d[k] for k in ["relative_path", "line", "severity", "message"]} for d in diagnostics], hide_index=True)
    with st.expander("Inspect a source file"):
        source_viewer(store, list(paths), "inventory_source")
        fid = st.session_state.get("inventory_source_file")
        if fid:
            st.json(json.loads(store.file(fid)["metadata"]))
    with st.expander("Optional AI assistance"):
        from ui.assistance import render
        render(store, w)
