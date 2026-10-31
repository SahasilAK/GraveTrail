"""Create schema catalogs and author column-level lineage."""
from uuid import uuid4

import duckdb
import streamlit as st
from pydantic import ValidationError

from dataforge.lineage_builder import (
    BuilderColumn,
    BuilderDocument,
    BuilderLink,
    BuilderTable,
    export_tabular,
    load_builder,
    save_builder,
    schema_rows,
)
from dataforge.schema_imports import import_schema
from ui.builder_canvas import builder_html, canvas
from ui.common import context, title
from ui.presentation import section

title("Lineage builder", "Design table schemas and connect columns to build and present your own lineage.")
store, w = context()
prefix = "lineage_builder_" + w
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
    with st.form(form_key):
        name = st.text_input("Table name", value=existing.name if existing else "", max_chars=300,
                             placeholder="e.g. warehouse.customer")
        roles = ["source", "intermediate", "target"]
        role = st.selectbox("Table role", roles, index=roles.index(existing.role) if existing else (1 if place else 0))
        comment = st.text_input("Table comment", value=existing.comment if existing else "", max_chars=2000)
        rows = [c.model_dump() for c in existing.columns] if existing else [{"id": "", "name": "", "data_type": "", "comment": ""}]
        edited = st.data_editor(rows, num_rows="dynamic", hide_index=True, key=form_key + f"_columns_{document.revision}",
                                column_config={"id": None, "name": st.column_config.TextColumn("Column name", required=True),
                                               "data_type": st.column_config.TextColumn("Data type"),
                                               "comment": st.column_config.TextColumn("Comment")},
                                alt="Table columns. Add or delete rows to change the schema.")
        allow_prune = st.checkbox("Allow deleting columns and their relationships", value=False) if existing else False
        if st.form_submit_button("Save table" if existing else "Create table", type="primary"):
            try:
                columns = []
                for row in edited:
                    if not any(row.get(k) for k in ("name", "data_type", "comment")):
                        continue
                    columns.append(BuilderColumn(id=row.get("id") or uuid4().hex, name=row.get("name") or "",
                                                 data_type=row.get("data_type") or "", comment=row.get("comment") or ""))
                table = BuilderTable(id=existing.id if existing else uuid4().hex, name=name, role=role,
                                     comment=comment, columns=columns,
                                     position=existing.position if existing else ({"x": 80, "y": 80} if place else None))
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


mode = section("Builder workspace", ["Schemas & data entry", "Build lineage"], prefix + "section")
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
                    for column in table.columns:
                        column.id = uuid4().hex
                existing_names = {t.name.casefold() for t in document.tables}
                duplicate = [t.name for t in tables if t.name.casefold() in existing_names]
                if duplicate:
                    raise ValueError("These tables already exist; edit them instead: " + ", ".join(duplicate)[:300])
                BuilderDocument(tables=document.tables + tables, links=document.links)
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
else:
    st.caption("Connect source outputs on the right to target inputs on the left. Many columns can feed the same target; use labels to describe joins or transformations.")
    canvas_key = prefix + "canvas"

    def save_canvas():
        try:
            payload = st.session_state[canvas_key].get("edit")
            save_builder(store, w, BuilderDocument.model_validate(payload))
            st.session_state.pop(prefix + "canvas_error", None)
        except (ValueError, duckdb.Error, OSError) as exc:
            st.session_state[prefix + "canvas_error"] = "Canvas edit was not saved: " + str(exc)[:500]

    if error := st.session_state.pop(prefix + "canvas_error", ""):
        st.error(error)
    canvas(document, canvas_key, save_canvas, error)
    with st.expander("Create a table on the canvas"):
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
            if st.button("Add relationship"):
                payload = document.model_dump()
                payload["links"].append(BuilderLink(source_table=source_id, source_column=source_column,
                                                   target_table=target_id, target_column=target_column, label=label).model_dump())
                for index, t in enumerate(payload["tables"]):
                    if t["id"] in {source_id, target_id} and not t["position"]:
                        t["position"] = {"x": 60 + (index % 3) * 520, "y": 60 + (index // 3) * 320}
                commit(payload, "Relationship added.")

with st.expander("Export & restore builder"):
    st.caption("SVG and PNG buttons on the canvas export all placed tables. HTML exports an offline interactive presentation. CSV/Excel include every table and relationship. JSON preserves the complete editable builder.")
    format = st.selectbox("Builder export format", ["JSON", "HTML", "Excel", "CSV"], key=prefix + "export_format")
    if st.button("Prepare builder export", disabled=not document.tables):
        try:
            extension, mime = {"JSON": ("json", "application/json"), "HTML": ("html", "text/html"),
                               "Excel": ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"), "CSV": ("csv", "text/csv")}[format]
            content = document.model_dump_json(indent=2).encode() if format == "JSON" else builder_html(document) if format == "HTML" else export_tabular(document, extension)
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
