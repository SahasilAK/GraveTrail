"""Bounded schema-only imports. Uploaded code is never executed."""
from __future__ import annotations

import csv
import io
import json
import re
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

import sqlglot
import yaml
from sqlglot import exp

from dataforge.lineage_builder import BuilderColumn, BuilderDocument, BuilderTable

MAX_IMPORT_BYTES = 5 * 1024 * 1024


def _column(value: dict) -> BuilderColumn:
    return BuilderColumn(name=value.get("name") or value.get("column"),
                         data_type=str(value.get("data_type") or value.get("type") or ""),
                         comment=str(value.get("description") or value.get("comment") or ""))


def _structured(value: dict | list) -> list[BuilderTable]:
    if isinstance(value, dict) and "version" in value and "tables" in value and "links" in value:
        return BuilderDocument.model_validate(value).tables
    tables = []
    if isinstance(value, list):
        entries = value
    else:
        entries = list(value.get("tables", [])) + list(value.get("models", []))
        sources = value.get("sources", [])
        for source in sources if isinstance(sources, list) else []:
            for table in source.get("tables", []):
                namespace = source.get("schema") or source.get("name", "")
                namespace = ".".join(filter(None, [source.get("database"), namespace]))
                entries.append({**table, "name": ".".join(filter(None, [namespace, table.get("identifier") or table.get("name")]))})
        for collection in ("nodes", "sources"):
            records = value.get(collection, {})
            if not isinstance(records, dict):
                continue
            for node in records.values():
                if node.get("resource_type") not in (None, "model", "seed", "snapshot", "source"):
                    continue
                metadata = node.get("metadata", {})
                name = node.get("alias") or node.get("identifier") or node.get("name") or metadata.get("name")
                namespace = ".".join(filter(None, [node.get("database") or metadata.get("database"),
                                                   node.get("schema") or metadata.get("schema")]))
                entries.append({**node, "name": ".".join(filter(None, [namespace, name]))})
    for table in entries:
        columns = table.get("columns", [])
        if isinstance(columns, dict):
            columns = [{**c, "name": c.get("name", name)} for name, c in columns.items()]
        tables.append(BuilderTable(name=table.get("name") or table.get("table"),
                                  comment=str(table.get("description") or table.get("comment") or ""),
                                  role=table.get("role", "source"), columns=[_column(c) for c in columns]))
    return tables


def _sql(text: str, dialect: str | None) -> tuple[list[BuilderTable], list[str]]:
    tables, warnings = [], []
    for statement in sqlglot.parse(text, read=dialect or None):
        if not isinstance(statement, exp.Create) or not isinstance(statement.this, exp.Schema):
            if statement is not None:
                warnings.append("Skipped a statement without an explicit CREATE TABLE column schema.")
            continue
        schema = statement.this
        if not isinstance(schema.this, exp.Table):
            continue
        columns = []
        for column in schema.expressions:
            if isinstance(column, exp.ColumnDef):
                comment = next((c.kind.this for c in column.constraints if isinstance(c.kind, exp.CommentColumnConstraint)), None)
                columns.append(BuilderColumn(name=column.name, data_type=column.kind.sql(dialect=dialect or None) if column.kind else "",
                                             comment=comment.this if isinstance(comment, exp.Literal) else ""))
        tables.append(BuilderTable(name=".".join(part.name for part in schema.this.parts), columns=columns))
    return tables, warnings


def _sas(text: str) -> tuple[list[BuilderTable], list[str]]:
    from dataforge.models import statements
    from dataforge.parsers.sas import strip_comments

    tables, warnings = [], []
    name, columns, sql = None, [], None
    for statement, _, _ in statements(strip_comments(text), sas=True):
        if re.match(r"proc\s+sql\b", statement, re.I):
            sql = []
        elif sql is not None:
            if re.fullmatch(r"quit\s*;", statement, re.I):
                found, notes = _sql("\n".join(sql), None)
                tables.extend(found)
                warnings.extend(notes)
                sql = None
            else:
                sql.append(statement)
        elif match := re.fullmatch(r"data\s+([\w.]+)\s*;", statement, re.I):
            name, columns = match[1], []
        elif name and re.fullmatch(r"run\s*;", statement, re.I):
            if columns:
                tables.append(BuilderTable(name=name, columns=columns))
            else:
                warnings.append(f"No explicit LENGTH schema in SAS DATA {name}; inherited/runtime columns were skipped.")
            name, columns = None, []
        elif name and (match := re.fullmatch(r"length\s+([^;]+);", statement, re.I | re.S)):
            # shortcut: only explicit LENGTH groups; runtime/inherited SAS schemas require metadata exports.
            for group in re.finditer(r"((?:[A-Za-z_]\w*\s+)+)(\$?\s*\d+(?:\.\d+)?)", match[1]):
                for column in group[1].split():
                    columns.append(BuilderColumn(name=column, data_type=group[2].replace(" ", "")))
    warnings.append("SAS import reads PROC SQL DDL and explicit DATA/LENGTH declarations only; review inferred runtime schemas manually.")
    return tables, warnings


def _xml(text: str) -> tuple[list[BuilderTable], list[str]]:
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", text, re.I):
        raise ValueError("XML DTDs and entity declarations are not supported")
    root = ET.fromstring(text)
    tables = []
    for node in root.iter():
        kind = node.tag.rsplit("}", 1)[-1].upper()
        if kind not in {"SOURCE", "TARGET", "TRANSFORMATION"}:
            continue
        columns = [BuilderColumn(name=c.attrib.get("NAME"), data_type=c.attrib.get("DATATYPE", ""),
                                 comment=c.attrib.get("DESCRIPTION", "")) for c in node
                   if c.tag.rsplit("}", 1)[-1].upper() in {"SOURCEFIELD", "TARGETFIELD", "TRANSFORMFIELD"}]
        if columns:
            tables.append(BuilderTable(name=node.attrib.get("NAME"), columns=columns,
                                       role={"SOURCE": "source", "TARGET": "target", "TRANSFORMATION": "intermediate"}[kind]))
    return tables, ["XML import reads Informatica PowerCenter SOURCE, TARGET and TRANSFORMATION field definitions; mappings are not imported."]


def import_schema(filename: str, content: bytes, dialect: str | None = None) -> tuple[list[BuilderTable], list[str]]:
    """Read common explicit schema formats and report unsupported/partial content."""
    if len(content) > MAX_IMPORT_BYTES:
        raise ValueError("Schema import exceeds 5 MiB; split the file")
    try:
        text = content.decode("utf-8-sig")
        suffix = PurePosixPath(filename).suffix.lower()
        warnings = []
        if suffix in {".sql", ".ddl", ".hql"}:
            tables, warnings = _sql(text, dialect)
        elif suffix == ".sas":
            tables, warnings = _sas(text)
        elif suffix in {".json", ".yaml", ".yml"}:
            if suffix == ".json":
                value = json.loads(text)
            else:
                # Reject aliases before loading to avoid recursive/expanding YAML input.
                if any(isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)) for token in yaml.scan(text)):
                    raise ValueError("YAML aliases/anchors are not supported in schema imports")
                value = yaml.safe_load(text)
            if not isinstance(value, (dict, list)):
                raise ValueError("Expected a schema object or table list")
            tables = _structured(value)
        elif suffix in {".csv", ".tsv"}:
            grouped = {}
            for row in csv.DictReader(io.StringIO(text), delimiter="\t" if suffix == ".tsv" else ","):
                row = {k.strip().lower(): v for k, v in row.items() if k}
                if row.get("record_type", "schema") != "schema":
                    continue
                name = row.get("table") or row.get("table_name")
                column = row.get("column") or row.get("column_name")
                if not name:
                    raise ValueError("CSV requires table and column headers (optional data_type, comment, role)")
                table = grouped.setdefault(name, {"name": name, "role": row.get("role") or "source", "columns": []})
                if column:
                    table["columns"].append({**row, "name": column})
            tables = _structured(list(grouped.values()))
        elif suffix == ".xml":
            tables, warnings = _xml(text)
        else:
            raise ValueError("Unsupported schema format. Use SQL/DDL, SAS, dbt YAML/JSON, Informatica XML or CSV/TSV.")
        # Deduplicate repeated artifact definitions only when their schema agrees.
        unique = {}
        for table in tables:
            previous = unique.get(table.name.casefold())
            if previous and [(c.name, c.data_type) for c in previous.columns] != [(c.name, c.data_type) for c in table.columns]:
                raise ValueError(f"Conflicting declarations for {table.name}; import them separately and review")
            unique[table.name.casefold()] = table
        if not unique:
            raise ValueError("No explicit table schema found in this file")
        validated = BuilderDocument(tables=list(unique.values()))
        for table in validated.tables:
            if not table.columns:
                warnings.append(f"{table.name}: no columns declared; add columns in the schema editor.")
        return validated.tables, list(dict.fromkeys(warnings))
    except (UnicodeError, csv.Error, yaml.YAMLError, ET.ParseError, sqlglot.errors.SqlglotError, TypeError, AttributeError, KeyError, RecursionError) as exc:
        raise ValueError(f"Cannot read schema: {str(exc)[:300]}") from None
