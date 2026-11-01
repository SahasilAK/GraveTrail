"""Authored lineage documents, independent of analyzed source evidence."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from dataforge.datatypes import TYPE_CATALOG, format_data_type, type_entry
from dataforge.store import Store

SETTING = "lineage_builder"
WORKS_SETTING = "lineage_builder_works"
JOIN_TYPES = ["Inner join", "Left join", "Right join", "Full outer join", "Cross join", "Self join"]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class BuilderModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Position(BuilderModel):
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)


class BuilderColumn(BuilderModel):
    id: Name = Field(default_factory=lambda: uuid4().hex)
    name: Name
    data_type: str = Field(default="", max_length=300)
    comment: str = Field(default="", max_length=2000)


class TableSize(BuilderModel):
    width: float = Field(ge=320, le=1600, allow_inf_nan=False)
    height: float = Field(ge=98, le=30000, allow_inf_nan=False)


class BuilderFolder(BuilderModel):
    id: Name = Field(default_factory=lambda: uuid4().hex)
    name: Name


class BuilderTable(BuilderModel):
    id: Name = Field(default_factory=lambda: uuid4().hex)
    name: Name
    role: Literal["source", "intermediate", "target"] = "source"
    system: str = Field(default="", max_length=100)
    columns: list[BuilderColumn] = Field(default_factory=list, max_length=200)
    comment: str = Field(default="", max_length=2000)
    position: Position | None = None
    canvas_member: bool = False
    catalog_hidden: bool = False
    size: TableSize | None = None
    folder: Name | None = None

    @model_validator(mode="after")
    def unique_columns(self) -> BuilderTable:
        for values in ([c.id for c in self.columns], [c.name.casefold() for c in self.columns]):
            if len(set(values)) != len(values):
                raise ValueError("Column names and IDs must be unique within a table")
        if self.position is not None:
            object.__setattr__(self, "canvas_member", True)
        return self


class BuilderLink(BuilderModel):
    id: Name = Field(default_factory=lambda: uuid4().hex)
    source_table: Name
    source_column: Name
    target_table: Name
    target_column: Name
    label: str = Field(default="", max_length=500)
    kind: Literal["lineage", "join"] = "lineage"
    join_type: str = Field(default="", max_length=100)

    @model_validator(mode="after")
    def normalize_join(self) -> BuilderLink:
        object.__setattr__(self, "join_type", (self.join_type.strip() or "Inner join") if self.kind == "join" else "")
        return self


class BuilderDocument(BuilderModel):
    version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    tables: list[BuilderTable] = Field(default_factory=list, max_length=100)
    links: list[BuilderLink] = Field(default_factory=list, max_length=2000)
    folders: list[BuilderFolder] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def valid_graph(self) -> BuilderDocument:
        for values in ([t.id for t in self.tables], [t.name.casefold() for t in self.tables], [e.id for e in self.links],
                       [f.id for f in self.folders], [f.name.casefold() for f in self.folders]):
            if len(set(values)) != len(values):
                raise ValueError("Table/folder names, table/folder IDs and relationship IDs must be unique")
        folder_ids = {f.id for f in self.folders}
        if any(t.folder is not None and t.folder not in folder_ids for t in self.tables):
            raise ValueError("A table refers to a missing catalog folder")
        endpoints = {(t.id, c.id) for t in self.tables for c in t.columns}
        seen = set()
        for link in self.links:
            source = (link.source_table, link.source_column)
            target = (link.target_table, link.target_column)
            if source not in endpoints or target not in endpoints:
                raise ValueError("A relationship refers to a missing table or column")
            pair = tuple(sorted((source, target))) if link.kind == "join" else (source, target)
            identity = (link.kind, pair)
            if source == target or identity in seen:
                raise ValueError("A relationship must connect different columns and cannot be duplicated")
            seen.add(identity)
        return self


class BuilderWorkInfo(BuilderModel):
    id: Name = Field(default_factory=lambda: uuid4().hex)
    name: Name
    updated_at: str


class BuilderWork(BuilderWorkInfo):
    document: BuilderDocument


def list_builder_works(store: Store, workspace: str) -> list[BuilderWorkInfo]:
    return [BuilderWorkInfo.model_validate(value) for value in store.setting(workspace, WORKS_SETTING, [])]


def get_builder_work(store: Store, workspace: str, work_id: str) -> BuilderWork:
    value = store.setting(workspace, WORKS_SETTING + "_" + work_id, None)
    if value is None:
        raise ValueError("The saved work no longer exists. Reload the list.")
    return BuilderWork.model_validate(value)


def save_builder_work(store: Store, workspace: str, name: str, *, work_id: str | None = None,
                      document: BuilderDocument | None = None) -> BuilderWork:
    """Save a named editable snapshot, or explicitly update an existing one."""
    with store.transaction():
        works = list_builder_works(store, workspace)
        if work_id is not None and not any(w.id == work_id for w in works):
            raise ValueError("The saved work no longer exists. Reload the list.")
        work = BuilderWork(id=work_id or uuid4().hex, name=name,
                           updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           document=BuilderDocument.model_validate((document or load_builder(store, workspace)).model_dump()))
        if any(w.id != work.id and w.name.casefold() == work.name.casefold() for w in works):
            raise ValueError("A saved work with this name already exists. Choose another name or update that work.")
        if work_id is None and len(works) >= 100:
            raise ValueError("This workspace already has 100 saved works. Update an existing work instead.")
        works = [w for w in works if w.id != work.id] + [BuilderWorkInfo.model_validate(work.model_dump(exclude={"document"}))]
        store.set_setting(workspace, WORKS_SETTING + "_" + work.id, work.model_dump())
        store.set_setting(workspace, WORKS_SETTING, [w.model_dump() for w in works])
    return work


def load_builder_work(store: Store, workspace: str, work_id: str, *, expected_revision: int) -> BuilderDocument:
    """Replace the active document with a saved copy while retaining revision conflict checks."""
    work = get_builder_work(store, workspace, work_id)
    payload = work.document.model_dump()
    payload["revision"] = expected_revision
    return save_builder(store, workspace, BuilderDocument.model_validate(payload))


def load_builder(store: Store, workspace: str) -> BuilderDocument:
    """Read the saved catalog and canvas for one workspace."""
    return BuilderDocument.model_validate(store.setting(workspace, SETTING, {}))


def save_builder(store: Store, workspace: str, document: BuilderDocument) -> BuilderDocument:
    """Validate and save atomically; reject edits based on an older revision."""
    document = BuilderDocument.model_validate(document.model_dump())
    with store.transaction():
        previous = load_builder(store, workspace)
        if previous.revision != document.revision:
            raise ValueError("The builder changed in another session. Reload and try the edit again.")
        members = {t.id for t in previous.tables if t.canvas_member}
        for table in document.tables:
            if table.id in members:
                table.canvas_member = True
        document.revision += 1
        store.set_setting(workspace, SETTING, document.model_dump())
    return document


def schema_rows(document: BuilderDocument) -> list[dict]:
    return [{"table": t.name, "role": t.role, "system": t.system, "table_comment": t.comment,
             "column": c.name if c else "", "data_type": c.data_type if c else "",
             "comment": c.comment if c else ""}
            for t in document.tables for c in (t.columns or [None])]


def link_rows(document: BuilderDocument) -> list[dict]:
    tables = {t.id: t for t in document.tables}
    columns = {(t.id, c.id): c.name for t in document.tables for c in t.columns}
    return [{"source_table": tables[e.source_table].name,
             "source_column": columns[e.source_table, e.source_column],
             "target_table": tables[e.target_table].name,
             "target_column": columns[e.target_table, e.target_column], "label": e.label,
             "relationship_kind": e.kind, "join_type": e.join_type}
            for e in document.links]


def export_tabular(document: BuilderDocument, format: str, *, schema_only: bool = False) -> bytes:
    """Export the entire authored catalog and links; spreadsheet values stay literal."""
    schemas, links = schema_rows(document), link_rows(document)
    if format == "csv":
        output = io.StringIO(newline="")
        fields = ["table", "role", "system", "table_comment", "column", "data_type", "comment"] if schema_only else [
            "record_type", "table", "role", "system", "table_comment", "column", "data_type", "comment",
            "source_table", "source_column", "target_table", "target_column", "label", "relationship_kind", "join_type"]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for kind, rows in (("schema", schemas), ("relationship", links)):
            if schema_only and kind == "relationship":
                continue
            for row in rows:
                # CSV consumers can execute formula-looking cells on open.
                writer.writerow({**({} if schema_only else {"record_type": kind}),
                                 **{k: "'" + v if v.lstrip().startswith(("=", "+", "-", "@")) else v for k, v in row.items()}})
        return output.getvalue().encode("utf-8-sig")
    if format != "xlsx":
        raise ValueError("Choose CSV or Excel")
    import xlsxwriter

    output = io.BytesIO()
    with xlsxwriter.Workbook(output, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False}) as book:
        for title, rows, fields in (
            ("Schema", schemas, ["table", "role", "system", "table_comment", "column", "data_type", "comment"]),
            ("Lineage", links, ["source_table", "source_column", "target_table", "target_column", "label", "relationship_kind", "join_type"]),
        ):
            if schema_only and title == "Lineage":
                continue
            sheet = book.add_worksheet(title)
            sheet.write_row(0, 0, fields)
            for index, row in enumerate(rows, 1):
                sheet.write_row(index, 0, [row[f] for f in fields])
            sheet.freeze_panes(1, 0)
            sheet.set_column(0, len(fields)-1, 26)
            sheet.autofilter(0, 0, len(rows), len(fields)-1)
    return output.getvalue()


def export_schemas(document: BuilderDocument, format: str, *, table_ids: list[str] | None = None,
                   role: str | None = None) -> bytes:
    """Export selected schema definitions without canvas state or relationships."""
    tables = [t for t in document.tables if (table_ids is None or t.id in table_ids) and (role is None or t.role == role)]
    if not tables:
        raise ValueError("Select at least one table to export")
    subset = BuilderDocument(tables=tables, folders=document.folders)
    if format in ("csv", "xlsx"):
        return export_tabular(subset, format, schema_only=True)
    payload = {"tables": [t.model_dump(include={"name", "role", "system", "comment", "columns"},
                                        exclude={"columns": {"__all__": {"id"}}}) for t in tables]}
    if format == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2).encode()
    if format == "yaml":
        import yaml
        return yaml.safe_dump(payload, allow_unicode=True, sort_keys=False).encode()
    if format == "sql":
        import sqlglot
        from sqlglot import exp
        from sqlglot.errors import ParseError

        dialects = {"BigQuery": "bigquery", "Oracle": "oracle", "SQL Server": "tsql", "Azure Synapse": "tsql",
                    "Databricks": "databricks", "Redshift": "redshift", "Snowflake": "snowflake",
                    "PostgreSQL": "postgres", "MySQL": "mysql", "MariaDB": "mysql", "SQLite": "sqlite",
                    "DuckDB": "duckdb", "Spark SQL": "spark", "Hive": "hive",
                    "Teradata": "teradata", "Trino": "trino", "ClickHouse": "clickhouse", "Presto": "presto"}
        statements = []
        for table in tables:
            dialect = dialects.get(table.system)

            def quote(name: str) -> str:
                return exp.to_identifier(name, quoted=True).sql(dialect=dialect)

            if not table.columns or any(not c.data_type.strip() for c in table.columns):
                raise ValueError(f"SQL DDL needs a datatype for every column in {table.name}. Use JSON, YAML, CSV or Excel for incomplete schemas.")
            columns = []
            for column in table.columns:
                try:
                    datatype = column.data_type.strip()
                    known = datatype.casefold() in {kind.casefold() for kind in TYPE_CATALOG.get(table.system, [])}
                    # Parse the whole definition: DataType.build alone silently accepts trailing SQL.
                    # Catalog constants also cover vendor types the installed parser cannot read.
                    parsed = sqlglot.parse("CREATE TABLE __schema_export__ (__column__ " + ("INT" if known else datatype) + ")", read=dialect)
                    statement = parsed[0] if len(parsed) == 1 else None
                    schema = statement.this if isinstance(statement, exp.Create) else None
                    definition = schema.expressions[0] if isinstance(schema, exp.Schema) and len(schema.expressions) == 1 else None
                    if (not isinstance(definition, exp.ColumnDef) or not isinstance(definition.kind, exp.DataType)
                            or any(v for k, v in definition.args.items() if k not in ("this", "kind"))
                            or any(v for k, v in statement.args.items() if k not in ("this", "kind"))
                            or any(n.comments for n in statement.walk())):
                        raise ValueError("Enter a datatype only")
                except (ValueError, TypeError, ParseError) as exc:
                    raise ValueError(f"Cannot export SQL datatype for {table.name}.{column.name}: {exc}") from None
                comment = "".join("  -- " + line + "\n" for line in column.comment.splitlines())
                columns.append(comment + f"  {quote(column.name)} {column.data_type.strip()}")
            comment = "".join("-- " + line + "\n" for line in table.comment.splitlines())
            statements.append(comment + "CREATE TABLE " + ".".join(quote(part) for part in table.name.split(".")) + " (\n" + ",\n".join(columns) + "\n);")
        return ("\n\n".join(statements) + "\n").encode()
    raise ValueError("Choose JSON, YAML, SQL, CSV or Excel")


def columns_from_rows(rows: list[dict], system: str, *, existing: list[BuilderColumn] | None = None) -> list[BuilderColumn]:
    """Shared native-grid and canvas-dialog entry, with stable IDs for existing columns."""
    if not isinstance(rows, list) or len(rows) > 200 or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Enter at most 200 column rows")
    columns = []
    originals = {c.id: c for c in existing or []}
    for row in rows:
        if not any(row.get(k) for k in ("name", "data_type", "comment", "precision", "scale")):
            continue
        try:
            original = originals.get(row.get("id"))
            unchanged_type = original and all(
                (row.get(key) or "") == value if isinstance(value, str) else row.get(key) == value
                for key, value in type_entry(original.data_type, system).items())
            # Editing a name/comment must not reinterpret an imported unconstrained or vendor-specific type.
            data_type = original.data_type if unchanged_type else format_data_type(
                system, row.get("data_type") or "", row.get("precision"), row.get("scale"))
            columns.append(BuilderColumn(id=row.get("id") or uuid4().hex, name=row.get("name") or "",
                                         data_type=data_type, comment=row.get("comment") or ""))
        except ValueError as exc:
            raise ValueError(f"Column {str(row.get('name') or len(columns)+1)[:100]}: {exc}") from None
    return columns
