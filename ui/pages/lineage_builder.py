"""Create schema catalogs and author column-level lineage."""
from uuid import uuid4

import duckdb
import streamlit as st
from pydantic import ValidationError

from dataforge.configuration import VisualizationSettings
from dataforge.datatypes import TYPE_CATALOG, type_entry
from dataforge.lineage_builder import (
    JOIN_TYPES,
    BuilderDocument,
    BuilderLink,
    BuilderTable,
    columns_from_rows,
    export_schemas,
    export_tabular,
    get_builder_work,
    list_builder_works,
    load_builder,
    load_builder_work,
    save_builder,
    save_builder_work,
    save_canvas_work,
    schema_rows,
)
from dataforge.schema_imports import import_schema
from ui.builder_canvas import builder_html, builder_node_colors, canvas, column_editor
from ui.common import context, title
from ui.presentation import section
from ui.themes import _loaded_preset

title("Lineage builder", "Design table schemas and connect columns to build and present your own lineage.")
store, w = context()
prefix = "lineage_builder_" + w
node_colors = builder_node_colors(_loaded_preset(), VisualizationSettings.from_store(store, w).graph_palette,
                                  dark=st.get_option("theme.base") == "dark")
if notice := st.session_state.pop(prefix + "notice", None):
    st.success(notice)
try:
    document = load_builder(store, w)
except (ValueError, duckdb.Error):
    st.error("Cannot load the saved builder. Check storage access or restore a workspace backup.")
    st.stop()


def commit(payload: dict, notice: str) -> None:
    try:
        save_builder(store, w, BuilderDocument.model_validate(payload))
        st.session_state.pop(prefix + "preview", None)
        st.session_state[prefix + "notice"] = notice
        st.rerun()
    except (ValueError, duckdb.Error, OSError) as exc:
        st.error(str(exc)[:600])


def table_form(existing: BuilderTable | None = None, place: bool = False) -> None:
    form_key = prefix + (existing.id if existing else "new")
    saved_system = existing.system if existing and existing.system else "Generic SQL"
    systems = list(TYPE_CATALOG)
    if saved_system not in systems:
        systems.append(saved_system)
    system = st.selectbox("System / database", systems, index=systems.index(saved_system),
                          key=form_key + "_system", accept_new_options=True,
                          help="Choose a system to see its datatype suggestions, or enter another system.") or "Generic SQL"
    editor_key = form_key + f"_columns_{document.revision}"
    rows = [{**c.model_dump(), **type_entry(c.data_type, system)} for c in existing.columns] if existing and existing.columns else [
        {"id": "", "name": "", "comment": "", **type_entry("")}]
    with st.form(form_key):
        name = st.text_input("Table name", value=existing.name if existing else "", max_chars=300,
                             placeholder="e.g. warehouse.customer")
        roles = ["source", "intermediate", "target"]
        role = st.selectbox("Table role", roles, index=roles.index(existing.role) if existing else (1 if place else 0))
        comment = st.text_input("Table comment", value=existing.comment if existing else "", max_chars=2000)
        st.caption("Type a datatype or choose a suggestion in the same field. For decimals, enter precision and scale, or write DECIMAL(18,2).")
        edited = column_editor(rows, system, editor_key)
        allow_prune = st.checkbox("Allow deleting columns and their relationships", value=False) if existing else False
        if st.form_submit_button("Save table" if existing else "Create table", type="primary"):
            try:
                columns = columns_from_rows(edited, system, existing=existing.columns if existing else None)
                table = BuilderTable(id=existing.id if existing else uuid4().hex, name=name, role=role,
                                     comment=comment, columns=columns, system=system, size=existing.size if existing else None,
                                     folder=existing.folder if existing else None, canvas_member=True,
                                     catalog_hidden=existing.catalog_hidden if existing else False,
                                     color=existing.color if existing else "",
                                     position=existing.position if existing else None)
                payload = document.model_dump()
                if existing:
                    payload["tables"] = [table.model_dump() if t["id"] == existing.id else t for t in payload["tables"]]
                    retained = {c.id for c in columns}
                    links = [e for e in payload["links"] if not (
                        (e["source_table"] == table.id and e["source_column"] not in retained) or
                        (e["target_table"] == table.id and e["target_column"] not in retained))]
                    if len(links) != len(payload["links"]) and not allow_prune:
                        raise ValueError("Deleted columns have relationships. Select the checkbox to remove those relationships, or keep the columns.")
                    payload["links"] = links
                else:
                    payload["tables"].append(table.model_dump())
                commit(payload, "Table saved.")
            except ValueError as exc:
                st.error(str(exc)[:600])


mode = section("Builder workspace", ["Schemas & data entry", "Build lineage", "Export schemas", "Saved work"], prefix + "section")
st.caption(f"{len(document.tables)} tables · {sum(len(t.columns) for t in document.tables)} columns · {len(document.links)} relationships · Saved in this workspace")

if mode == "Schemas & data entry":
    action = section("Schema action", ["Create table", "Import schemas", "Edit tables"], prefix + "schema_action")
    if action == "Create table":
        st.subheader("Create a table")
        st.caption("Define source, intermediate or target tables. Add column names, data types and optional comments.")
        table_form()
    elif action == "Import schemas":
        st.subheader("Import table schemas")
        st.caption("SQL CREATE TABLE / DDL · dbt schema YAML, manifest or catalog JSON · Informatica PowerCenter XML · SAS explicit LENGTH / PROC SQL DDL · JSON table lists · schema CSV/TSV")
        st.caption("Uploads are read as text only. Runtime-generated schemas and vendor formats outside this list require a schema export or manual entry.")
        uploaded = st.file_uploader("Schema files", type=["sql", "ddl", "hql", "sas", "yml", "yaml", "json", "xml", "csv", "tsv"],
                                    accept_multiple_files=True, max_upload_size=5, key=prefix + "imports")
        dialect = st.selectbox("SQL dialect", ["Auto", "postgres", "mysql", "tsql", "oracle", "snowflake", "bigquery", "spark", "hive", "duckdb"], key=prefix + "dialect")
        if st.button("Preview schemas", disabled=not uploaded):
            tables, notes = [], []
            try:
                if sum(f.size for f in uploaded) > 10 * 1024 * 1024:
                    raise ValueError("Import batch exceeds 10 MiB; import smaller batches")
                for file in uploaded:
                    found, warnings = import_schema(file.name, file.getvalue(), None if dialect == "Auto" else dialect)
                    tables.extend(found)
                    notes.extend(f"{file.name}: {note}" for note in warnings)
                # New IDs ensure schema imports cannot collide with a different document's identities.
                for table in tables:
                    table.id, table.position = uuid4().hex, None
                    table.canvas_member = True
                    table.catalog_hidden = False
                    table.folder = None
                    table.color = ""
                    for column in table.columns:
                        column.id = uuid4().hex
                existing_names = {t.name.casefold() for t in document.tables}
                duplicate = [t.name for t in tables if t.name.casefold() in existing_names]
                if duplicate:
                    raise ValueError("These tables already exist; edit them instead: " + ", ".join(duplicate)[:300])
                BuilderDocument(tables=document.tables + tables, links=document.links, folders=document.folders)
                st.session_state[prefix + "preview"] = {"tables": [t.model_dump() for t in tables], "notes": notes}
            except ValueError as exc:
                st.session_state.pop(prefix + "preview", None)
                st.error(str(exc)[:600])
        if preview := st.session_state.get(prefix + "preview"):
            for note in preview["notes"]:
                st.warning(note)
            staged = BuilderDocument(tables=preview["tables"])
            st.dataframe(schema_rows(staged), hide_index=True, alt="Schemas ready to import")
            if st.button(f"Add {len(staged.tables)} tables", type="primary"):
                payload = document.model_dump()
                payload["tables"].extend(preview["tables"])
                commit(payload, "Schemas imported. Open Build lineage to place tables on the canvas.")
    elif action == "Edit tables":
        if not document.tables:
            st.info("Create a table or import schemas to start.")
        else:
            names = {t.id: t.name for t in document.tables}
            selected = st.selectbox("Table to edit", names, format_func=names.get, key=prefix + "edit_table")
            table = next(t for t in document.tables if t.id == selected)
            table_form(table)
            with st.expander("Delete table"):
                confirmed = st.checkbox("Delete this table and all of its relationships", key=prefix + "delete_" + selected)
                if st.button("Delete table", disabled=not confirmed):
                    payload = document.model_dump()
                    payload["tables"] = [t for t in payload["tables"] if t["id"] != selected]
                    payload["links"] = [e for e in payload["links"] if selected not in (e["source_table"], e["target_table"])]
                    commit(payload, "Table deleted.")
elif mode == "Build lineage":
    st.caption("Create or add tables to the catalog, then drag them onto the canvas or into folders. Save named copies here; Clear canvas saves a backup first. Use Saved work to load a design.")
    canvas_key = prefix + "canvas"

    def save_canvas():
        try:
            payload = st.session_state[canvas_key].get("edit")
            save_builder(store, w, BuilderDocument.model_validate(payload))
            st.session_state.pop(prefix + "canvas_error", None)
        except (ValueError, duckdb.Error, OSError) as exc:
            st.session_state[prefix + "canvas_error"] = "Canvas edit was not saved: " + str(exc)[:500]

    def create_canvas_table():
        try:
            request = st.session_state[canvas_key].get("create_table")
            if not isinstance(request, dict) or not isinstance(request.get("table"), dict):
                raise ValueError("Invalid table entry")
            raw_table = dict(request["table"])
            raw_table["position"] = None
            raw_table["canvas_member"] = True
            raw_table["columns"] = columns_from_rows(raw_table.get("columns", []), raw_table.get("system", ""))
            table = BuilderTable.model_validate(raw_table)
            payload = load_builder(store, w).model_dump()
            payload["revision"] = request.get("revision")
            payload["tables"].append(table.model_dump())
            save_builder(store, w, BuilderDocument.model_validate(payload))
            st.session_state.pop(prefix + "canvas_error", None)
        except (ValueError, duckdb.Error, OSError) as exc:
            st.session_state[prefix + "canvas_error"] = "Table was not saved: " + str(exc)[:500]

    def canvas_work_action():
        try:
            request = st.session_state[canvas_key].get("work_action")
            if not isinstance(request, dict) or request.get("action") not in ("save", "clear") or not isinstance(request.get("name", ""), str):
                raise ValueError("Invalid canvas action")
            clearing = request["action"] == "clear"
            work = save_canvas_work(store, w, request.get("name", ""), expected_revision=request.get("revision"), clear=clearing)
            st.session_state[prefix + "selected_work_id"] = work.id
            st.session_state[prefix + "work_result"] = {
                "id": work.id, "message": f'Saved as “{work.name}”.' + (" Canvas cleared; restore it from Saved work." if clearing else "")}
            st.session_state.pop(prefix + "canvas_error", None)
        except (ValueError, duckdb.Error, OSError) as exc:
            st.session_state[prefix + "canvas_error"] = "Canvas was not saved or cleared: " + str(exc)[:500]

    if error := st.session_state.pop(prefix + "canvas_error", ""):
        st.error(error)
    canvas(document, canvas_key, save_canvas, error, on_create=create_canvas_table, node_colors=node_colors,
           on_work=canvas_work_action, work_result=st.session_state.get(prefix + "work_result"))
    with st.expander("Create a table in the catalog"):
        table_form(place=True)
    with st.expander("Add a relationship without dragging"):
        choices = {t.id: t.name for t in document.tables if t.columns}
        if not choices:
            st.info("Create tables with columns first.")
        else:
            left, right = st.columns(2)
            with left:
                source_id = st.selectbox("Source table", choices, format_func=choices.get, key=prefix + "link_source")
                source = next(t for t in document.tables if t.id == source_id)
                source_columns = {c.id: c.name for c in source.columns}
                source_column = st.selectbox("Source column", source_columns, format_func=source_columns.get)
            with right:
                target_id = st.selectbox("Target table", choices, format_func=choices.get, index=min(1, len(choices)-1), key=prefix + "link_target")
                target = next(t for t in document.tables if t.id == target_id)
                target_columns = {c.id: c.name for c in target.columns}
                target_column = st.selectbox("Target column", target_columns, format_func=target_columns.get)
            label = st.text_input("Relationship label", max_chars=500)
            kind = st.selectbox("Relationship type", ["Lineage", "Join"])
            join_type = st.selectbox("Join type", JOIN_TYPES, accept_new_options=True) if kind == "Join" else ""
            if st.button("Add relationship"):
                payload = document.model_dump()
                payload["links"].append(BuilderLink(source_table=source_id, source_column=source_column,
                                                   target_table=target_id, target_column=target_column, label=label,
                                                   kind=kind.lower(), join_type=join_type or "").model_dump())
                for index, t in enumerate(payload["tables"]):
                    if t["id"] in {source_id, target_id} and not t["position"]:
                        t["position"] = {"x": 60 + (index % 3) * 520, "y": 60 + (index // 3) * 320}
                commit(payload, "Relationship added.")

elif mode == "Export schemas":
    st.subheader("Export table schemas")
    scope = st.selectbox("Tables to export", ["All tables", "Selected tables", "Source tables", "Intermediate tables", "Target tables"],
                         key=prefix + "schema_export_scope")
    ids = None
    role = {"Source tables": "source", "Intermediate tables": "intermediate", "Target tables": "target"}.get(scope)
    if scope == "Selected tables":
        names = {t.id: t.name for t in document.tables}
        ids = st.multiselect("Search and select tables", names, format_func=names.get, key=prefix + "schema_export_tables")
    selected = [t for t in document.tables if (ids is None or t.id in ids) and (role is None or t.role == role)]
    st.caption(f"{len(selected)} tables selected. Exports contain schema definitions only. SQL DDL requires column datatypes; JSON and YAML preserve custom types and comments.")
    schema_format = st.selectbox("Schema export format", ["JSON", "YAML", "SQL DDL", "CSV", "Excel"], key=prefix + "schema_export_format")
    if st.button("Prepare schema export", disabled=not selected):
        try:
            extension, mime = {"JSON": ("json", "application/json"), "YAML": ("yaml", "application/yaml"),
                               "SQL DDL": ("sql", "text/plain"), "CSV": ("csv", "text/csv"),
                               "Excel": ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}[schema_format]
            content = export_schemas(document, extension, table_ids=ids, role=role)
            st.download_button("Download schemas " + schema_format, content, "table-schemas." + extension, mime, on_click="ignore")
        except (ValueError, OSError) as exc:
            st.error(str(exc)[:600])

elif mode == "Saved work":
    st.subheader("Save, load and share lineage work")
    st.caption("The current work saves automatically in this workspace. Save named copies to keep different designs. JSON files include tables, columns, folders, joins, links, positions and box sizes so another GraveTrail user can continue editing.")
    name = st.text_input("Work name", max_chars=300, key=prefix + "work_name")
    if st.button("Save new work", disabled=not name.strip()):
        try:
            save_builder_work(store, w, name)
            st.success("Work saved in this workspace.")
        except (ValueError, duckdb.Error, OSError) as exc:
            st.error(str(exc)[:600])
    try:
        works = list_builder_works(store, w)
        if works:
            names = {work.id: work.name for work in works}
            previous_work = st.session_state.get(prefix + "selected_work_id")
            selected_work = st.selectbox("Saved work", names, format_func=names.get,
                                         index=list(names).index(previous_work) if previous_work in names else 0,
                                         key=prefix + "saved_work")
            st.session_state[prefix + "selected_work_id"] = selected_work
            work = get_builder_work(store, w, selected_work)
            st.caption("Saved: " + work.updated_at)
            st.download_button("Export saved work JSON", work.document.model_dump_json(indent=2).encode(),
                               "lineage-work.json", "application/json", on_click="ignore")
            if st.button("Update selected work with current design"):
                save_builder_work(store, w, work.name, work_id=work.id)
                st.session_state[prefix + "notice"] = "Saved work updated."
                st.rerun()
            replace_saved = st.checkbox("Replace the current work with this saved work", key=prefix + "load_work_confirm_" + work.id)
            if st.button("Load saved work", disabled=not replace_saved):
                load_builder_work(store, w, work.id, expected_revision=document.revision)
                st.session_state[prefix + "notice"] = "Saved work loaded. Open Build lineage to continue editing."
                st.rerun()
        else:
            st.info("No named works saved yet.")
    except (ValueError, duckdb.Error, OSError) as exc:
        st.error(str(exc)[:600])
    st.subheader("Import another user's work")
    imported_work = st.file_uploader("Lineage work JSON", type=["json"], max_upload_size=64, key=prefix + "import_work")
    imported_name = st.text_input("Imported work name", max_chars=300, key=prefix + "imported_work_name")
    if st.button("Import as saved work", disabled=not imported_work or not imported_name.strip()):
        try:
            incoming = BuilderDocument.model_validate_json(imported_work.getvalue())
            save_builder_work(store, w, imported_name, document=incoming)
            st.session_state[prefix + "notice"] = "Imported work saved. Select it above and load it when ready."
            st.rerun()
        except (ValueError, duckdb.Error, OSError) as exc:
            st.error(str(exc)[:600])

with st.expander("Export & restore builder"):
    st.caption("The canvas Export menu saves SVG, PNG or editable canvas JSON. HTML exports an offline interactive presentation. CSV/Excel include every table and relationship. JSON preserves the complete editable builder.")
    format = st.selectbox("Builder export format", ["JSON", "HTML", "Excel", "CSV"], key=prefix + "export_format")
    if st.button("Prepare builder export", disabled=not document.tables):
        try:
            extension, mime = {"JSON": ("json", "application/json"), "HTML": ("html", "text/html"),
                               "Excel": ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"), "CSV": ("csv", "text/csv")}[format]
            content = document.model_dump_json(indent=2).encode() if format == "JSON" else builder_html(document, node_colors=node_colors) if format == "HTML" else export_tabular(document, extension)
            st.download_button("Download builder " + format, content, "lineage-builder." + extension, mime, on_click="ignore")
        except (ValueError, OSError) as exc:
            st.error(str(exc)[:600])
    restore = st.file_uploader("Restore an editable builder JSON", type=["json"], max_upload_size=5, key=prefix + "restore")
    replace = st.checkbox("Replace this workspace's builder with the uploaded JSON", key=prefix + "replace")
    if st.button("Restore builder", disabled=not restore or not replace):
        try:
            restored = BuilderDocument.model_validate_json(restore.getvalue())
            payload = restored.model_dump()
            payload["revision"] = document.revision
            commit(payload, "Builder restored.")
        except (ValueError, ValidationError) as exc:
            st.error(str(exc)[:600])
