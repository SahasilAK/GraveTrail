"""Plan source regions, emit dbt candidates and inspect the resulting SQL independently."""
from __future__ import annotations

import hashlib
import json
import re
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath

import networkx as nx
import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.scope import traverse_scope
from sqlglot.tokens import TokenType

from dataforge.dbt.resources import inherited_config
from dataforge.dbt.yaml import read_project_paths
from dataforge.migration.sources import (
    SECRET_FILE,
    SQL_BATCH_SEPARATOR,
    dbt_model_name,
    declaration,
    grouping_key_errors,
    guarded_table_drop,
    project_yaml,
    relation,
    sas_inline_evidence,
    sas_units,
    script_writes,
    sql_regions,
    sql_unit,
    sqlite_literal_table,
    temporary_relation,
    ungrouped_columns,
)
from dataforge.migration.targets import warehouse
from dataforge.parsers.sas import parse_sas
from dataforge.parsers.sql import parse_sql

NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]{0,127}\Z")
SIMPLE_SQL_NAME = r'(?:[a-z_][a-z_0-9]*|"[a-z_][a-z_0-9]*")'
SIMPLE_SQL_RELATION = re.compile(rf"{SIMPLE_SQL_NAME}(?:\.{SIMPLE_SQL_NAME}){{0,2}}\Z")
RESERVED_PATH = re.compile(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", re.I)
TEMPLATE = re.compile(r"{{\s*(.*?)\s*}}", re.S)
CALL = re.compile(r"""(ref|source)\(\s*(['"])([A-Za-z_][\w]{0,127})\2(?:\s*,\s*(['"])([A-Za-z_][\w]{0,127})\4)?\s*\)""")
CONFIG = re.compile(r"config\((.*)\)", re.S)
CONFIG_ARG = re.compile(r"""\s*(materialized|alias)\s*=\s*(['"])([A-Za-z_][A-Za-z_0-9]{0,127})\2\s*""")
MARKER = "__migration_ref_"
MAX_ARTIFACT = 1024 * 1024
MAX_PROJECT = 100 * MAX_ARTIFACT
MAX_REGIONS = 20_000
VERSION = 10
DIALECT_ERRORS = (SqlglotError, ValueError, RecursionError, TypeError, KeyError, AttributeError)
UNSAFE_FUNCTIONS = frozenset({"java_method", "reflect", "read_files", "read_csv", "read_parquet", "http_get"})

# Structural whitelist keeps unqualified functions, syntax and semantics visible.
QUALIFIED = frozenset("""
    Select Union With CTE Table TableAlias Identifier From Join Where Group Having Distinct
    Column Alias Star Literal Null Boolean Paren And Or Not EQ NEQ GT GTE LT LTE Is In Between
    Add Sub Mul Div Mod Neg Cast DataType DataTypeParam Case If Coalesce Count Sum Min Max Avg
    Subquery
""".split())


def digest(value):
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def fingerprint(value):
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))


def source_review_context(plan, settings):
    return fingerprint([plan, {key: value for key, value in settings.items()
                               if key not in {"ai_source_reviews", "validation_rules"}}])


def related_models(plan, models):
    related = set(models)
    pending = list(related)
    while pending:
        for parent in plan["outputs"].get(pending.pop(), {}).get("inputs", ()):
            if parent in plan["outputs"] and parent not in related:
                related.add(parent)
                pending.append(parent)
    return related


def source_review_key(context, plan, files, models):
    return fingerprint([context, {model: files.get(model, {}).get("hash") for model in related_models(plan, models)}])


def source_review_status(revision):
    receipts = revision["settings"].get("ai_source_reviews", {})
    if not receipts:
        return {}
    plan = revision["plan"]
    context = source_review_context(plan, revision["settings"])
    return {source: "stale" if not receipt.get("key") or receipt["key"] != source_review_key(
        context, plan, revision["files"], receipt.get("models", receipt["files"]))
        else "unresolved" if not receipt["files"] or receipt["unresolved_outputs"] else "applied"
        for source, receipt in receipts.items()}


def slug(value):
    name = re.sub(r"[^a-z0-9_]+", "_", value.casefold()).strip("_")[:84] or "model"
    return "m_" + name if name[0].isdigit() else name


def unsafe_query(query):
    return bool(query.find(exp.Into, exp.Command, exp.DML, exp.DDL, exp.TableSample, exp.Lock)) or any(
        node.name.casefold() in UNSAFE_FUNCTIONS for node in query.find_all(exp.Anonymous)
    )


def output_name(query):
    if isinstance(query, exp.Alias):
        return query.alias
    if isinstance(query, exp.Column):
        return query.name
    return ""  # Expressions without stable aliases require review.


SQL_ROW_OPERATIONS = {
    "row filters": exp.Where, "join conditions": exp.Join, "grouping": exp.Group,
    "group filters": exp.Having, "window expressions": exp.Window, "row limits": exp.Limit,
    "duplicate elimination": exp.Distinct,
}

SQL_COMPARISONS = {exp.EQ: "=", exp.NEQ: "!=", exp.GT: ">", exp.GTE: ">=", exp.LT: "<", exp.LTE: "<="}


def _conjuncts(expression):
    expression = expression.unnest()
    return expression.flatten() if isinstance(expression, exp.And) else (expression,)


def _sql_predicate_facts(query):
    facts = []
    for clause in query.find_all(exp.Where, exp.Having, exp.Qualify):
        for test in _conjuncts(clause.this):
            negated = isinstance(test, exp.Not)
            test = test.this.unnest() if negated else test
            operator = SQL_COMPARISONS.get(type(test))
            if not operator:
                continue
            column, literal = test.this, test.expression
            if isinstance(literal, exp.Column):
                column, literal = literal, column
                operator = operator.translate(str.maketrans("<>", "><"))
            if isinstance(column, exp.Column) and (
                isinstance(literal, (exp.Literal, exp.Boolean)) or
                isinstance(literal, exp.Neg) and isinstance(literal.this, exp.Literal)
            ):
                facts.append(fingerprint([column.name.casefold(), operator, literal.sql(), negated]))
    return sorted(facts)


def _sql_join_facts(query):
    facts = []
    for join in query.find_all(exp.Join):
        condition = join.args.get("on")
        if not isinstance(join.this, exp.Table) or condition is None:
            continue
        keys = sorted(sorted((item.this.name.casefold(), item.expression.name.casefold()))
                      for item in _conjuncts(condition) if isinstance(item, exp.EQ)
                      and isinstance(item.this, exp.Column) and isinstance(item.expression, exp.Column))
        if keys:
            facts.append(fingerprint([join.side or join.kind or "INNER", keys]))
    return sorted(facts)


def _sql_ranking_facts(query):
    facts = []
    for window in query.find_all(exp.Window):
        if not isinstance(window.this, (exp.RowNumber, exp.Rank, exp.DenseRank)):
            continue
        partition = window.args.get("partition_by", ())
        order = window.args.get("order")
        order_by = order.expressions if order else []
        if (all(isinstance(column, exp.Column) and not column.is_star for column in partition)
                and all(isinstance(item.this, exp.Column) and not item.this.is_star for item in order_by)):
            facts.append(fingerprint([window.this.key, sorted(column.name.casefold() for column in partition),
                                      [(item.this.name.casefold(), bool(item.args.get("desc"))) for item in order_by]]))
    return sorted(facts)


def _sql_query_evidence(query, target):
    """Record checkable SQL behavior without claiming that similar ASTs are equivalent."""
    operations = sorted(name for name, kind in SQL_ROW_OPERATIONS.items() if query.find(kind))
    filters = sorted({column.name.casefold() for where in query.find_all(exp.Where, exp.Having, exp.Qualify)
                      for column in where.find_all(exp.Column)})
    union_all = sum(node.args.get("distinct") is False for node in query.find_all(exp.Union))
    literal_tables = []
    for values in query.find_all(exp.Values):
        rows = values.expressions
        if rows and all(isinstance(row, exp.Tuple) and all(
            isinstance(cell, (exp.Literal, exp.Null, exp.Boolean, exp.Neg)) and not cell.find(exp.Column)
            for cell in row.expressions) for row in rows):
            literal_tables.append(fingerprint(sorted(row.sql() for row in rows)))
    casts = {}
    if isinstance(query, exp.Select):
        for item in query.selects:
            if isinstance(item, exp.Alias) and isinstance(item.this, exp.Cast):
                if mapped := target.map_type(item.this.to.sql(dialect=target.dialect)):
                    casts[item.alias.casefold()] = mapped
    return {"operations": operations, "filter_columns": filters, "union_all": union_all,
            "literal_tables": sorted(literal_tables), "casts": casts,
            "predicate values or operators": _sql_predicate_facts(query), "join types or keys": _sql_join_facts(query),
            "ranking keys or sort direction": _sql_ranking_facts(query)}


def dbt_config(values):
    if not isinstance(values, dict) or set(values) - {"materialized", "alias", "enabled", "tags"}:
        raise ValueError("Review unsupported dbt configuration.")
    if values.get("materialized", "view") not in {"table", "view", "ephemeral"}:
        raise ValueError("Review unsupported dbt materialization.")
    if "alias" in values and (not isinstance(values["alias"], str) or not NAME.fullmatch(values["alias"])):
        raise ValueError("Resolve the dbt alias to a literal identifier.")
    if "enabled" in values and type(values["enabled"]) is not bool:
        raise ValueError("Resolve the dbt model enabled flag.")
    if "tags" in values and (not isinstance(values["tags"], list)
                             or any(not isinstance(tag, str) or not NAME.fullmatch(tag) for tag in values["tags"])):
        raise ValueError("Review dbt tags and their selection semantics.")
    return values


def inspect_sql(text, dialect, *, wrappers=(), guarded_drop=None):
    """Decode only application-allowlisted template calls into inert parser tokens."""
    if MARKER in text:
        raise ValueError("Reserved migration parser token")
    refs = {}
    configs = []

    def replace(match):
        body = match[1]
        padding = "\n" * match[0].count("\n")
        if config := CONFIG.fullmatch(body):
            value = {}
            for argument in config[1].split(","):
                parsed = CONFIG_ARG.fullmatch(argument)
                if not parsed or parsed[1] in value:
                    raise ValueError("Nonliteral or unsupported inline dbt configuration")
                value[parsed[1]] = parsed[3]
            configs.append(dbt_config(value))
            return padding
        call = CALL.fullmatch(body)
        if not call or (call[1] == "source" and not call[5]):
            raise ValueError("Unresolved or unsafe dbt template call")
        marker = f"{MARKER}{len(refs)}__"
        refs[marker] = (call[1], call[3], call[5])
        return marker + padding

    sql = TEMPLATE.sub(replace, text)
    if len(configs) > 1 or any(marker in sql for marker in ("{{", "{%", "{#", "}}", "%}", "#}")):
        raise ValueError("Unresolved or unsafe dbt template syntax")
    if dialect == "databricks":
        # SQLGlot tolerates separators that Databricks rejects.
        closing = {TokenType.FROM, TokenType.WHERE, TokenType.GROUP_BY, TokenType.HAVING, TokenType.QUALIFY,
                   TokenType.ORDER_BY, TokenType.LIMIT, TokenType.R_PAREN, TokenType.SEMICOLON, TokenType.UNION}
        kinds = [token.token_type for token in sqlglot.tokenize(sql, read=dialect)]
        if any(a == TokenType.COMMA and b in closing for a, b in zip(kinds, [*kinds[1:], TokenType.SEMICOLON])):
            raise ValueError("Trailing comma in Databricks query")
    paired = None
    if guarded_drop:
        statements = [(start, end) for start, end, _ in sql_regions(sql, dialect) if sql[start:end].strip()]
        if len(statements) == 2 and guarded_table_drop(sql[:statements[0][1]], dialect) == guarded_drop:
            paired = guarded_drop
            sql = sql[statements[1][0]:]
    query, name, kind, gap = sql_unit(sql, dialect)
    if query is None or gap or (paired and name != paired) or (name and (name, kind) not in wrappers):
        raise ValueError("Expected one read-only SELECT or UNION query")
    if any(not select.expressions for select in query.find_all(exp.Select)):
        raise ValueError("Every SELECT needs a projection")
    if dialect == "databricks":
        for window in query.find_all(exp.Window):
            parent = window.parent
            while parent is not None and not isinstance(parent, exp.Select):
                if isinstance(parent, (exp.Where, exp.Join, exp.Group, exp.Having)):
                    raise ValueError("Window filters need QUALIFY or an outer query in Databricks")
                parent = parent.parent
    tables = query_tables(query)
    seen = {table.name for table in tables}
    if refs.keys() - seen or any(table.name in refs and len(table.parts) != 1 for table in tables):
        raise ValueError("References must appear as standalone table inputs")
    return query, tables, refs, configs[0] if configs else None


def _scope_inputs(scope):
    """Include relations used as filters by SEMI and ANTI joins."""
    inputs = {}
    for alias, node in scope.references:
        if alias in inputs:
            raise ValueError(f"Alias already used: {alias}")
        if alias in scope.sources:
            inputs[alias] = (node, scope.sources[alias])
    return inputs


def query_tables(query):
    tables = []
    for scope in traverse_scope(query):
        for node, source in _scope_inputs(scope).values():
            if isinstance(source, exp.Table):
                relation(source)
                tables.append(node)
    if not tables and list(query.find_all(exp.Table)) and not list(query.find_all(exp.CTE)):
        raise ValueError("Unresolved SQL table expression")
    return tables


def _replace_input(table, columns, token):
    temporary = temporary_relation(relation(table))
    unaliased = not table.alias
    name = exp.to_identifier(table.name, quoted=table.this.quoted) if temporary else table.this.copy()
    for column in columns:
        qualifier = column.args.get("table")
        if temporary and qualifier is not None and qualifier.name.lstrip("#").casefold() == table.alias_or_name.casefold():
            column.set("table", exp.to_identifier(table.alias_or_name, quoted=name.quoted))
        if (column.table == table.alias_or_name and (column.db or column.catalog)
                and (not column.db or column.db == table.db)
                and (not column.catalog or column.catalog == table.catalog)):
            column.set("db", None)
            column.set("catalog", None)
    table.set("catalog", None)
    table.set("db", None)
    table.set("this", exp.to_identifier(token))
    if unaliased:
        table.set("alias", exp.TableAlias(this=name))


def normalize_proposal(sql, target, wrappers, bindings, *, guarded_drop=None):
    """Remove a matching simple wrapper and bind only exact, unambiguous planned inputs."""
    try:
        try:
            query, _, refs, config = inspect_sql(sql, target.dialect)
            changed = False
        except DIALECT_ERRORS:
            query, _, refs, config = inspect_sql(sql, target.dialect, wrappers=wrappers, guarded_drop=guarded_drop)
            changed = True
        if unsafe_query(query):
            return sql
        templates = {marker: "{{ " + kind + "(" + ", ".join(repr(arg) for arg in (name, other) if arg) + ") }}"
                     for marker, (kind, name, other) in refs.items()}
        for scope in traverse_scope(query):
            for table, source in _scope_inputs(scope).values():
                if not isinstance(source, exp.Table) or table.name in refs:
                    continue
                if call := bindings.get(relation(table)):
                    token = f"{MARKER}{len(templates)}__"
                    templates[token] = call
                    _replace_input(table, scope.columns, token)
                    changed = True
        if not changed:
            return sql
        rendered = target.emit_sql(query)
        rendered = re.sub(rf"{MARKER}\d+__", lambda match: templates[match[0]], rendered)
        if config:
            rendered = "{{ config(" + ", ".join(f"{key}={value!r}" for key, value in config.items()) + ") }}\n" + rendered
        inspect_sql(rendered, target.dialect)
        return rendered + "\n"
    except DIALECT_ERRORS:
        return sql


def inline_reference(evidence, target):
    """Render the supported literal SAS layout as an optional typed reference."""
    columns = evidence["columns"]
    rows = []
    for row in evidence["rows"]:
        values = [exp.cast(exp.Literal.number(value) if kind == "DOUBLE" else exp.Literal.string(value),
                           kind, dialect=target.dialect) for value, kind in zip(row, columns.values())]
        rows.append(exp.Tuple(expressions=values))
    alias = exp.TableAlias(this=exp.to_identifier("seed_rows"), columns=[exp.to_identifier(name) for name in columns])
    return target.emit_sql(exp.select(*columns).from_(exp.Values(expressions=rows, alias=alias))) + "\n"


def _matches_inline_rows(query, evidence):
    source = query.args.get("from_")
    values = source.this if source else None
    columns = evidence["columns"]
    if (not isinstance(query, exp.Select) or not isinstance(values, exp.Values)
            or any(value for key, value in query.args.items() if key not in {"from_", "expressions"})
            or list(values.alias_column_names) != list(columns)
            or any(not isinstance(item, exp.Column) or item.name != name
                   for item, name in zip(query.selects, columns, strict=False))
            or len(query.selects) != len(columns)):
        return False
    actual = []
    try:
        for row in values.expressions:
            if len(row.expressions) != len(columns):
                return False
            cells = []
            for value, kind in zip(row.expressions, columns.values()):
                if isinstance(value, exp.Cast):
                    if value.to.sql(dialect="databricks").upper() != kind:
                        return False
                    value = value.this
                elif kind != "STRING":
                    return False
                if not isinstance(value, exp.Literal):
                    if kind != "DOUBLE" or not isinstance(value, exp.Neg) or not isinstance(value.this, exp.Literal):
                        return False
                    value = exp.Literal.number("-" + value.this.this)
                if value.is_string != (kind != "DOUBLE"):
                    return False
                cells.append(Decimal(value.this) if kind == "DOUBLE" else value.this.replace("T", " ", 1)
                             if kind == "TIMESTAMP_NTZ" else value.this)
            actual.append(tuple(cells))
    except InvalidOperation:
        return False
    expected = [tuple(Decimal(value) if kind == "DOUBLE" else value
                      for value, kind in zip(row, columns.values())) for row in evidence["rows"]]
    return Counter(actual) == Counter(expected)


def _physical_input(parts, logical, physical):
    catalog, schema, name = ([None, None] + parts)[-3:]
    source_id = slug(logical) + "_" + digest(logical)[:8]
    group = "legacy_" + digest(logical)[:8]
    key = f"source:{group}.{source_id}"
    physical.setdefault(key, {
        "group": group, "name": source_id, "identifier": name,
        "catalog": catalog, "schema": schema, "relation": logical,
    })
    return key, "{{ source('" + group + "', '" + source_id + "') }}"


def _dbt_metadata(snapshot):
    metadata = {"sources": {}, "columns": {}, "docs": {}, "errors": {}, "project": None,
                "config": {}, "model_config": {}, "paths": {}, "root": None}
    projects = [s for s in snapshot["sources"] if s["kind"] == "dbt" and s.get("role") == "project"
                and "text" in s]
    for source in snapshot["sources"]:
        if (source["kind"] != "dbt" or "text" not in source
                or not source["path"].lower().endswith((".yaml", ".yml"))):
            continue
        try:
            data = project_yaml(source["text"])
            if source in projects:
                safe = {"name", "version", "config-version", "profile", "model-paths", "macro-paths",
                        "test-paths", "seed-paths", "snapshot-paths", "docs-paths", "analysis-paths",
                        "target-path", "clean-targets", "require-dbt-version", "models"}
                if len(projects) != 1 or set(data) - safe:
                    raise ValueError("Review project configuration, inheritance or multiple packages.")
                if not NAME.fullmatch(data.get("name", "")):
                    raise ValueError("Invalid dbt project identity")
                def validate_tree(tree, depth=0):
                    if not isinstance(tree, dict) or depth > 32:
                        raise ValueError("Review nested dbt configuration.")
                    dbt_config({key[1:]: value for key, value in tree.items() if key.startswith("+")})
                    for key, value in tree.items():
                        if not key.startswith("+"):
                            validate_tree(value, depth + 1)
                validate_tree(data.get("models", {}))
                metadata.update(project=data["name"], config=data, paths=read_project_paths(source["text"]),
                                root=str(PurePosixPath(source["path"]).parent))
            else:
                if set(data) - {"version", "models", "sources"}:
                    raise ValueError("Review dbt tests, exposures, configurations or other resources.")
                for entry in data.get("models", []):
                    if set(entry) - {"name", "description", "columns", "config"}:
                        raise ValueError("Review model versions, configuration or test declarations.")
                    key = entry["name"]
                    if key in metadata["model_config"]:
                        raise ValueError("Duplicate dbt model declaration.")
                    metadata["model_config"][key] = dbt_config(entry.get("config", {}))
                    _dbt_columns(entry, key, metadata)
                for entry in data.get("sources", []):
                    if (set(entry) - {"name", "database", "schema", "description", "tables"}
                            or not NAME.fullmatch(entry["name"])):
                        raise ValueError("Review source configuration.")
                    for table in entry["tables"]:
                        if set(table) - {"name", "identifier", "description", "columns"} or not NAME.fullmatch(table["name"]):
                            raise ValueError("Review table declarations and tests.")
                        schema, catalog = entry.get("schema"), entry.get("database")
                        identifier = table.get("identifier", table["name"])
                        if not all(isinstance(x, str) and x and len(x) <= 128
                                   for x in (schema, catalog, identifier)):
                            raise ValueError("Confirm the source catalog, schema and identifier explicitly.")
                        key = "source:" + entry["name"] + "." + table["name"]
                        if key in metadata["sources"]:
                            raise ValueError("Duplicate dbt source declaration")
                        metadata["sources"][key] = {
                            "group": entry["name"], "name": table["name"], "identifier": identifier,
                            "schema": schema, "catalog": catalog,
                        }
                        _dbt_columns(table, key, metadata)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            metadata["errors"][source["id"]] = "Review unsupported or malformed dbt project metadata."
            if isinstance(exc, ValueError) and str(exc).startswith(("Review ", "Confirm ", "Duplicate ")):
                metadata["errors"][source["id"]] = str(exc)
    return metadata


def _dbt_columns(entry, key, metadata):
    metadata["docs"][key] = str(entry.get("description", ""))
    for column in entry.get("columns", []):
        if set(column) - {"name", "data_type", "description"}:
            raise ValueError("Review dbt column constraints and tests.")
        name = column["name"]
        if not isinstance(name, str) or not isinstance(column.get("data_type", ""), str):
            raise ValueError("Invalid column declaration")
        metadata["columns"].setdefault(key, {})[name] = column.get("data_type", "")


def _paired_sql(text, following, dialect):
    """Recognize adjacent operations that describe one relational dbt output."""
    if dropped := guarded_table_drop(text, dialect):
        query, name, materialization, gap = sql_unit(following, dialect, guarded_drop=dropped)
        if (query is not None and name == dropped and materialization in {"table", "ephemeral"}
                and not unsafe_query(query)
                and not any(table.name.casefold() == dropped.rsplit(".", 1)[-1].strip('"').casefold()
                            for table in query_tables(query))):
            note = "Confirm that dbt replacement preserves the original guarded DROP and CREATE lifecycle."
            if materialization == "table":
                query.meta["migration_guarded_drop"] = dropped
            return query, name, materialization, " ".join(filter(None, (gap, note)))
    if dialect == "sqlite" and re.search(r"\bcreate\s+table\b", text, re.I) and re.search(r"\binsert\s+into\b", following, re.I):
        create, insert = (sqlglot.parse(statement, read=dialect) for statement in (text, following))
        if len(create) == len(insert) == 1 and (seed := sqlite_literal_table(create[0], insert[0])):
            query, name = seed
            return query, name, "table", ("Review SQLite initialization and source key/null constraints. "
                                          "This dbt output represents the declared literal rows and column types.")
    return None


def _inventory_sql(source, declarations):
    text, dialect = source["text"], source.get("dialect", "")
    spans = iter(sql_regions(text, dialect))
    current = next(spans, None)
    while current:
        (start, end, compound), current = current, next(spans, None)
        if current and not (compound or current[2]):
            try:
                if pair := _paired_sql(text[start:end], text[current[0]:current[1]], dialect):
                    query, name, materialization, gap = pair
                    yield source, start, current[1], query, [name], gap, materialization, ""
                    current = next(spans, None)
                    continue
            except DIALECT_ERRORS:
                pass  # Retain both original statements independently.
        raw = text[start:end]
        if dialect == "tsql" and (batch := SQL_BATCH_SEPARATOR.fullmatch(raw)):
            gap = "Account for repeated T-SQL batch execution and writes." if batch["repeat"] else ""
            yield source, start, end, None, [], gap, None, "" if gap else "preserved"
            continue
        if compound:
            yield (source, start, end, None, script_writes(raw, dialect),
                   "Review the procedural block, execution ordering and any dynamic outputs as a whole.", None, "")
            continue
        try:
            if fact := declaration(raw, dialect):
                declarations[fact[0]].append(fact[1])
                yield source, start, end, None, [], "", None, "preserved"
                continue
            query, name, materialization, gap = sql_unit(raw, dialect, merge_draft=True)
            if query is not None and materialization == "view":
                query.meta["migration_view_definition"] = True
        except DIALECT_ERRORS:
            query, name, materialization, gap = None, None, None, "Recover opaque SQL and identify affected outputs."
        names = [name] if name else script_writes(raw, dialect) if gap else []
        yield source, start, end, query, names, gap, materialization, ""


def _inventory(snapshot, metadata, declarations):
    for source in snapshot["sources"]:
        text = source.get("text", "")
        kind, path, dialect = source["kind"], source["path"], source.get("dialect", "")
        if "text" not in source or SECRET_FILE.search(path):
            yield source, 0, 0, None, [], source.get("skip", "Sensitive file excluded."), None, "excluded"
        elif kind == "sas":
            for start, end, query, names, gap, materialization in sas_units(text):
                yield source, start, end, query, names, gap, materialization, ""
        elif kind == "sql":
            yield from _inventory_sql(source, declarations)
        elif kind == "dbt" and source.get("role") == "model" and path.lower().endswith(".sql"):
            name = dbt_model_name(path)
            try:
                query, _, _, config = inspect_sql(text, dialect or "databricks")
                file_config = {}
                if metadata["root"] is not None:
                    relative = str(PurePosixPath(path).relative_to(metadata["root"]))
                    file_config = inherited_config(metadata["config"], metadata["project"], relative,
                                                   "model", metadata["paths"])
                config = {**file_config, **metadata["model_config"].get(name, {}), **(config or {})}
                metadata.setdefault("resolved_config", {})[source["id"]] = config
                if not config.get("enabled", True):
                    yield source, 0, len(text), None, [name], "Disabled in the original dbt configuration.", None, "excluded"
                    continue
                materialization = config.get("materialized", "view")
                gap = "" if dialect == "databricks" else "Confirm the original model dialect and lowering."
            except DIALECT_ERRORS:
                query, materialization, gap = None, None, "Resolve unsupported model SQL or executable templates."
            yield source, 0, len(text), query, [name], gap, materialization, ""
        elif kind == "dbt" and source.get("role") == "model" and path.lower().endswith(".py"):
            yield (source, 0, len(text), None, [dbt_model_name(path)],
                   "Translate the Python model's data-frame transformations and dependencies into relational SQL.", None, "")
        elif kind == "dbt":
            preserved = path.lower().endswith((".yml", ".yaml")) and source.get("role") in {"project", "model"}
            gap = metadata["errors"].get(source["id"], "" if preserved else (
                "Review dbt resource semantics and any external prerequisites before adding to the active project."))
            yield source, 0, len(text), None, [], gap, None, "preserved" if preserved and not gap else ""
        elif kind == "builder":
            names = [source["table"]] if source["role"] != "source" else []
            gap = "Specify expressions, row grain, joins and filters for this design output." if names else ""
            yield source, 0, len(text), None, names, gap, None, "preserved" if not names else ""
        else:
            yield source, 0, len(text), None, [], "Map this resource or account for it as an external prerequisite.", None, ""


def _binding(call, project):
    kind, first, second = call
    if kind == "source":
        return f"source:{first}.{second}"
    if second:
        return second if first == project else f"package:{first}.{second}"
    return first


class SourceBindingError(ValueError):
    pass


def source_relation(name, kind):
    """Match analyzed names to statically identified source outputs."""
    if kind == "sql" and '"' in name and SIMPLE_SQL_RELATION.fullmatch(name):
        # Analysis can omit redundant quoting on lowercase SQL identifiers.
        return name.replace('"', "")
    key = name.casefold()
    return "work." + key if kind == "sas" and "." not in key else key


def _preceding_writer(writes, position):
    index = bisect_left(writes, position, key=lambda writer: writer[0])
    return writes[index - 1][1] if index else None


def _possible_producer(name, logical, kind):
    if kind == "sql" and ('"' in name or '"' in logical):
        name, logical = source_relation(name, kind), source_relation(logical, kind)
    declared, referenced = name.casefold().split("."), logical.casefold().split(".")
    if declared[-1] != referenced[-1]:
        return False
    if kind == "sql" and all(NAME.fullmatch(part) for part in declared + referenced):
        common = min(len(declared), len(referenced))
        return declared[-common:] == referenced[-common:]
    return True


def _inputs(query, sql, source, producers, target, physical, materialization, project, staged=None, *,
            local_writes=None, position=0, emit=True):
    kind = source["kind"]
    if kind == "dbt":
        _, tables, template_refs, config = inspect_sql(sql, source.get("dialect") or target.dialect)
        bindings = []
        for table in tables:
            call = template_refs.get(table.name)
            if call:
                binding = _binding(call, project)
                bindings.append(producers.get(binding.casefold(), binding))
            else:
                bindings.append("physical:" + relation(table))
        # Same-target models keep their original bytes and template calls.
        return sql if emit else "", sorted(set(bindings)), (config or {}).get("materialized", materialization)
    bindings = []
    templates = {}
    dialect = source.get("dialect", "")
    table_scopes = [(node, scope) for scope in traverse_scope(query)
                    for node, source_node in _scope_inputs(scope).values() if isinstance(source_node, exp.Table)
                    or (isinstance(node, exp.Table) and temporary_relation(relation(node), dialect))]
    for table, scope in table_scopes:
        logical = relation(table)
        if dialect == "sqlite" and not table.db:
            temp_name = f"temp.{logical}"
            temp_writes = (local_writes or {}).get(temp_name, ())
            if temp_writes and (position is None or _preceding_writer(temp_writes, position)):
                logical = temp_name
        identity = source_relation(logical, kind)
        work = kind == "sas" and identity.startswith("work.")
        temporary = temporary_relation(logical, dialect)
        linked = (staged or {}).get(logical) if temporary else producers.get(logical)
        writes = (local_writes or {}).get(identity if work else logical, ())
        prior_version = False
        if temporary and not linked:
            writer = "CREATE TEMP TABLE" if dialect == "sqlite" else "SELECT INTO"
            raise SourceBindingError(
                f"A temporary input needs exactly one preceding {writer} writer in this script. "
                "Resolve its session lifetime, control flow and other writes before conversion.")
        if temporary and dialect == "sqlite" and position is None:
            raise SourceBindingError("A persistent SQLite view cannot use a script-local temporary input.")
        if work:
            linked = _preceding_writer(writes, position)
            if not linked:
                raise SourceBindingError(
                    f"SAS input {logical} needs an earlier WORK writer in the same session. "
                    "Confirm the job order and select the actual inputs in a conversion contract.")
        elif kind == "sql" and not temporary and writes and position is not None:
            linked = _preceding_writer(writes, position)
            prior_version = not linked
        if linked:
            call = "{{ ref('" + linked + "') }}"
        else:
            if not prior_version and any(_possible_producer(name, logical, kind) for name in producers):
                raise ValueError("A possible transformation producer needs an exact relation mapping")
            linked, call = _physical_input([p.name for p in table.parts], logical, physical)
            if prior_version:
                physical[linked].update(prior_version=True, assumed_location=True)
        token = f"{MARKER}{len(templates)}__"
        templates[token] = call
        _replace_input(table, scope.columns, token)
        bindings.append(linked)
    if MARKER in sql:
        raise ValueError("Reserved migration parser token")
    if not emit:
        return "", sorted(set(bindings)), materialization
    rendered = target.emit_sql(query)
    rendered = re.sub(rf"{MARKER}\d+__", lambda match: templates[match[0]], rendered)
    return rendered + "\n", sorted(set(bindings)), materialization


def _manual_inputs(raw, source, output, producers, physical, local_writes, position):
    """Recover literal parser edges for the named output within a retained source span."""
    kind = source["kind"]
    dialect = source.get("dialect", "")
    if kind == "sas":
        code = raw if re.search(r"\b(?:data|proc)\s+", raw, re.I) else "proc sql;\n" + raw + "\nquit;"
        parsed = parse_sas(code, sql_dialect=dialect)
        name = source_relation(output["name"], kind)
    else:
        parsed = parse_sql(raw, dialect)
        name = output["name"]
    inputs = set()
    for op in parsed.operations:
        if any(ref.name.casefold() == name.casefold() for ref in op.targets):
            if kind == "sas":
                names = [row["target_column"] for row in sorted(op.derivations, key=lambda row: row["ordinal"])
                         if not row.get("scope") and row["target_table"].casefold() == name.casefold()]
                if names and all(names) and len(names) == len(set(names)):
                    output.setdefault("expected_columns", names)
                    if op.method == "sas-proc-sql":
                        output["ordered_projection"] = True
                if names and all(row["category"] == "inline_data" for row in op.derivations):
                    if inline := sas_inline_evidence(raw, names):
                        output["sas_inline"] = inline
                        output["ordered_projection"] = True
                        output["critical"] = False
                        output["manual"] = "Verify the literal seed rows, SAS informats and target date and numeric types."
                if op.kind == "DATA":
                    passthrough = next((row for row in op.derivations if row.get("sas_passthrough")
                                        and not row.get("scope") and row["target_table"].casefold() == name.casefold()), None)
                    if passthrough and len(op.sources) == 1:
                        output["sas_passthrough"] = {"exclude": passthrough.get("sas_exclude", []),
                                                     "computed": [column for column in names if column]}
                    filters = sorted({dep["column"] for row in op.derivations for dep in row.get("inputs", [])
                                      if dep["role"] == "row_filter" and NAME.fullmatch(dep["column"])})
                    if filters:
                        output["sas_row_filter_columns"] = filters
                    assignments = {row["target_column"]: row["expression"] for row in op.derivations
                                   if row.get("scope") == "data-step" and row["status"] == "verified"
                                   and row["target_column"] in names and len(row["expression"]) <= 512
                                   and re.match(r"\s*\w+\s*=\s*\w+\s*\(", row["expression"])}
                    if assignments:
                        output["sas_computed_columns"] = assignments
            for ref in op.sources:
                if (kind == "sas" and op.kind == "PROC IMPORT" and ref.kind == "file"
                        and ref.name.lower().endswith(".csv") and re.search(r"\bdbms\s*=\s*csv\b", code, re.I)):
                    filename = ref.name.removeprefix("file:")
                    identifier = "ingested_" + slug(PurePosixPath(filename).stem)
                    key, _ = _physical_input([identifier], ref.name, physical)
                    physical[key]["input_file"] = filename
                    output["manual"] = "Map the ingested CSV and confirm its schema, header, parsing and replacement behavior."
                    inputs.add(key)
                    continue
                if ref.name.casefold() != name.casefold() and not temporary_relation(ref.name):
                    key = _manual_binding(ref.name, kind, producers, physical, local_writes, position)
                    if key:
                        inputs.add(key)
    return inputs


def expected_columns(plan, model, visited=()):
    """Use a complete planned input layout for one-to-one SAS DATA-step passthrough."""
    output = plan["outputs"].get(model, {})
    if columns := output.get("expected_columns"):
        return columns
    passthrough = output.get("sas_passthrough")
    inputs = output.get("inputs", [])
    if passthrough and len(inputs) == 1 and model not in visited and len(visited) < 50:
        parent = expected_columns(plan, inputs[0], (*visited, model))
        if parent:
            return [column for column in parent if column not in passthrough["exclude"]] + passthrough["computed"]
    return []


def _manual_binding(logical, kind, producers, physical, local_writes, position):
    identity = source_relation(logical, kind)
    writes = local_writes.get(identity if kind == "sas" else logical, ())
    if kind == "sas" and identity.startswith("work."):
        return _preceding_writer(writes, position)
    linked = _preceding_writer(writes, position) if writes else producers.get(logical)
    if linked:
        return linked
    parts = logical.split(".")
    if len(parts) <= 3 and all(NAME.fullmatch(part) for part in parts):
        key = _physical_input(parts, logical, physical)[0]
        if writes:
            physical[key].update(prior_version=True, assumed_location=True)
        return key
    return None


def convert(snapshot, cancelled=lambda: False, progress=None, *, resumed=None, checkpoint=None, drafts=True):
    """Cover every source range and plan every known output before qualifying any model."""
    target = warehouse(snapshot)
    metadata = _dbt_metadata(snapshot)
    sources = {s["id"]: s for s in snapshot["sources"]}
    regions, outputs, candidates, files, physical = [], {}, {}, {}, dict(metadata["sources"])
    producers, writers = {}, defaultdict(list)
    local_writes = defaultdict(lambda: defaultdict(list))
    declarations = defaultdict(list)
    barriers = []
    opaque_sql = set()
    source_index = None
    line_offsets = []
    for source, start, end, query, names, gap, materialization, disposition in _inventory(snapshot, metadata, declarations):
        if cancelled():
            raise InterruptedError()
        if len(regions) >= MAX_REGIONS:
            raise ValueError(f"Scope exceeds {MAX_REGIONS:,} source regions. Split the migration into smaller batches.")
        region_id = f"r{len(regions) + 1}"
        if source["id"] != source_index:
            source_index = source["id"]
            line_offsets = [match.end() for match in re.finditer(r"\r\n|\r|\n", source.get("text", ""))]
        if source.get("skip") and not gap:
            gap = source["skip"]
        names = list(dict.fromkeys(n.casefold() if source["kind"] == "sas" else n for n in names))
        if query is not None and not names:
            names = [f"{PurePosixPath(source['path']).stem}_{region_id}"]
        region = {
            "id": region_id, "source": source["id"], "hash": source["hash"], "start": start, "end": end,
            "start_line": 1 + bisect_right(line_offsets, start), "end_line": 1 + bisect_right(line_offsets, max(start, end - 1)),
            "utf8_bytes": len(source.get("text", "")[start:end].encode()),
            "outputs": [], "gap": gap, "disposition": disposition or (
                "manual_required" if gap else "candidate" if query is not None else "non_executable"
            ),
        }
        regions.append(region)
        if not names and gap and source.get("selected") is False and source["kind"] not in {"sql", "sas", "dbt"}:
            region["disposition"] = "excluded"
        if query is None and gap and not names and region["disposition"] != "excluded":
            barriers.append(region_id)
        if query is None and gap and source["kind"] == "sql":
            opaque_sql.add(source["id"])
        for name in names:
            plain = name.split(".")[-1].strip('"')
            identity = source_relation(name, source["kind"])
            work = source["kind"] == "sas" and identity.startswith("work.")
            temporary = source["kind"] == "sql" and temporary_relation(name, source.get("dialect", ""))
            key = (source["id"], identity) if temporary or work else identity if source["kind"] == "dbt" else name
            # A later identified writer cannot be silently dropped; give it its own conversion obligation.
            existing = bool(writers[key])
            model = plain if NAME.fullmatch(plain) else slug(name) + "_" + digest(name)[:8]
            if existing or model.casefold() in outputs or RESERVED_PATH.fullmatch(model):
                model = slug(name) + "_" + digest(source["id"] + ":" + str(start) + ":" + name)[:10]
            model = model.casefold() if source["kind"] != "dbt" else model
            writers[key].append(model)
            if not temporary and not work:
                producers.setdefault(key, model)
            if work or source["kind"] == "sql" and (not temporary or source.get("dialect") == "sqlite"):
                local_writes[source["id"]][identity if work else name].append((start, model))
            region["outputs"].append(model)
            outputs[model] = {
                "name": name, "region": region_id, "kind": source["kind"], "inputs": [],
                "materialization": materialization or snapshot.get("materialization", "table"),
                "hard": [], "review": [gap] if gap and query is not None else [],
            }
            if source["kind"] == "dbt":
                cfg = metadata.get("resolved_config", {}).get(source["id"], {})
                outputs[model]["dbt_config"] = {key: value for key, value in cfg.items() if key in {"alias", "tags"}}
            if disposition == "excluded":
                outputs[model]["excluded"] = True
            if query is not None:
                candidates[model] = query[name] if isinstance(query, dict) else query
                if source["kind"] in {"sas", "sql"}:
                    columns = [output_name(item) for item in candidates[model].selects]
                    if columns and all(column and column != "*" for column in columns) and len(columns) == len(set(columns)):
                        outputs[model]["expected_columns"] = columns
                if source["kind"] == "sql" and isinstance(query, (exp.Select, exp.Union)) and not query.meta.get("migration_merge_keys"):
                    outputs[model]["sql_evidence"] = _sql_query_evidence(query, target)
                    outputs[model]["ordered_projection"] = True
                    if dropped := query.meta.get("migration_guarded_drop"):
                        outputs[model]["guarded_drop"] = dropped
                if isinstance(query, dict):
                    outputs[model].update(manual=gap, critical=True)
                elif keys := query.meta.get("migration_merge_keys"):
                    outputs[model]["suggested_merge_keys"] = keys
                elif order := query.meta.get("migration_sas_order"):
                    outputs[model].update(manual=gap, critical=True, sas_order=order)
                elif remerge := query.meta.get("migration_sas_remerge"):
                    outputs[model].update(manual=gap, critical=True, sas_remerge=remerge)
                elif stack := query.meta.get("migration_sas_stack"):
                    outputs[model].update(manual=gap, sas_stack=stack)
            elif gap:
                outputs[model]["manual"] = gap
                if source["kind"] in {"sas", "sql"} or "Python model" in gap:
                    outputs[model]["critical"] = True
    region_by_id = {row["id"]: row for row in regions}
    if progress:
        progress(.5, "Mapping inventoried transformation outputs")
    declared_outputs = snapshot.get("known_outputs", {})
    regions_by_source = defaultdict(list)
    for region in regions:
        regions_by_source[region["source"]].append(region)
    mapped = {(r["source"], source_relation(outputs[model]["name"], outputs[model]["kind"]))
              for r in regions for model in r["outputs"]}
    # SQLite lineage can spell CREATE TEMP TABLE output without its implicit temp schema.
    local_aliases = {(r["source"], outputs[model]["name"].removeprefix("temp."))
                     for r in regions for model in r["outputs"]
                     if sources[r["source"]].get("dialect") == "sqlite" and r["source"] not in opaque_sql
                     and outputs[model]["name"].startswith("temp.") and outputs[model]["materialization"] == "ephemeral"}
    for file_id, names in declared_outputs.items():
        for name in dict.fromkeys(names):
            if file_id not in sources:
                continue
            source = sources[file_id]
            identity = source_relation(name, source["kind"])
            if (file_id, identity) in mapped or (file_id, identity) in local_aliases:
                continue
            mapped.add((file_id, identity))
            # A parsed output may still be missing from an otherwise clean converter ledger.
            source_regions = regions_by_source[file_id]
            region = next((row for row in source_regions if row["gap"]), source_regions[0] if source_regions else None)
            if region is None:
                continue
            model = slug(name) + "_" + digest(file_id + name)[:10]
            region["outputs"].append(model)
            outputs[model] = {"name": name, "region": region["id"], "kind": source["kind"], "inputs": [],
                              "materialization": "table", "hard": [], "review": [],
                              "manual": "Locate this analyzed output in its retained source.", "critical": True}
            if not temporary_relation(name, source.get("dialect", "")) and not (source["kind"] == "sas" and identity.startswith("work.")):
                producers.setdefault(name.casefold(), model)
    for models in writers.values():
        if len(models) > 1:
            for model in models:
                outputs[model]["hard"].append("Several operations write this relation. Resolve writer order and history.")
    grouped = defaultdict(list)
    for model in outputs:
        grouped[model.casefold()].append(model)
    for duplicates in grouped.values():
        if len(duplicates) > 1:
            for model in duplicates:
                outputs[model]["hard"].append("Case-insensitive dbt model name collision.")
    resumed = resumed or {}
    pending = {}

    def flush():
        if pending and checkpoint:
            checkpoint(pending)
            pending.clear()

    generated_bytes = 0
    bound = set()
    staged_by_source = defaultdict(dict)
    for model, query in candidates.items():
        if cancelled():
            flush()
            raise InterruptedError()
        output = outputs[model]
        region = region_by_id[output["region"]]
        source = sources[region["source"]]
        raw = source["text"][region["start"]:region["end"]]
        dialect = source.get("dialect", "")
        staged = staged_by_source[source["id"]]
        if source["kind"] not in ("sas", "builder") and dialect not in {"", target.dialect}:
            output["review"].append("Source dialect translation requires semantic review.")
        if source["kind"] == "sas":
            output["review"].append("Verify SAS missing values, schema attributes and expression semantics.")
        if unsafe_query(query):
            output["hard"].append("Replace SQL side effects or unsafe relation operations with an explicit design.")
        if source["kind"] == "dbt" and not metadata["project"]:
            output["hard"].append("Establish the original dbt project configuration.")
        unsupported = sorted({type(node).__name__ for node in query.walk()} - QUALIFIED)
        if unsupported:
            output["review"].append("Review unqualified SQL constructs: " + ", ".join(unsupported))
        if query.find(exp.SetOperation):
            output["review"].append("Confirm positional types and duplicate semantics of every set branch.")
        if query.find(exp.Div, exp.Mod, exp.Sum, exp.Avg, exp.Cast):
            output["review"].append("Confirm numeric precision, overflow, division or cast semantics.")
        if any(join.side not in {"", "LEFT"} or join.kind not in {"", "INNER", "OUTER"}
               or not isinstance(join.args.get("on"), exp.EQ) for join in query.find_all(exp.Join)):
            output["review"].append("Review nonqualified join predicates or join type.")
        if query.find(exp.With) and any(node.args.get("recursive") for node in query.find_all(exp.With)):
            output["hard"].append("Recursive dependencies require a different conversion.")
        try:
            saved = resumed.get(model)
            if saved:
                rendered, dependencies, materialization, bindings = saved
            else:
                bindings = {}
                # A view definition retains live relation references. SELECT/CTAS snapshots read at their statement.
                position = None if query.meta.get("migration_view_definition") else region["start"]
                rendered, dependencies, materialization = _inputs(
                    query, raw, source, producers, target, bindings, output["materialization"], metadata["project"], staged,
                    local_writes=local_writes[source["id"]], position=position, emit=drafts)
            size = len(rendered.encode())
            if size > MAX_ARTIFACT or generated_bytes + size > MAX_PROJECT:
                raise ValueError("Generated model exceeds the artifact budget")
            output["inputs"] = dependencies
            output["materialization"] = materialization
            for key, binding in bindings.items():
                if binding.get("prior_version") or key not in physical:
                    physical[key] = binding
            if not output.get("sas_order") or dependencies:
                bound.add(model)
            if drafts and not output.get("sas_order"):
                files[model] = {"sql": rendered, "origin": "static", "hash": digest(rendered)}
                generated_bytes += size
            if (temporary_relation(output["name"], dialect) and materialization == "ephemeral" and not output["hard"]
                    and source["id"] not in opaque_sql and len(writers[source["id"], output["name"]]) == 1):
                staged[output["name"]] = model
            elif temporary_relation(output["name"], dialect):
                output["hard"].append("Resolve temporary table writes and control flow in the source script.")
        except SourceBindingError as exc:
            output.update(manual=str(exc), critical=True)
            region.update(gap=str(exc), disposition="manual_required")
        except DIALECT_ERRORS:
            output["hard"].append("Lowering failed. Resolve dynamic names, ambiguous producers or target syntax.")
        else:
            if checkpoint and not saved:
                pending[model] = (rendered, dependencies, materialization, bindings)
                if len(pending) >= 25:
                    flush()
    flush()
    table_by_id = {s["id"].removeprefix("builder-"): s for s in sources.values() if s["kind"] == "builder"}
    builder_columns = dict(snapshot.get("builder_columns", {}))
    for model, output in outputs.items():
        if model in bound:
            continue
        region = region_by_id[output["region"]]
        source = sources[region["source"]]
        inputs = set()
        if output["kind"] == "builder":
            table_id = source["id"].removeprefix("builder-")
            for link in snapshot.get("builder_links", []):
                if link["target_table"] != table_id:
                    continue
                parent = table_by_id[link["source_table"]]
                logical = parent["table"]
                if logical in producers:
                    inputs.add(producers[logical])
                else:
                    key, _ = _physical_input([logical], logical, physical)
                    inputs.add(key)
                    builder_columns[key] = builder_columns.get(logical, {})
        elif output["kind"] in {"sas", "sql"} and "text" in source and output.get("manual"):
            raw = source["text"][region["start"]:region["end"]]
            try:
                inputs.update(_manual_inputs(raw, source, output, producers, physical,
                                             local_writes[source["id"]], region["start"]))
            except DIALECT_ERRORS:
                output["review"].append("Supply literal dependencies in the conversion contract.")
        output["inputs"] = sorted(inputs)
    selected = snapshot.get("selected_outputs")
    restricted = any(source.get("selected") is False for source in sources.values())
    if selected or restricted:
        wanted = {kind: {source_relation(name, kind) for name in selected or ()} for kind in {s["kind"] for s in sources.values()}}
        active = set()
        for model, row in outputs.items():
            source = sources[region_by_id[row["region"]]["source"]]
            chosen = source.get("selected", True)
            name = source_relation(row["name"], row["kind"])
            work = row["kind"] == "sas" and name.startswith("work.")
            sqlite_local = name.startswith("temp.") and (source["id"], name[5:]) in local_aliases
            match = name in wanted[row["kind"]] or sqlite_local and name[5:] in wanted[row["kind"]]
            if (selected and match and (chosen or not (work or sqlite_local))) or (not selected and chosen):
                active.add(model)
        queue = list(active)
        while queue:
            for parent in outputs[queue.pop()]["inputs"]:
                if parent in outputs and parent not in active:
                    active.add(parent)
                    queue.append(parent)
        for model, row in outputs.items():
            if model not in active:
                row["excluded"] = True
                files.pop(model, None)
    for region in regions:
        if region["outputs"] and all(outputs[model].get("excluded") for model in region["outputs"]):
            region["disposition"] = "excluded"
        elif (not region["outputs"] and restricted and sources[region["source"]].get("selected") is False
              and not region["gap"]):
            region["disposition"] = "excluded"
    if selected and not any(not row.get("excluded") for row in outputs.values()):
        barriers.append("unmatched-selection")
    used = {key for row in outputs.values() if not row.get("excluded") for key in row["inputs"]}
    declared_sources = dict(physical)
    declaration_conflicts = []
    for key, row in declared_sources.items():
        facts = [] if row.get("prior_version") else declarations.get(row.get("relation"), [])
        if facts and all(fact == facts[0] for fact in facts):
            metadata["columns"][key] = facts[0]
        elif facts:
            declaration_conflicts.append(key)
        override = snapshot.get("source_mappings", {}).get(key)
        if override:
            row.update({k: override[k] for k in ("catalog", "schema", "identifier")})
            row["assumed_location"] = False
        if row.get("catalog") is None:
            row["catalog"] = snapshot["catalog"]
            row["assumed_location"] = True
        if row.get("schema") is None:
            row["schema"] = snapshot["schema"]
            row["assumed_location"] = True
    plan = {"regions": regions, "outputs": outputs, "physical": {key: row for key, row in declared_sources.items()
            if key in used or "relation" not in row},
            "barriers": barriers, "columns": {**metadata["columns"], **builder_columns},
            "declaration_conflicts": declaration_conflicts, "docs": metadata["docs"],
            "project": metadata["project"], "version": VERSION}
    return plan, files
def _join_bindings(query, aliases, alias_keys, invalid):
    """Track merged keys and which inputs are visible in each ON clause and in the result."""
    groups, predicates = {}, {}
    joins = [(join, alias_keys[join.this.alias_or_name.casefold()]) for join in query.args.get("joins") or ()
             if join.this.alias_or_name.casefold() in alias_keys]
    visible = set(aliases) - {right for _, right in joins}
    for join, right in joins:
        predicates[id(join)] = visible | {right}
        filters = join.kind in {"SEMI", "ANTI"}
        for column in join.args.get("using") or ():
            name = column.name.casefold()
            left = {alias for alias in visible if name in aliases[alias][1] or not aliases[alias][2]}
            _, right_columns, right_complete = aliases[right]
            if not left or right_complete and name not in right_columns:
                invalid.setdefault(column.sql(), column.meta.get("line"))
            elif not filters and (len(left) == 1 or left == groups.get(name)):
                groups[name] = left | {right}
        if not filters:
            visible.add(right)
    return groups, visible, predicates


def _column_bindings(query, refs, plan, schemas, complete, target, model_config):
    layouts, bindings, invalid = {}, {}, {}
    uncertain = False
    for scope in traverse_scope(query):
        aliases, alias_keys = {}, {}
        for alias, (node, source) in _scope_inputs(scope).items():
            original_alias = alias.casefold()
            if isinstance(source, exp.Table):
                call = refs.get(source.name)
                key = _binding(call, plan.get("project")) if call else "physical:" + relation(source)
                if call and not node.alias:
                    alias = (plan["physical"].get(key, {}).get("identifier") if call[0] == "source"
                             else model_config.get(key, {}).get("alias", key)) or alias
                facts = {name.casefold(): fact["target_type"] if fact["provenance"] != "assumed_string" else None
                         for name, fact in schemas.get(key, {}).items()}
                if alias.casefold() in aliases:
                    invalid.setdefault(alias, node.this.meta.get("line"))
                aliases[alias.casefold()] = (key, facts, key in complete)
            else:
                facts, full = layouts.get(id(source), ({}, False))
                aliases[alias.casefold()] = (None, facts, full)
            alias_keys[original_alias] = alias.casefold()
        groups, projection_aliases, predicates = _join_bindings(scope.expression, aliases, alias_keys, invalid)
        for column in scope.columns:
            if column.is_star:
                continue
            name = column.name.casefold()
            visible = predicates.get(id(column.find_ancestor(exp.Join)), projection_aliases)
            if column.table:
                qualifier = column.table.casefold()
                if qualifier in aliases and qualifier not in visible:
                    invalid.setdefault(column.sql(), column.this.meta.get("line"))
                    continue
                candidates = [aliases[qualifier]] if qualifier in visible else []
                if not candidates and (scope.is_subquery or any(
                        column.table.casefold() in cols for _, cols, _ in aliases.values())):
                    uncertain = True
                    continue
            else:
                candidates = [alias for key, alias in aliases.items() if key in visible]
                if group := groups.get(name):
                    possible = {alias for alias, (_, cols, full) in aliases.items() if alias in visible and (name in cols or not full)}
                    if possible == group:
                        joined = [aliases[alias] for alias in sorted(group)]
                        bindings[id(column)] = (tuple(dict.fromkeys(key for key, _, _ in joined if key)),
                                                _common_type([cols.get(name) for _, cols, _ in joined]))
                        continue
            matches = [(key, cols[name]) for key, cols, _ in candidates if name in cols]
            unknown = [(key, None) for key, cols, full in candidates if not full and name not in cols]
            if len(matches) > 1 or not matches and not unknown:
                if not column.table and scope.is_subquery and len(candidates) <= 1:
                    uncertain = True
                    continue
                invalid.setdefault(column.sql(), column.this.meta.get("line"))
            elif len(matches) + len(unknown) == 1:
                key, dtype = (matches or unknown)[0]
                bindings[id(column)] = ((key,) if key else (), dtype)
            else:
                uncertain = True
        projected = {}
        full = True
        for selection, expressions in zip(scope.expression.selects, _projection_groups(scope.expression)):
            name = output_name(selection)
            if selection.is_star or not name or name.casefold() in projected:
                full = False
                continue
            projected[name.casefold()] = _projection_type(expressions, bindings, target)
        if scope.outer_columns:
            full = full and len(scope.outer_columns) == len(projected)
            projected = dict(zip(map(str.casefold, scope.outer_columns), projected.values())) if full else {}
        layouts[id(scope)] = projected, full
    return bindings, invalid, uncertain


def _infer_type(expression, bindings, target):
    if isinstance(expression, exp.Literal):
        if expression.is_string:
            return target.string_type
        if expression.is_int and len(expression.this) <= 9:
            return "INT"
    if isinstance(expression, exp.Boolean):
        return "BOOLEAN"
    if isinstance(expression, exp.Column):
        return bindings.get(id(expression), (None, None))[1]
    if isinstance(expression, exp.Count):
        return "BIGINT"
    if isinstance(expression, exp.Cast) and isinstance(expression.to, exp.DataType):
        return target.map_type(expression.to.sql(dialect=target.dialect))
    return None


def _common_type(types):
    if not types or None in types:
        return None
    if len(set(types)) == 1:
        return types[0]
    integers = ("TINYINT", "SMALLINT", "INT", "BIGINT")
    if all(dtype in integers for dtype in types):
        return max(types, key=integers.index)
    return None


def _projection_groups(query):
    query = query.unnest()
    if isinstance(query, exp.SetOperation):
        left, right = _projection_groups(query.this), _projection_groups(query.expression)
        return [expressions + (right[index] if index < len(right) and not query.args.get("by_name") else [None])
                for index, expressions in enumerate(left)]
    return [[item.this if isinstance(item, exp.Alias) else item] for item in query.selects]


def _projection_type(expressions, bindings, target):
    return _common_type([_infer_type(item, bindings, target) for item in expressions if not isinstance(item, exp.Null)])


def _known_columns(snapshot, plan, model, query, refs, schemas, complete, target, model_config):
    """Infer literals and unambiguous pass-throughs. Keep declared and assumed types distinct."""
    output = plan["outputs"][model]
    overrides = snapshot.get("types", {})
    declarations = plan["columns"].get(output["name"], {})
    bindings, invalid, uncertain = _column_bindings(query, refs, plan, schemas, complete, target, model_config)

    result = {}
    lineage = []
    names = set()
    missing_layout = False
    for index, (selection, expressions) in enumerate(zip(query.selects, _projection_groups(query))):
        name = output_name(selection)
        if selection.is_star or not name or name.casefold() in names:
            missing_layout = True
            continue
        names.add(name.casefold())
        inferred = _projection_type(expressions, bindings, target)
        declared = declarations.get(name)
        override = overrides.get(f"{model}.{name}")
        supported = target.map_type(override or declared) if override or declared else inferred
        result[name] = {
            "source_type": declared or inferred, "target_type": supported or target.string_type,
            "provenance": (
                "user_confirmed" if override and supported else "declared" if declared and supported
                else "inferred" if supported else "assumed_string"
            ),
            "ordinal": index + 1,
        }
        contributors = {}
        for expression in expressions:
            if expression is None:
                continue
            for column in expression.find_all(exp.Column):
                parents, _ = bindings.get(id(column), ((), None))
                for parent in parents:
                    key = (parent, column.name)
                    contributors[key] = (contributors.get(key, False) or len(parents) > 1
                                         or not isinstance(expression, exp.Column))
        for (parent, column), inferred_lineage in contributors.items():
            lineage.append({"source": parent, "source_column": column, "model": model,
                            "output_column": name, "inferred": inferred_lineage})
    sensitive = (exp.Where, exp.Join, exp.Having, exp.Group, exp.Order, exp.Distinct, exp.Cast,
                 exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Mod, exp.AggFunc, exp.Predicate,
                 exp.Case, exp.Coalesce, exp.Window)
    arithmetic = (exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Mod, exp.Neg)
    numeric = re.compile(r"^(?:TINYINT|SMALLINT|INT|BIGINT|FLOAT|DOUBLE|DECIMAL)(?:\b|\()")
    comparisons = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)
    unknown_sensitive = any(
        not column.is_star and _infer_type(column, bindings, target) is None
        and column.find_ancestor(*sensitive) is not None for column in query.find_all(exp.Column)
    ) or any(
        (fact := _infer_type(operand, bindings, target)) is not None and not numeric.match(fact)
        for node in query.find_all(*arithmetic) for operand in (node.this, node.expression) if operand is not None
    ) or any(
        left != right and not (numeric.match(left) and numeric.match(right))
        for node in query.find_all(*comparisons)
        if (left := _infer_type(node.this, bindings, target)) and (right := _infer_type(node.expression, bindings, target))
    )
    return result, missing_layout, unknown_sensitive, invalid, uncertain, lineage


def validate(snapshot, plan, files, reviews=None):
    """Reparse generated artifacts, derive dependency edges and gate the active project."""
    target = warehouse(snapshot)
    reviews = reviews or {}
    findings, checks, edges, layouts, parsed, tiers = [], [], [], {}, {}, {}
    regions = {row["id"]: row for row in plan["regions"]}
    source_kinds = {row["id"]: row["kind"] for row in snapshot["sources"]}
    outputs, physical = plan["outputs"], plan["physical"]
    graph = nx.DiGraph()
    logical_edges = {(dependency, model) for model, output in outputs.items() if not output.get("excluded")
                     for dependency in output["inputs"]}
    by_model = defaultdict(list)
    opaque_sources = {regions[region]["source"] for region in plan["barriers"] if region in regions}
    opaque_dbt = any(source_kinds.get(source) == "dbt" for source in opaque_sources)
    legacy_producers = plan["version"] < 2 and any(
        source_kinds.get(row["source"]) == "sql" and not row["outputs"]
        and row["gap"].startswith(("Review the procedural block", "Recover opaque SQL"))
        for row in regions.values()
    )

    def finding(code, message, model=None, hard=False, inherited=None, region=None, line=None):
        item = {"id": f"{model or region or 'scope'}:{code}:{len(by_model[model])}", "code": code,
                "message": message, "severity": "blocker" if hard else "review", "model": model,
                "region": region or (outputs[model]["region"] if model else None), "inherited_from": inherited}
        if line:
            item["generated_line"] = line
        findings.append(item)
        by_model[model].append(item)

    def check(model, name, status):
        checks.append({"model": model, "check": name, "status": status, "version": VERSION})

    for region in regions.values():
        if region["gap"] and not region["outputs"] and region["disposition"] not in {"excluded", "preserved"}:
            finding("unresolved_region", region["gap"], region=region["id"], hard=True)
    if "unmatched-selection" in plan["barriers"]:
        finding("unmatched_selection", "Find the producer of the selected analyzed asset before handoff.", hard=True)
    elif snapshot.get("selected_outputs"):
        seen = defaultdict(set)
        source_dialects = {source["id"]: source.get("dialect") for source in snapshot["sources"]}
        for output in outputs.values():
            if not output.get("excluded"):
                kind = output["kind"]
                src = regions[output["region"]]["source"]
                name = source_relation(output["name"], kind)
                seen[kind, name].add(src)
                if output["materialization"] == "ephemeral" and source_dialects[src] == "sqlite" and name.startswith("temp."):
                    seen[kind, name[5:]].add(src)
        kinds = {kind for kind, _ in seen}
        paths = {source["id"]: source["path"] for source in snapshot["sources"]}
        for name in snapshot["selected_outputs"]:
            if not any((kind, source_relation(name, kind)) in seen for kind in kinds):
                finding("unmatched_selection", f"Locate the producer of {name}.", hard=True)
            work = source_relation(name, "sas")
            producers = seen.get(("sas", work), ())
            if work.startswith("work.") and len(producers) > 1:
                candidates = ", ".join(sorted(paths.get(source, source) for source in producers))
                finding("ambiguous_work_selection", f"Choose one producing SAS file for {work}: {candidates}.", hard=True)
    for missing in snapshot.get("analysis_gaps", []):
        finding("incomplete_analysis", missing, hard=True)
    for source in snapshot["sources"]:
        if source.get("skip") and source.get("required"):
            finding("admission", f"Resolve skipped source {source['path']}: {source['skip']}", hard=True)
    for model, output in outputs.items():
        if output.get("excluded"):
            continue
        graph.add_node(model)
        for problem in output["hard"]:
            finding("source_structure", problem, model, hard=True)
        if output.get("critical") and not output.get("contract"):
            finding("critical_source", output["manual"], model, hard=True)
        if regions[output["region"]]["source"] in opaque_sources or (output["kind"] == "dbt" and opaque_dbt):
            finding("opaque_scope", "Resolve opaque regions in this source or dbt project.", model, hard=True)
        if legacy_producers and any(key in physical for key in output["inputs"]):
            finding("legacy_producer_inventory", "Create a fresh migration to recheck opaque producers against these inputs.",
                    model, hard=True)
        if plan["version"] < 7 and output["kind"] == "sql" and output["materialization"] != "view":
            reader = regions[output["region"]]
            writes = [regions[outputs[parent]["region"]] for parent in output["inputs"] if parent in outputs]
            if any(write["source"] == reader["source"] and write["start"] >= reader["start"] for write in writes):
                finding("legacy_source_order", "Reconvert from pinned sources to confirm the relation read before its later write.",
                        model, hard=True)
        file = files.get(model)
        source_id = regions[output["region"]]["source"]
        ai_review = snapshot.get("ai_source_reviews", {}).get(source_id, {})
        withheld = ai_review.get("withheld_drafts", {}).get(model)
        if withheld and withheld["before"] == (file and file["hash"]):
            for reason in withheld["reasons"]:
                finding("ai_draft_unapplied", reason, model, hard=True)
        if not file:
            finding("missing_output", output.get("manual", "Provide the required output file."), model, hard=True)
            check(model, "required_output", "fail")
            continue
        check(model, "required_output", "pass")
        if (not NAME.fullmatch(model) or RESERVED_PATH.fullmatch(model) or len(file["sql"].encode()) > MAX_ARTIFACT
                or digest(file["sql"]) != file["hash"]):
            finding("artifact_integrity", "Fix the model name, size or content hash.", model, hard=True)
            check(model, "artifact_integrity", "fail")
            continue
        check(model, "artifact_integrity", "pass")
        for note in output["review"]:
            finding("semantics", note, model)
        if file["origin"] != "static":
            finding("engineer_review", "Compare this edit against every mapped source obligation.", model)
        if source_id in snapshot.get("stale_ai_source_reviews", ()) or (
            model in ai_review.get("files", {}) and ai_review["files"][model] != file["hash"]
        ):
            finding("ai_source_review_stale", "Compare this draft against the original source and current dependencies again.", model)
        elif model in ai_review.get("files", {}):
            for region_id, observation in ai_review["coverage"].items():
                region = regions.get(region_id)
                if (region and (output["region"] == region_id or not region["outputs"])
                        and observation.get("ai_status", observation["status"]) != "accounted"):
                    finding("ai_source_review", observation.get("ai_detail", observation["detail"]),
                            model, region=region_id)
        if output.get("manual") and not output.get("critical"):
            finding("manual_semantics", output["manual"], model)
        if output.get("contract"):
            finding("manual_contract", "Compare the implementation with the recorded conversion contract.", model)
        if set(file.get("rules", [])) & set(snapshot.get("revoked_rules", [])):
            finding("revoked_lesson", "Revisit this edit in light of the revoked lesson.", model)
        try:
            query, tables, refs, config = inspect_sql(file["sql"], target.dialect)
            if unsafe_query(query):
                raise ValueError("Model contains a side effect")
        except DIALECT_ERRORS as exc:
            message = {
                "Every SELECT needs a projection": "Supply output expressions for each empty SELECT.",
                "Trailing comma in Databricks query": "Remove the trailing comma from the Databricks query.",
                "Window filters need QUALIFY or an outer query in Databricks":
                    "Compute the window in a SELECT, then filter it with QUALIFY or an outer query.",
                "Model contains a side effect": "Remove write operations from the model body.",
            }.get(str(exc), "Use a single target SELECT and literal ref/source/config calls.")
            errors = getattr(exc, "errors", ())
            line = errors[0].get("line") if errors else None
            finding("unsafe_sql", message, model, hard=True, line=line)
            check(model, "target_sql_and_templates", "fail")
            continue
        check(model, "target_sql_and_templates", "pass")
        parsed[model] = (query, tables, refs, config)
        if file["origin"] == "ai":
            source_columns = expected_columns(plan, model)
            projected = []
            for item in query.selects:
                if item.is_star and output.get("sas_passthrough") and len(output["inputs"]) == 1:
                    star = item.this if isinstance(item, exp.Column) else item
                    excluded = {name.name.casefold() for name in star.args.get("except_") or []}
                    projected.extend(name for name in expected_columns(plan, output["inputs"][0])
                                     if name.casefold() not in excluded)
                else:
                    projected.append(output_name(item))
            actual_names = [name.casefold() for name in projected]
            source_names = [name.casefold() for name in source_columns]
            if not output.get("ordered_projection"):
                actual_names.sort()
                source_names.sort()
            if source_columns and actual_names != source_names:
                finding("changed_projection", "Preserve the original output columns: "
                        + ", ".join(source_columns) + ".", model, hard=True)
            if evidence := output.get("sql_evidence"):
                observed = _sql_query_evidence(query, target)
                missing = set(evidence["operations"]) - set(observed["operations"])
                if {"row filters", "group filters"} & missing and query.find(exp.Qualify):
                    missing.difference_update(("row filters", "group filters"))
                if not set(evidence["filter_columns"]) <= set(observed["filter_columns"]):
                    missing.add("filter columns")
                if observed["union_all"] < evidence["union_all"]:
                    missing.add("UNION ALL branches")
                if Counter(evidence["literal_tables"]) - Counter(observed["literal_tables"]):
                    missing.add("literal VALUES rows")
                if evidence["casts"].items() - observed["casts"].items():
                    missing.add("declared projection casts")
                for behavior in ("predicate values or operators", "join types or keys", "ranking keys or sort direction"):
                    if Counter(evidence.get(behavior, ())) - Counter(observed[behavior]):
                        missing.add(behavior)
                if missing:
                    finding("sql_source_behavior", "Preserve original SQL behavior for "
                            + ", ".join(sorted(missing)) + ", or explain the rewrite in engineer review.", model, hard=True)
            if (inline := output.get("sas_inline")) and not _matches_inline_rows(query, inline):
                finding("sas_inline_rows", "Preserve every original DATALINES literal in a single VALUES model.",
                        model, hard=True)
            if required_filters := output.get("sas_row_filter_columns"):
                observed_filters = {column.name.casefold() for condition in query.find_all(exp.Where)
                                    for column in condition.find_all(exp.Column)}
                if not set(required_filters) <= observed_filters:
                    finding("sas_missing_filter", "Preserve the SAS DATA step row filter using: "
                            + ", ".join(required_filters) + ".", model, hard=True)
            if assignments := output.get("sas_computed_columns"):
                calculated = {item.alias.casefold() for select in query.find_all(exp.Select)
                              for item in select.selects if isinstance(item, exp.Alias)
                              and not isinstance(item.this, (exp.Column, exp.Literal))}
                if missing := sorted(assignments.keys() - calculated):
                    finding("sas_missing_assignment", "Preserve the SAS assignment as an output expression for: "
                            + ", ".join(missing) + ".", model, hard=True)
        if file["origin"] == "ai" and config and config.get("materialized", output["materialization"]) != output["materialization"]:
            finding("changed_materialization", "Keep the model's planned materialization. Change it in the migration plan.", model, hard=True)
        actual = set()
        for table in tables:
            call = refs.get(table.name)
            line = table.this.meta.get("line")
            if not call:
                dependency = "physical:" + relation(table)
                finding("unmapped_table", "Map direct relation references through a declared dbt source.", model, hard=True, line=line)
            elif call[0] == "ref":
                dependency = _binding(call, plan.get("project"))
                if dependency not in outputs or outputs[dependency].get("excluded"):
                    finding("broken_ref", f"Resolve the unplanned dbt model reference {dependency}.", model, hard=True, line=line)
                elif dependency not in files:
                    finding("pending_ref", f"Convert and review the planned upstream model {dependency}.", model, hard=True, line=line)
            else:
                dependency = f"source:{call[1]}.{call[2]}"
                if dependency not in physical:
                    finding("broken_source", f"Declare and map dbt source {call[1]}.{call[2]}.", model, hard=True, line=line)
                elif physical[dependency].get("assumed_location"):
                    source = physical[dependency]
                    message = (f"Map the version of {source['relation']} read before the write in this script."
                               if source.get("prior_version") else f"Confirm the catalog and schema for {source['relation']}.")
                    finding("source_mapping", message, model, hard=True, line=line)
                elif physical[dependency].get("prior_version"):
                    finding("prior_version", "Verify that the mapped input preserves the relation version read before the write.",
                            model, line=line)
                if dependency in plan.get("declaration_conflicts", []) and not snapshot.get("input_types", {}).get(dependency):
                    finding("schema_conflict", "Reconcile conflicting source declarations with a confirmed schema.", model)
            actual.add(dependency)
            graph.add_edge(dependency, model)
            edges.append({"source": dependency, "target": model, "model_hash": file["hash"],
                          "source_region": output["region"], "identifier": table.alias_or_name,
                          "line": table.this.meta.get("line", 1)})
        expected = set(output["inputs"])
        if actual != expected:
            finding("changed_dependencies", f"Reconcile expected inputs {sorted(expected)} with generated inputs {sorted(actual)}.",
                    model, hard=True)
        check(model, "dependencies", "fail" if any(row["severity"] == "blocker" and row["code"] in {
            "broken_ref", "pending_ref", "broken_source", "unmapped_table", "changed_dependencies", "source_mapping"}
            for row in by_model[model]) else "pass")
    components = list(nx.strongly_connected_components(graph))
    for component in components:
        if len(component) > 1 or any(graph.has_edge(node, node) for node in component):
            for model in component:
                if model in outputs:
                    finding("cycle", "Break the generated dependency cycle.", model, hard=True)
    schemas = {}
    for key, row in physical.items():
        declarations = plan["columns"].get(key, {})
        mapped = snapshot.get("input_types", {}).get(key, {})
        schemas[key] = {}
        for name in sorted(declarations.keys() | mapped.keys()):
            declared = declarations.get(name)
            target_type = target.map_type(mapped.get(name) or declared)
            provenance = "user_confirmed" if name in mapped else "declared"
            schemas[key][name] = {"source_type": declared, "target_type": target_type or target.string_type,
                                  "provenance": provenance if target_type else "assumed_string"}
    condensed = nx.condensation(graph, components)
    ordered = [model for component in nx.topological_sort(condensed)
               for model in sorted(condensed.nodes[component]["members"])]
    column_edges = []
    complete = set()
    model_config = {model: {"materialized": outputs[model]["materialization"],
                            **outputs[model].get("dbt_config", {}), **(entry[3] or {})}
                    for model, entry in parsed.items()}
    incremental = snapshot.get("incremental", {})
    for model, keys in incremental.items():
        if model in model_config:
            model_config[model].update(materialized="incremental", incremental_strategy="merge",
                                       unique_key=keys[0] if len(keys) == 1 else keys,
                                       file_format="delta", on_schema_change="fail", full_refresh=False)
    materializations = {model: cfg["materialized"] for model, cfg in model_config.items()}
    aliases = defaultdict(list)
    physical_names = {(row["catalog"].casefold(), row["schema"].casefold(), row["identifier"].casefold())
                      for row in physical.values()}
    for model in ordered:
        if model not in parsed:
            continue
        query, _, refs, _ = parsed[model]
        layout, partial, sensitive, invalid, uncertain, columns = _known_columns(
            snapshot, plan, model, query, refs, schemas, complete, target, model_config)
        schemas[model] = layouts[model] = layout
        column_edges.extend({**edge, "model_hash": files[model]["hash"], "source_region": outputs[model]["region"]}
                            for edge in columns)
        if materializations[model] != "ephemeral":
            alias = model_config[model].get("alias", model)
            aliases[alias.casefold()].append(model)
            if (snapshot["catalog"].casefold(), snapshot["schema"].casefold(), alias.casefold()) in physical_names:
                finding("target_collision", f"Target relation {snapshot['catalog']}.{snapshot['schema']}.{alias} "
                        "overlaps a configured input. Change the target alias or source mapping.", model, hard=True)
        if not partial and not invalid:
            complete.add(model)
        if partial:
            finding("unknown_layout", "Resolve wildcard layout, unnamed expressions or duplicate output columns.", model)
        for key in {item.sql(): item for select in query.find_all(exp.Select)
                    for item in grouping_key_errors(select)}.values():
            finding("target_aggregation", f"Replace invalid GROUP BY key {key.sql()} with a grouping expression.",
                    model, hard=True, line=key.meta.get("line"))
        for expression in {item.sql(): item for select in query.find_all(exp.Select)
                           for item in ungrouped_columns(select)}.values():
            anchor = expression.this if isinstance(expression, exp.Column) else expression
            finding("target_aggregation", f"Expression {expression.sql()} is outside the grouping and aggregate expressions. "
                    "Preserve the intended row grain when revising this SELECT.", model, hard=True,
                    line=anchor.meta.get("line"))
        sas_order = outputs[model].get("sas_order", {})
        if sas_order.get("kind") == "nodupkey":
            for window in query.find_all(exp.Window):
                if not isinstance(window.this, exp.RowNumber):
                    continue
                partition = window.args.get("partition_by") or ()
                if (len(partition) != len(sas_order["keys"]) or not all(isinstance(key, exp.Column) for key in partition)
                        or {key.name.casefold() for key in partition} != set(sas_order["keys"])):
                    finding("sas_partition", "Partition SAS NODUPKEY by the full BY tuple: "
                            + ", ".join(sas_order["keys"]) + ".", model, hard=True,
                            line=window.this.meta.get("line"))
        set_layouts = [(operation.this.unnest().selects, operation.expression.unnest().selects)
                       for operation in query.find_all(exp.SetOperation)]
        if any(not branch or any(projection.is_star for projection in branch)
               for branches in set_layouts for branch in branches):
            finding("set_layout", "Expand or confirm the exact layouts of all set-operation branches.", model, hard=True)
        elif any(len(left) != len(right) for left, right in set_layouts):
            finding("set_layout", "Reconcile the mismatched output counts of the set-operation branches.", model, hard=True)
        if isinstance(query.unnest(), exp.SetOperation) and any(fact["provenance"] == "assumed_string" for fact in layout.values()):
            finding("set_types", "Confirm compatible output types across all set-operation branches.", model)
        if stack := outputs[model].get("sas_stack"):
            unions = list(query.find_all(exp.Union))
            if not unions or any(union.args.get("distinct") is not False for union in unions):
                finding("sas_stack_operation", "Preserve SAS SET concatenation and duplicates with UNION ALL.", model, hard=True)
            inputs = outputs[model]["inputs"]
            facts_by_input = [{name.casefold(): fact["target_type"] for name, fact in schemas.get(parent, {}).items()
                               if fact["provenance"] != "assumed_string"} for parent in inputs]
            issues = [name for name in stack["columns"]
                      if not _common_type([facts.get(name.casefold()) for facts in facts_by_input])]
            if issues:
                manual = files[model]["origin"] != "static" and outputs[model].get("contract")
                finding("sas_stack_schema", "Confirm compatible input layouts for SAS SET columns " + ", ".join(issues)
                        + ", or document and implement the differences in a reviewed conversion.", model, hard=not manual)
        if sensitive:
            finding("unknown_sensitive_type", "Confirm operand types and coercion used by predicates, grouping or calculations.", model)
        for column, line in sorted(invalid.items()):
            finding("missing_column", f"Resolve the missing or ambiguous column binding for {column}.",
                    model, hard=True, line=line)
        if uncertain:
            finding("unproven_column_binding", "Confirm which inputs supply unbound column references.", model)
        if model in incremental:
            if "materialized" in (parsed[model][3] or {}):
                finding("incremental_config", "Remove inline materialization before applying the approved Delta merge config.",
                        model, hard=True)
            if any(column not in layouts[model] or layouts[model][column]["provenance"] == "assumed_string"
                   for column in incremental[model]):
                finding("merge_key", "Restore or confirm the incremental merge keys in the output schema.", model, hard=True)
            finding("incremental_merge", "Verify unique non-null keys, repeat runs, late arrivals and delete behavior.", model)
        if (required_keys := outputs[model].get("suggested_merge_keys")) and incremental.get(model) != required_keys:
            finding("merge_configuration", "Confirm the original MERGE keys and the Delta merge materialization in Validation.",
                    model, hard=True)
        check(model, "schema", "fail" if invalid else "unknown" if partial or sensitive or uncertain else "pass")
        check(model, "semantic_obligations", "unknown" if by_model[model] else "pass")
    for colliding in aliases.values():
        if len(colliding) > 1:
            for model in colliding:
                finding("target_collision", "Resolve model aliases that write the same Databricks relation.", model, hard=True)
    direct = {model: list(by_model[model]) for model in outputs}
    active = {}
    review_keys = {}
    nodes = {model: sorted(parent for parent in graph.predecessors(model)) for model in outputs if model in graph}
    for model in ordered:
        if model not in outputs or outputs[model].get("excluded"):
            continue
        file = files.get(model)
        own = direct[model]
        hard = any(row["severity"] == "blocker" for row in own)
        pending = [parent for parent in nodes[model] if parent in outputs and parent not in active]
        for parent in pending:
            finding("upstream", f"Resolve upstream model {parent} before handoff.", model,
                    hard=tiers.get(parent) == "blocked", inherited=parent)
        statuses = sorted(row["id"] for row in own if row["severity"] != "blocker")
        review_keys[model] = fingerprint({
            "sql": file and file["hash"], "source": regions[outputs[model]["region"]], "schema": layouts.get(model),
            "contract": outputs[model].get("contract"),
            "parents": [(parent, review_keys.get(parent), schemas.get(parent), physical.get(parent)) for parent in nodes[model]],
            "findings": [(row["code"], row["message"]) for row in own], "rules": file and file.get("rules", []),
            "target": target.profile,
            **({"incremental": incremental[model]} if model in incremental else {}),
        })
        accepted = (
            file and model in reviews and reviews[model]["key"] == review_keys[model]
            and sorted(reviews[model]["obligations"]) == statuses
        )
        if hard or any(row["severity"] == "blocker" for row in by_model[model]):
            tiers[model] = "blocked"
        elif pending or own:
            tiers[model] = "needs_investigation"
            if accepted and not pending:
                active[model] = "engineer_accepted"
        else:
            tiers[model] = "static_checks_satisfied"
            active[model] = "statically_qualified"
    scope_blockers = any(row["model"] is None for row in findings)
    actual_edges = {(row["source"], row["target"]) for row in edges}
    return {
        "checks": checks, "findings": findings, "tiers": tiers, "active": active,
        "eligible": bool(active) and not scope_blockers and len(active) == len(nodes),
        "review_keys": review_keys, "schemas": layouts, "source_schemas": {key: schemas[key] for key in physical},
        "materializations": materializations, "model_config": model_config,
        "runtime_equivalence": "not_evaluated",
        "lineage": {"edges": edges, "nodes": nodes, "missing": sorted(logical_edges - actual_edges),
                    "extra": sorted(actual_edges - logical_edges), "columns": column_edges},
    }
