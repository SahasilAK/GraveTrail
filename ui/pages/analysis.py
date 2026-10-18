from collections import Counter

import streamlit as st

from dataforge.services import analyze
from ui.common import context, title
from ui.presentation import empty_state, section

title("Analysis", "Turn source code into dependencies you can inspect, verify and trace.")
store, w = context()
mode = section("Analysis view", ["Run", "Diagnostics", "History"], "analysis_section_" + w)
files = store.files(w)
if not files:
    empty_state("Ready when your sources are", "Add SQL, SAS or CSV files to build your first evidence-backed analysis.", ":material/play_circle:")
    st.page_link("ui/pages/builder.py", label="Import sources", icon=":material/upload_file:")
elif mode == "Run":
    if result := st.session_state.pop("analysis_notice_" + w, None):
        st.success(f"Analysis complete: {result['assets']} assets, {result['edges']} dependencies. "
                   f"Parsed {result['analyzed']}; reused {result['cached']} cached files in {result['duration']:.2f}s.")
        with st.container(horizontal=True):
            st.page_link("ui/pages/explorer.py", label="Explore lineage", icon=":material/account_tree:")
            st.button("Review diagnostics", icon=":material/fact_check:",
                      on_click=lambda: st.session_state.update({"analysis_section_" + w: "Diagnostics"}))
    statuses = Counter(f["parsing_status"] for f in files)
    with st.container(horizontal=True):
        for label, status in [("Successful parses", "success"), ("Partial parses", "partial"),
                              ("Failed parses", "failed"), ("Pending files", "pending")]:
            st.metric(label, statuses[status], border=True)
    st.caption("Extensions: " + ", ".join(f"{ext}: {count}" for ext, count in sorted(Counter(f["extension"] for f in files).items())))
    with st.container(border=True, key="analysis_run"):
        st.subheader("Build your lineage", icon=":material/play_circle:")
        st.write("Analyze new or changed files. Original source stays local and is never executed.")
        paths = {f["file_id"]: f["relative_path"] for f in files}
        key = "analysis_files_" + w
        if key in st.session_state:
            st.session_state[key] = [fid for fid in st.session_state[key] if fid in paths]
        selected = st.multiselect("Files to analyze (leave empty for all)", list(paths), format_func=paths.get,
                                  key=key, persist_state="session")
        run = st.button("Analyze selected" if selected else "Analyze all files", type="primary", icon=":material/play_arrow:")
        rebuild, validate = False, False
        with st.expander("Rebuild & validation"):
            st.caption("Rebuild reparses every file. Validation checks the evidence already stored; neither executes source code.")
            with st.container(horizontal=True):
                rebuild = st.button("Rebuild all lineage", icon=":material/refresh:")
                validate = st.button("Validate stored lineage", icon=":material/verified:")
        if run or rebuild:
            try:
                bar = st.progress(0, text="Reading inventory")
                result = analyze(store, w, (selected or None) if not rebuild else None,
                                 force=rebuild or store.setting(w, "reanalysis_mode", "changed") == "all",
                                 progress=lambda p, text: bar.progress(p, text=text))
                st.session_state["last_analysis"] = result
                st.session_state["analysis_notice_" + w] = result
                st.rerun()
            except Exception as exc:
                st.error(f"Analysis failed ({type(exc).__name__}). Previous committed lineage was retained.")
        if validate:
            from dataforge.reporting import validate_lineage_evidence
            invalid = validate_lineage_evidence(store, w)["invalid"]
            (st.error if invalid else st.success)(f"Validation: {len(invalid)} invalid evidence records")
elif mode == "Diagnostics":
    from ui.analysis_sections import render_diagnostics
    render_diagnostics(store, w)
else:
    from ui.analysis_sections import render_history
    render_history(store, w)
