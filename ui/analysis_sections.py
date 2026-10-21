"""Lazy diagnostic investigation and run history; source and AI stay explicit."""
import json

import streamlit as st

from dataforge.services import compare_runs
from dataforge.store import Store
from ui.common import source_viewer


def render_diagnostics(store: Store, w: str) -> None:
    """Render parser diagnostics and expandable source-backed review controls.

    Args:
        store: Workspace storage service.
        w: Workspace identifier."""
    diagnostics = store.diagnostics(w)
    visibility = store.setting(w, "diagnostic_visibility", "all")
    if visibility != "all":
        diagnostics = [d for d in diagnostics if d["severity"] == "error" or
                       (visibility == "warnings_errors" and d["severity"] == "warning")]
        st.caption("Parsing diagnostic display is filtered. All diagnostics remain stored and unresolved review still includes warnings/errors.")
    pending = {f["file_id"] for f in store.files(w) if f["parsing_status"] == "pending"}
    if any(d["file_id"] in pending for d in diagnostics):
        st.warning("Some diagnostics refer to files pending reanalysis. Run Analysis before inspecting their source evidence.")
    st.subheader("Parsing diagnostics", icon=":material/fact_check:")
    severity = st.selectbox("Severity", ["All", "error", "warning", "info"], key="diagnostic_severity_" + w)
    shown = [d for d in diagnostics if severity == "All" or d["severity"] == severity]
    if shown:
        st.dataframe([{**{k: d[k] for k in ["severity", "relative_path", "line", "message"]}, "Source revision": "Pending reanalysis" if d["file_id"] in pending else "Current"} for d in shown], hide_index=True,
                     column_config={"relative_path": "Source file", "line": "Line", "severity": "Severity", "message": "Message"},
                     alt="Parser diagnostics with exact source locations")
        panel = st.expander("Inspect diagnostic evidence", on_change="rerun", key="diagnostic_source_panel")
        if panel.open:
            with panel:
                options = {d["diagnostic_id"]: d for d in shown if d["file_id"] not in pending}
                if not options:
                    st.info("Analyze pending files to inspect current diagnostic evidence.")
                else:
                    key = "diagnostic_source_choice_" + w
                    if st.session_state.get(key) not in options:
                        st.session_state.pop(key, None)
                    chosen = st.selectbox("Diagnostic", list(options), format_func=lambda k: f"{options[k]['relative_path']}:{options[k]['line']} · {options[k]['message']}", key=key)
                    d = options[chosen]
                    source = store.file(d["file_id"])
                    if source["parsing_status"] == "pending":
                        st.warning("This source is pending reanalysis. Refresh Analysis before inspecting evidence.")
                    else:
                        first = max(1, int(d["line"] or 1) - 2)
                        last = min(source["line_count"], first + 6)
                        evidence = [{"file_id": d["file_id"], "statement_id": chosen, "start_line": first, "end_line": last,
                                     "code": "\n".join(source["raw_content"].splitlines()[first-1:last]), "kind": "Diagnostic context", "source_hash": source["content_hash"]}]
                        source_viewer(store, [d["file_id"]], "diagnostic_source", evidence)
    else:
        st.success("No diagnostics match this view. Unsupported constructs remain visible when reported by the parser.", icon=":material/check_circle:")
    st.subheader("Optional AI review")
    st.badge("External requests enabled" if store.setting(w, "external_llm", False) else "External requests disabled", icon=":material/shield:")
    review_panel = st.expander("Unresolved review queue", on_change="rerun", key="unresolved_review_panel")
    if review_panel.open:
        with review_panel:
            from ui.unresolved_review import render
            render(store, w)
    manual_panel = st.expander("Optional AI assistance", on_change="rerun", key="manual_assistance_panel")
    if manual_panel.open:
        with manual_panel:
            from ui.assistance import render
            render(store, w)


def render_history(store: Store, w: str) -> None:
    """Render recent analysis runs and comparisons between completed runs.

    Args:
        store: Workspace storage service.
        w: Workspace identifier."""
    from ui.analysis_ai import report
    report(store, w)
    st.subheader("Analysis history", icon=":material/history:")
    st.dataframe([{k: r[k] for k in ["created_at", "status", "analyzed", "cached", "duration"]} for r in store.runs(w)[:50]],
                 hide_index=True, column_config={"created_at": "Started", "analyzed": "Parsed files", "cached": "Reused files", "duration": st.column_config.NumberColumn("Seconds", format="%.2f")},
                 alt="Recent analysis runs")
    st.subheader("Compare completed runs")
    runs = [r for r in store.runs(w) if r["status"] == "completed"]
    if len(runs) < 2:
        st.info("Complete at least two analysis runs to compare workspace changes.")
    else:
        options = {r["run_id"]: r for r in runs}
        def fmt(k):
            return f"{options[k]['created_at']} ({k[:8]})"
        before = st.selectbox("Baseline run", list(options), index=1, format_func=fmt)
        after = st.selectbox("Comparison run", list(options), format_func=fmt)
        result = compare_runs(options[before], options[after])
        st.dataframe([{"Change": name.replace("_", " ").capitalize(), "Count": len(values)} for name, values in result.items()],
                     hide_index=True, alt="Changes between completed analysis runs")
        with st.expander("Complete comparison details"):
            st.json(result)
        st.download_button("Download comparison", json.dumps(result, indent=2), "comparison.json", "application/json")
