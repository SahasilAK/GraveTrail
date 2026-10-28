"""Shared lineage controls and selection-driven graph inspection."""
import json

import streamlit as st

from dataforge.column_evidence import load_column_evidence
from dataforge.column_graph import build_column_scene
from dataforge.configuration import ParsingSettings, VisualizationSettings
from dataforge.exports import report_csv
from dataforge.services import analysis_is_current
from dataforge.transformations import column_catalog, trace_columns
from ui.column_graph import column_graph_view, resolve_selection


@st.fragment
def render_column_lineage(store, workspace, asset, *, key="column_lineage"):
    w = workspace
    if not analysis_is_current(store, w):
        st.warning("Analysis is out of date. These are the last stored transformations; run Analysis to refresh coverage.")

    catalog = column_catalog(store, w, asset, limit=500)
    scope_key = f"{w}_{asset}"
    choices = {c["column_id"]: c for c in catalog}
    if choices:
        if st.session_state.get("transformation_column_" + scope_key) not in choices:
            st.session_state.pop("transformation_column_" + scope_key, None)
        column = st.selectbox("Column to trace", list(choices),
            format_func=lambda k: f'{choices[k]["column_name"]} · {choices[k].get("scope") or "physical"}' +
                                 (f' · v{choices[k]["version"]}' if choices[k].get("version") else ""),
            key="transformation_column_" + scope_key)
        if len(catalog) == 500:
            st.caption("Showing up to 500 columns. Enter a column name or exact ID below if yours is outside this selection.")
    else:
        column = None
        st.info("No transformation columns are cataloged for this asset. Run Analysis to establish coverage, or enter a column name to inspect its state.")
    requested = st.text_input("Column name or exact ID", placeholder="Optional: trace a column outside the selector",
                              key="transformation_exact_" + scope_key)
    column = requested.strip() or column
    if not column:
        st.stop()

    with st.container(horizontal=True, vertical_alignment="bottom"):
        direction = st.segmented_control("Direction", ["upstream", "downstream"], default="upstream",
            format_func=lambda value: "How it is produced" if value == "upstream" else "What it affects",
            key="transformation_direction_" + scope_key) or "upstream"
        depth = st.slider("Transformation depth", 1, 15, 5, key="transformation_depth_" + scope_key)
        status = st.selectbox("Resolution status", ["all", "verified", "inferred", "unresolved"],
                             key="transformation_status_" + scope_key)

    revision = store.rows("SELECT * FROM column_analysis WHERE workspace_id=?", [w])
    freshness = analysis_is_current(store, w)
    cache_key = json.dumps([str(store.home), w, asset, column, direction, depth, status, revision, freshness,
                            {name: store.setting(w, name, value) for name, value in ParsingSettings().model_dump().items()}], default=str)
    try:
        cached = st.session_state.get(key + "_trace")
        if not cached or cached[0] != cache_key:
            cached = (cache_key, trace_columns(store, w, asset, column, direction=direction,
                      depth=depth, limit=200, status=status, include_source=False))
            st.session_state[key + "_trace"] = cached
        trace = cached[1]
    except ValueError as exc:
        st.info(str(exc))
        return

    steps = trace["derivations"]
    coverage = trace["coverage"]
    state_messages = {
        "constant": "Known constant: this output has no value input columns. Row-selection context may still apply.",
        "not_analyzed": "Transformation coverage is not available. Run Analysis to establish column derivations.",
        "unresolved": "This column could not be resolved statically. Review the coverage boundaries below.",
        "no_known_dependency": "No known dependency in this direction. This does not establish runtime independence.",
    }
    with st.container(horizontal=True):
        st.metric("Transformation steps", len(steps), border=True)
        st.metric("Coverage boundaries", len(coverage), border=True)
        st.metric("Trace state", trace["state"].replace("_", " ").capitalize(), border=True)
    if trace["state"] in state_messages:
        st.info(state_messages[trace["state"]])
    if trace["truncated"]:
        st.warning("This trace reached a traversal limit. Exported results carry the same incomplete coverage markers.")
    elif not trace["complete"]:
        st.warning("Coverage is incomplete. Known steps are shown alongside their unresolved boundaries.")
    if coverage:
        with st.expander("Coverage details", expanded=not steps):
            st.dataframe(coverage, hide_index=True, alt="Transformation coverage boundaries")
    st.caption("Value inputs supply an output. Selection, matching, rowset and ordering roles describe other effects. Static coverage does not verify runtime behavior.")

    if steps:
        display = []
        for index, step in enumerate(steps, 1):
            evidence = step.get("evidence") or {}
            target = step["target"]
            display.append({"Step": index, "Output": f'{target.get("table", "")}.{target["column_name"]}',
                "Transformation": step["category"], "Status": step["status"],
                "Inputs and roles": "; ".join(f'{i.get("table", "")}.{i.get("column_name") or "[rowset]"} ({i["role"]})' for i in step["inputs"]),
                "Branch": step.get("branch"), "Source file": evidence.get("relative_path"),
                "Lines": f'{evidence.get("start_line", "")}–{evidence.get("end_line", "")}'})
        root = choices.get(column)
        if root is None:
            root = next((ref for step in steps for ref in [step["target"], *step["inputs"]]
                         if ref["column_id"] == column or (ref["asset_id"] == asset and ref["column_name"] == column)), None)
        scene = build_column_scene(trace, root, status=status)
        scene_key = scene["trace_key"]
        if scene.get("display_truncated"):
            st.warning(f"Reduced graph display: {scene['omitted_derivations']} transformations, "
                       f"{scene['omitted_nodes']} nodes and {scene['omitted_edges']} edges omitted. Table and exports retain the bounded trace.")
        selection = resolve_selection(scene, st.session_state.get(key + "_selection"))
        component = column_graph_view(scene, key=key + "_graph", selection=selection,
                                      appearance=VisualizationSettings.from_store(store, w))
        event = resolve_selection(scene, component.selection)
        new_event = event is not None and event != selection
        if event is not None:
            selection = event
            st.session_state[key + "_selection"] = selection
        related = steps
        if selection:
            if selection["kind"] == "transformation":
                related = [d for d in steps if "derivation:" + d["derivation_id"] == selection["id"]]
            elif selection["kind"] == "edge":
                edge = next(e for e in scene["edges"] if e["id"] == selection["id"])
                related = [d for d in steps if d["derivation_id"] == edge["derivation_id"]]
            else:
                cid = selection["id"].removeprefix("column:")
                refs = [r for d in steps for r in [d["target"], *d["inputs"]] if r["column_id"] == cid]
                if refs:
                    st.caption("Selected column: " + refs[0]["table"] + "." + (refs[0]["column_name"] or "[rowset]"))
                related = [d for d in steps if d["target"]["column_id"] == cid or any(i["column_id"] == cid for i in d["inputs"])]
        if not related:
            st.info("No returned transformation is associated with this column.")
        else:
            candidates = {d["derivation_id"]: d for d in related}
            selected_id = st.selectbox("Transformation step", [None, *candidates],
                index=1 if selection and len(candidates) == 1 else 0,
                format_func=lambda did: "Choose a transformation" if did is None else
                    candidates[did]["target"]["table"] + "." + candidates[did]["target"]["column_name"] + " · " + candidates[did]["category"],
                key=key + "_step_" + scene_key + (selection["id"] if selection else ""))
            if new_event and selected_id is not None:
                st.session_state["transformation_inspector_" + scope_key] = True
            inspector = st.expander("Transformation logic", expanded=selected_id is not None,
                on_change="rerun", key="transformation_inspector_" + scope_key)
            if inspector.open and selected_id is not None:
                with inspector:
                    step = candidates[selected_id]
                    logic = load_column_evidence(store, w, trace["run_id"], step["derivation_id"])
                    st.code(logic.get("expression") or "Expression unavailable", language=logic["evidence"].get("language", "text"))
                    if logic["evidence"].get("coordinate_warning"):
                        st.warning(logic["evidence"]["coordinate_warning"])
                    st.caption("Original statement preview (up to 12,000 characters)")
                    st.code(logic["statement_preview"].get("code", ""), language=logic["statement_preview"].get("language", "text"))
                    st.dataframe(step["inputs"], hide_index=True, alt="Exact input columns and roles")
                    st.json({k: step[k] for k in ("category", "status", "branch", "ordinal", "coverage")})
                    st.dataframe([p for p in trace["paths"] if p["derivation_id"] == step["derivation_id"]], hide_index=True, alt="Value and row-selection effects")
            step = candidates.get(selected_id)
            if step:
                did = step["derivation_id"]
                evidence = load_column_evidence(store, w, trace["run_id"], did)
                meta = evidence["evidence"]
                st.caption(f"{meta.get('relative_path', 'Unknown source')} · lines {meta.get('start_line', '?')}–{meta.get('end_line', '?')} · {meta.get('source_hash', '')}")
                file_panel = st.expander("Analyzed source file", on_change="rerun", key=key + "_file_" + scene_key)
                if file_panel.open:
                    with file_panel:
                        detail = load_column_evidence(store, w, trace["run_id"], did, include_file=True)
                        source = detail.get("file")
                        if source is None:
                            st.warning("Analyzed source version unavailable")
                        else:
                            if source.get("version_mismatch"):
                                st.warning("Showing the analyzed version; the inventory contains a newer file.")
                            if meta.get("coordinate_warning"):
                                st.warning(meta["coordinate_warning"])
                            lines = source["raw_content"].splitlines()
                            file_key = key + scene_key + did + source["content_hash"]
                            page_count = max(1, (len(lines) + 199) // 200)
                            focus = source.get("focus_start_line") or 1
                            page = st.number_input("Source page", 1, page_count, min(page_count, (focus - 1) // 200 + 1), key=file_key + "_page")
                            find = st.text_input("Find in analyzed source", key=file_key + "_find")
                            if find:
                                hits = [str(i) for i, line in enumerate(lines, 1) if find.casefold() in line.casefold()]
                                st.caption("Matching lines: " + (", ".join(hits[:100]) or "none"))
                            start = (page - 1) * 200
                            chunk = lines[start:start + 200]
                            clipped = any(len(line) > 12000 for line in chunk)
                            st.caption(f"Original lines {start + 1}–{min(start + 200, len(lines))} · page {page}/{page_count}")
                            st.code("\n".join(f"{start + offset:6}  {line[:12000]}" for offset, line in enumerate(chunk, 1)), language=source.get("language", "text"), line_numbers=False)
                            if clipped:
                                st.warning("Long lines are capped at 12,000 characters in this view. Download contains the complete original.")
                            st.download_button("Download analyzed file", lambda: store.original(meta["file_id"], meta["source_hash"]),
                                source["file_name"], key=file_key + "_download", on_click="ignore")

        with st.expander("Steps and paths"):
            st.dataframe(display, hide_index=True, alt="Ordered column transformations and dependency roles")

    else:
        root = choices.get(column)
        if root is not None:
            scene = build_column_scene(trace, root, status=status)
            column_graph_view(scene, key=key + "_graph", selection=None,
                              appearance=VisualizationSettings.from_store(store, w))
        st.caption("No returned transformations to inspect. Coverage above explains any unresolved boundary.")

    markers = {k: trace[k] for k in ("workspace_id", "asset_id", "column", "direction", "depth", "state", "truncated", "complete", "run_id")}
    export_rows = [{**markers, "coverage": json.dumps(coverage, default=str),
                    "paths": json.dumps([p for p in trace["paths"] if p["derivation_id"] == step["derivation_id"]], default=str),
                    **{key: json.dumps(value, default=str) if isinstance(value, (dict, list)) else value
                       for key, value in step.items()}} for step in steps]
    if not export_rows:
        export_rows = [{**markers, "coverage": json.dumps(coverage, default=str)}]
    with st.popover("Export trace", icon=":material/download:"):
        st.caption("Exports contain this bounded trace, original expressions, evidence references and coverage markers.")
        st.download_button("Download JSON", lambda: json.dumps(trace, indent=2, default=str),
                           "column_transformations.json", "application/json", on_click="ignore")
        st.download_button("Download CSV", lambda: report_csv(export_rows),
                           "column_transformations.csv", "text/csv", on_click="ignore")
