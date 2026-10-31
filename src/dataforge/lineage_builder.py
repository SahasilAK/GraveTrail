"""Authored lineage documents, independent of analyzed source evidence."""
from __future__ import annotations

import csv
import io
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from dataforge.store import Store

SETTING = "lineage_builder"
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class BuilderModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Position(BuilderModel):
    x: float = Field(ge=0, le=12000, allow_inf_nan=False)
    y: float = Field(ge=0, le=12000, allow_inf_nan=False)


class BuilderColumn(BuilderModel):
    id: Name = Field(default_factory=lambda: uuid4().hex)
    name: Name
    data_type: str = Field(default="", max_length=300)
    comment: str = Field(default="", max_length=2000)


class BuilderTable(BuilderModel):
    id: Name = Field(default_factory=lambda: uuid4().hex)
    name: Name
    role: Literal["source", "intermediate", "target"] = "source"
    columns: list[BuilderColumn] = Field(default_factory=list, max_length=200)
    comment: str = Field(default="", max_length=2000)
    position: Position | None = None

    @model_validator(mode="after")
    def unique_columns(self) -> BuilderTable:
        for values in ([c.id for c in self.columns], [c.name.casefold() for c in self.columns]):
            if len(set(values)) != len(values):
                raise ValueError("Column names and IDs must be unique within a table")
        return self


class BuilderLink(BuilderModel):
    id: Name = Field(default_factory=lambda: uuid4().hex)
    source_table: Name
    source_column: Name
    target_table: Name
    target_column: Name
    label: str = Field(default="", max_length=500)


class BuilderDocument(BuilderModel):
    version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    tables: list[BuilderTable] = Field(default_factory=list, max_length=100)
    links: list[BuilderLink] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="after")
    def valid_graph(self) -> BuilderDocument:
        for values in ([t.id for t in self.tables], [t.name.casefold() for t in self.tables], [e.id for e in self.links]):
            if len(set(values)) != len(values):
                raise ValueError("Table names, table IDs and relationship IDs must be unique")
        endpoints = {(t.id, c.id) for t in self.tables for c in t.columns}
        seen = set()
        for link in self.links:
            source = (link.source_table, link.source_column)
            target = (link.target_table, link.target_column)
            if source not in endpoints or target not in endpoints:
                raise ValueError("A relationship refers to a missing table or column")
            if source == target or (source, target) in seen:
                raise ValueError("A relationship must connect different columns and cannot be duplicated")
            seen.add((source, target))
        return self


def load_builder(store: Store, workspace: str) -> BuilderDocument:
    """Read the saved catalog and canvas for one workspace."""
    return BuilderDocument.model_validate(store.setting(workspace, SETTING, {}))


def save_builder(store: Store, workspace: str, document: BuilderDocument) -> BuilderDocument:
    """Validate and save atomically; reject edits based on an older revision."""
    document = BuilderDocument.model_validate(document.model_dump())
    with store.transaction():
        if load_builder(store, workspace).revision != document.revision:
            raise ValueError("The builder changed in another session. Reload and try the edit again.")
        document.revision += 1
        store.set_setting(workspace, SETTING, document.model_dump())
    return document


def schema_rows(document: BuilderDocument) -> list[dict]:
    return [{"table": t.name, "role": t.role, "table_comment": t.comment,
             "column": c.name if c else "", "data_type": c.data_type if c else "",
             "comment": c.comment if c else ""}
            for t in document.tables for c in (t.columns or [None])]


def link_rows(document: BuilderDocument) -> list[dict]:
    tables = {t.id: t for t in document.tables}
    columns = {(t.id, c.id): c.name for t in document.tables for c in t.columns}
    return [{"source_table": tables[e.source_table].name,
             "source_column": columns[e.source_table, e.source_column],
             "target_table": tables[e.target_table].name,
             "target_column": columns[e.target_table, e.target_column], "label": e.label}
            for e in document.links]


def export_tabular(document: BuilderDocument, format: str) -> bytes:
    """Export the entire authored catalog and links; spreadsheet values stay literal."""
    schemas, links = schema_rows(document), link_rows(document)
    if format == "csv":
        output = io.StringIO(newline="")
        fields = ["record_type", "table", "role", "table_comment", "column", "data_type", "comment",
                  "source_table", "source_column", "target_table", "target_column", "label"]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for kind, rows in (("schema", schemas), ("relationship", links)):
            for row in rows:
                # CSV consumers can execute formula-looking cells on open.
                writer.writerow({"record_type": kind, **{k: "'" + v if v.lstrip().startswith(("=", "+", "-", "@")) else v
                                                         for k, v in row.items()}})
        return output.getvalue().encode("utf-8-sig")
    if format != "xlsx":
        raise ValueError("Choose CSV or Excel")
    import xlsxwriter

    output = io.BytesIO()
    with xlsxwriter.Workbook(output, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False}) as book:
        for title, rows, fields in (
            ("Schema", schemas, ["table", "role", "table_comment", "column", "data_type", "comment"]),
            ("Lineage", links, ["source_table", "source_column", "target_table", "target_column", "label"]),
        ):
            sheet = book.add_worksheet(title)
            sheet.write_row(0, 0, fields)
            for index, row in enumerate(rows, 1):
                sheet.write_row(index, 0, [row[f] for f in fields])
            sheet.freeze_panes(1, 0)
            sheet.set_column(0, len(fields)-1, 26)
            sheet.autofilter(0, 0, len(rows), len(fields)-1)
    return output.getvalue()
