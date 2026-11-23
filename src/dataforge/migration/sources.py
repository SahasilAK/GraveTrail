"""Bounded lexical inventory and conservative SQL/SAS/dbt source lowering."""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from math import isfinite
from pathlib import PurePosixPath

import sqlglot
from sqlglot import exp
from sqlglot.dialects.tsql import TSQL
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.scope import find_all_in_scope
from sqlglot.tokens import TokenType

from dataforge.dbt.yaml import read_yaml
from dataforge.parsers.sas import resolve_macros, strip_comments
from dataforge.parsers.sas_sql import sas_sql_dialect
from dataforge.parsers.sas_transformations import _dataset, _names, _renames, without_dataset_options

SAS_COLUMN = r"[A-Za-z_][A-Za-z_0-9]*"
SAS_NAME = rf"{SAS_COLUMN}(?:\.{SAS_COLUMN})?"
SAS_STRING = r"""'(?:[^']|'')*(?:'|\Z)|"(?:[^"]|"")*(?:"|\Z)"""
SAS_TRIVIA = re.compile(r"(?:\s+|/\*.*?\*/|%?\*[^;]*;)*", re.S)
SAS_TOKEN = re.compile(rf"/\*.*?(?:\*/|\Z)|{SAS_STRING}|;", re.S)
SAS_INLINE = re.compile(r"(?:datalines|cards)(4)?\s*;", re.I)
SAS_RUNTIME = re.compile(r"\bcall\s+(?:symputx?|execute)\s*\(", re.I)
SAS_LET = re.compile(rf"%let\s+({SAS_COLUMN})\s*=\s*(.*?)\s*;", re.I | re.S)
SAS_LET_VALUE = re.compile(
    rf"""(?:{SAS_NAME}|[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?|'(?:[^'\r\n]|'')*'|"(?:[^"\r\n]|"")*")"""
)
MUTATIONS = (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Drop, exp.Alter, exp.TruncateTable)
SECRET_FILE = re.compile(r"(?:^|/)(?:profiles\.ya?ml|secrets\.[^/]+|\.env[^/]*|[^/]+\.(?:pem|key|pfx))(?:$|/)", re.I)
SCRIPT_BLOCK = re.compile(r"\b(?:create\s+(?:(?:or\s+replace|or\s+alter)\s+)?(?:proc(?:edure)?|function|trigger)"
                          r"|begin\b|do\s+\$\$)", re.I)
SQL_BATCH_SEPARATOR = re.compile(r"[ \t]*go(?:[ \t]+(?P<repeat>\d+))?[ \t]*(?:--[^\r\n]*)?(?:\r\n?|\n|$)", re.I)
SQL_TEMP_INTO = re.compile(r"into\s+(\[#{1,2}[A-Za-z_]\w*\]|#{1,2}[A-Za-z_]\w*\b)", re.I)
SQL_IDENTIFIER = r'(?:#{0,2}[A-Za-z_][\w$]*|"(?:""|[^"])+"|`(?:``|[^`])+`|\[[^\]]+\])'
SCRIPT_WRITE = re.compile(
    rf"(?:create\s+(?:or\s+replace\s+)?(?:table|view)\s+(?:if\s+not\s+exists\s+)?"
    rf"|insert\s+(?:into|overwrite\s+table)\s+|update\s+|merge\s+into\s+|delete\s+from\s+)"
    rf"({SQL_IDENTIFIER}(?:\s*\.\s*{SQL_IDENTIFIER}){{0,2}})(?![\w.$])",
    re.I,
)


def spans(text, dialect=""):
    """Split on lexical semicolons, with all leading/trailing trivia preserved."""
    for start, end, _ in sql_regions(text, dialect, protect_blocks=False):
        yield start, end


class _TsqlInventoryTokenizer(TSQL.Tokenizer):
    # Keep GO visible as a standalone token instead of swallowing the next batch as command text.
    COMMANDS = TSQL.Tokenizer.COMMANDS - {TokenType.COMMAND}


def sql_regions(text, dialect, *, protect_blocks=True):
    """Split top-level SQL and keep an uncertain compound suffix together."""
    start = 0
    first_token = True
    compound = False
    try:
        tokens = (_TsqlInventoryTokenizer(dialect=TSQL()).tokenize(text) if protect_blocks and dialect == "tsql"
                  else sqlglot.tokenize(text, read=dialect or None))
    except (SqlglotError, ValueError, RecursionError):
        yield 0, len(text), False
        return
    for token in tokens:
        if token.start < start:
            continue
        if protect_blocks and dialect == "tsql" and token.token_type == TokenType.COMMAND and token.text.casefold() == "go":
            line_start = max(text.rfind("\n", 0, token.start), text.rfind("\r", 0, token.start)) + 1
            if line_start >= start and (separator := SQL_BATCH_SEPARATOR.match(text, line_start)):
                if start < line_start:
                    yield start, line_start, compound
                yield line_start, separator.end(), False
                start, first_token, compound = separator.end(), True, False
                continue
        if compound:
            continue
        if protect_blocks and first_token and SCRIPT_BLOCK.match(text, token.start):
            compound = True
            continue
        first_token = token.token_type == TokenType.SEMICOLON
        if first_token:
            end = token.end + 1
            yield start, end, False
            start = end
    if start < len(text):
        yield start, len(text), compound


def relation(table):
    if not isinstance(table, exp.Table) or not all(isinstance(p, exp.Identifier) for p in table.parts):
        raise ValueError("Dynamic, external or function-based table reference")
    parts = [p.sql() if p.quoted else p.name.casefold() for p in table.parts]
    prefix = "#" if table.this.args.get("temporary") else "##" if table.this.args.get("global_") else ""
    if prefix:
        parts[-1] = prefix + table.name.casefold()
    return ".".join(parts)


def temporary_relation(name, dialect=""):
    return name.rsplit(".", 1)[-1].lstrip('"').startswith("#") or (
        dialect == "sqlite" and bool(re.fullmatch(r"temp\.[a-z_]\w*", name)))


def guarded_table_drop(text, dialect):
    """Recognize only a single DROP TABLE IF EXISTS with no lifecycle options."""
    if not re.search(r"\bdrop\s+table\s+if\s+exists\b", text, re.I):
        return None
    trees = [tree for tree in sqlglot.parse(text, read=dialect or None) if tree is not None]
    if len(trees) != 1 or not isinstance(tree := trees[0], exp.Drop) or tree.kind != "TABLE" or not tree.args.get("exists"):
        return None
    if any(value for key, value in tree.args.items() if key not in {"this", "tables", "kind", "exists"}):
        return None
    tables = tree.args.get("tables") or [tree.this]
    return relation(tables[0]) if len(tables) == 1 else None


def sqlite_literal_table(create, insert):
    """Lower an exact SQLite initialization pair to a typed, read-only literal query."""
    if (not isinstance(create, exp.Create) or create.kind != "TABLE" or not isinstance(create.this, exp.Schema)
            or any(value for key, value in create.args.items() if key not in {"this", "kind"})
            or not isinstance(insert, exp.Insert) or not isinstance(values := insert.expression, exp.Values)
            or any(value for key, value in insert.args.items() if key not in {"this", "expression"})):
        return None
    name = relation(create.this.this)
    subject = insert.this.this if isinstance(insert.this, exp.Schema) else insert.this
    if relation(subject) != name or temporary_relation(name, "sqlite"):
        return None
    columns, required, keys = {}, set(), set()
    affinity = {"INT": "BIGINT", "INTEGER": "BIGINT", "TEXT": "STRING", "FLOAT": "DOUBLE",
                "REAL": "DOUBLE", "DOUBLE": "DOUBLE", "DOUBLE PRECISION": "DOUBLE"}
    for field in create.this.expressions:
        if (not isinstance(field, exp.ColumnDef) or not re.fullmatch(r"[A-Za-z_]\w*", field.name)
                or field.name.casefold() in columns or not isinstance(field.kind, exp.DataType)
                or not (target := affinity.get(field.kind.sql(dialect="sqlite")))):
            return None
        column = field.name.casefold()
        columns[column] = (field.name, target)
        for constraint in field.constraints:
            if isinstance(constraint.kind, exp.PrimaryKeyColumnConstraint) and not any(constraint.kind.args.values()):
                keys.add(column)
            elif not isinstance(constraint.kind, exp.NotNullColumnConstraint) or constraint.kind.args:
                return None
            required.add(column)
    if not columns or len(keys) > 1:
        return None
    supplied = ([field.name.casefold() for field in insert.this.expressions]
                if isinstance(insert.this, exp.Schema) else list(columns))
    if len(supplied) != len(columns) or set(supplied) != columns.keys() or not values.expressions:
        return None
    ordered_indices = [supplied.index(column) for column in columns]
    seen_keys = set()
    rows = []
    for row in values.expressions:
        if not isinstance(row, exp.Tuple) or len(row.expressions) != len(columns):
            return None
        cells = []
        for column, index in zip(columns, ordered_indices, strict=True):
            cell = row.expressions[index]
            _, target = columns[column]
            if isinstance(cell, exp.Null) and column not in required:
                cells.append(cell.copy())
                continue
            literal = cell.this if isinstance(cell, exp.Neg) else cell
            if not isinstance(literal, exp.Literal) or literal.is_string != (target == "STRING"):
                return None
            value = literal.this
            if target == "BIGINT":
                if not value.isascii() or not value.isdecimal() or len(value) > 19:
                    return None
                value = int(value) * (-1 if isinstance(cell, exp.Neg) else 1)
                if not -(2**63) <= value < 2**63:
                    return None
            elif target == "DOUBLE":
                value = float(value) * (-1 if isinstance(cell, exp.Neg) else 1)
                if not isfinite(value):
                    return None
            elif isinstance(cell, exp.Neg):
                return None
            if column in keys:
                if value in seen_keys:
                    return None
                seen_keys.add(value)
            cells.append(cell.copy())
        rows.append(exp.Tuple(expressions=cells))
    aliases = [exp.to_identifier(column) for column, _ in columns.values()]
    query = exp.select(*(exp.alias_(exp.cast(exp.column(column), target, dialect="databricks"), column)
                         for column, target in columns.values())).from_(
        exp.Values(expressions=rows, alias=exp.TableAlias(this=exp.to_identifier("seed_rows"), columns=aliases)))
    return query, name


def script_writes(text, dialect, *, inspect_literal=True):
    """Inventory statically named writes within opaque blocks without lowering their bodies."""
    try:
        tokens = sqlglot.tokenize(text, read=dialect or None)
    except (SqlglotError, ValueError, RecursionError):
        return []
    names = []
    for index, token in enumerate(tokens):
        if inspect_literal and token.token_type == TokenType.EXECUTE and index + 1 < len(tokens):
            argument = tokens[index + 1]
            if argument.token_type == TokenType.STRING and (literal := re.fullmatch(
                r"IMMEDIATE\s+'((?:[^']|'')*)'", argument.text.strip(), re.I | re.S
            )):
                names.extend(script_writes(literal[1].replace("''", "'"), dialect, inspect_literal=False))
        if token.token_type in (TokenType.CREATE, TokenType.INSERT, TokenType.UPDATE, TokenType.MERGE, TokenType.DELETE):
            match = SCRIPT_WRITE.match(text, token.start, token.start + 1024)
            if match:
                try:
                    names.append(relation(sqlglot.parse_one(match[1], into=exp.Table, read=dialect or None)))
                except (SqlglotError, ValueError, RecursionError):
                    continue
        elif dialect == "tsql" and token.token_type == TokenType.INTO:
            if match := SQL_TEMP_INTO.match(text, token.start, token.start + 256):
                names.append(match[1].strip("[]").casefold())
    return list(dict.fromkeys(names))


def _merge_projection(tree):
    """Draft an input projection for a literal, same-column update/insert MERGE."""
    target, source = tree.this, tree.args.get("using")
    if (not isinstance(target, exp.Table) or not isinstance(source, exp.Table) or relation(target) == relation(source)
            or not target.alias or not source.alias or target.alias == source.alias
            or any(value for key, value in tree.args.items() if key not in {"this", "using", "on", "whens"})):
        return None
    if any(value for table in (target, source) for key, value in table.args.items()
           if key not in {"this", "db", "catalog", "alias"}):
        return None

    def column(node, alias):
        if (isinstance(node, exp.Column) and isinstance(node.this, exp.Identifier) and not node.this.quoted
                and node.table == alias and not node.db and not node.catalog and re.fullmatch(r"[A-Za-z_]\w*", node.name)):
            return node.name
        return None

    keys = []
    pending = [tree.args.get("on")]
    while pending:
        term = pending.pop()
        if isinstance(term, exp.Paren):
            pending.append(term.this)
        elif isinstance(term, exp.And):
            pending.extend((term.expression, term.this))
        elif isinstance(term, exp.EQ):
            key = column(term.this, target.alias)
            if not key or key != column(term.expression, source.alias):
                key = column(term.expression, target.alias)
                if not key or key != column(term.this, source.alias):
                    return None
            if key in keys:
                return None
            keys.append(key)
        else:
            return None
    whens = tree.args.get("whens")
    branches = whens.expressions if whens else []
    if len(branches) != 2 or any(branch.args.get("condition") or branch.args.get("source") for branch in branches):
        return None
    update, insert = (branch.args.get("then") for branch in branches)
    if (not branches[0].args.get("matched") or branches[1].args.get("matched") or not isinstance(update, exp.Update)
            or not isinstance(insert, exp.Insert) or not isinstance(insert.this, exp.Tuple)
            or not isinstance(insert.expression, exp.Tuple)
            or any(value for name, value in update.args.items() if name != "expressions")
            or any(value for name, value in insert.args.items() if name not in {"this", "expression"})):
        return None
    values = insert.expression.expressions
    columns = [column(node, "") for node in insert.this.expressions]
    if (None in columns or columns != [column(node, source.alias) for node in values]
            or len(set(columns)) != len(columns) or not set(keys) <= set(columns)):
        return None
    updated = []
    for assignment in update.expressions:
        if (not isinstance(assignment, exp.EQ) or not (name := column(assignment.this, target.alias))
                or name != column(assignment.expression, source.alias)):
            return None
        updated.append(name)
    if len(updated) != len(set(updated)) or set(updated) != set(columns) - set(keys):
        return None
    projection = exp.select(*(node.copy() for node in values)).from_(source.copy())
    projection.meta["migration_merge_keys"] = keys
    return projection


def sql_unit(text, dialect, *, merge_draft=False, guarded_drop=None):
    """Return a read-only relational query, its logical output, and any wrapper gap."""
    trees = [tree for tree in sqlglot.parse(text, read=dialect or None) if tree is not None]
    if not trees or all(isinstance(tree, exp.Semicolon) for tree in trees):
        return None, None, None, ""
    if len(trees) != 1:
        raise ValueError("Multiple or opaque SQL statements")
    tree = trees[0]
    if isinstance(tree, exp.Create):
        subject = tree.this.this if isinstance(tree.this, exp.Schema) else tree.this
        name = relation(subject)
        kind = (tree.kind or "").lower()
        query = tree.expression
        allowed = {"this", "kind", "expression", "replace"}
        if (temporary_relation(f"temp.{name}", dialect)
                and isinstance(properties := tree.args.get("properties"), exp.Properties)
                and len(properties.expressions) == 1
                and isinstance(properties.expressions[0], exp.TemporaryProperty)
                and kind == "table"):
            name = f"temp.{name}"
            if (guarded_drop == name and isinstance(query, (exp.Select, exp.Union))
                    and not any(value for key, value in tree.args.items() if key not in allowed | {"properties"})):
                return query, name, "ephemeral", "Confirm the SQLite temporary table's script-local snapshot semantics."
            return None, name, None, "Establish SQLite temporary result lifetime and ordering before migration."
        if (kind in {"table", "view"} and isinstance(query, (exp.Select, exp.Union))
                and not any(value for key, value in tree.args.items() if key not in allowed)
                and isinstance(tree.this, exp.Table)):
            return query, name, kind, ""
        return None, name, None, "Recreate DDL, column definitions or nonrelational behavior explicitly."
    if isinstance(tree, MUTATIONS):
        subject = tree.this.this if isinstance(tree.this, exp.Schema) else tree.this
        if isinstance(tree, exp.Drop) and len(tables := tree.args.get("tables", [])) == 1:
            subject = tables[0]
        if merge_draft and isinstance(tree, exp.Merge) and (query := _merge_projection(tree)) is not None:
            return query, relation(subject), "table", (
                "Confirm non-null unique Delta merge keys, existing target backfill and repeated-load behavior.")
        return None, relation(subject) if isinstance(subject, exp.Table) else None, None, (
            "Establish ordering, keys and current-state or history semantics for this side effect."
        )
    if isinstance(tree, exp.Select) and isinstance(into := tree.args.get("into"), exp.Into):
        name = relation(into.this)
        temporary = temporary_relation(name)
        local = dialect == "tsql" and bool(re.fullmatch(r"#[A-Za-z_]\w*", name))
        allowed = {"this", "temporary"} if local else {"this"}
        if (any(value for key, value in into.args.items() if key not in allowed)
                or (temporary and not (merge_draft and local))):
            return None, name, None, "Establish temporary result lifetime and ordering before migration."
        body = tree.copy()
        body.set("into", None)
        if temporary:
            return body, name, "ephemeral", "Confirm the script-local staging lifetime and snapshot semantics."
        return body, name, "table", "Review SELECT INTO materialization semantics for the new dbt table."
    if isinstance(tree, (exp.Select, exp.Union)):
        return tree, None, None, ""
    return None, None, None, "Convert or document the procedural, configuration or operational statement."


def grouping_key_errors(select):
    """Find aggregate or impossible ordinal keys in a GROUP BY."""
    group = select.args.get("group")
    if not group:
        return []
    invalid = []
    for key in group.expressions:
        key = key.unnest()
        value = key
        if isinstance(key, exp.Literal) and key.is_int:
            index = int(key.this) - 1
            if not 0 <= index < len(select.selects):
                invalid.append(key)
                continue
            value = select.selects[index]
            if value.is_star:
                invalid.append(key)
                continue
        if any(isinstance(node, (exp.AggFunc, exp.Window))
               for node in value.walk(prune=lambda node: isinstance(node, exp.Query))):
            invalid.append(key)
    return invalid


def ungrouped_columns(select):
    """Return definite local column violations in a simple aggregate SELECT."""
    group = select.args.get("group")
    if group and any(value for key, value in group.args.items() if key != "expressions"):
        return []
    projections = [item.this if isinstance(item, exp.Alias) else item for item in select.selects]
    aliases = {item.alias.casefold(): item.this for item in select.selects if isinstance(item, exp.Alias)}
    grouped = []
    for expression in group.expressions if group else ():
        if isinstance(expression, exp.Literal) and expression.is_int and 1 <= int(expression.this) <= len(projections):
            expression = projections[int(expression.this) - 1]
        elif isinstance(expression, exp.Column) and not expression.table:
            if projection := aliases.get(expression.name.casefold()):
                grouped.append(projection.unnest())
        grouped.append(expression.unnest())

    def aggregate(node):
        return isinstance(node, exp.AggFunc) and not isinstance(node.parent, exp.Window)

    having = select.args.get("having")
    expressions = projections + ([having.this] if having else [])
    if not group and not having and not any(aggregate(node) for expression in expressions
                                            for node in expression.walk(prune=lambda node: isinstance(node, exp.Query))):
        return []
    # An unqualified reference may name a grouped column. Column binding checks its origin separately.
    simple_keys = [item for item in grouped if isinstance(item, exp.Column)]
    origin = select.args.get("from_")
    qualifier = origin.this.alias_or_name.casefold() if origin and not select.args.get("joins") else ""

    def signature(node):
        node = node.unnest()
        if isinstance(node, (exp.Add, exp.Mul)):
            return (node.key, tuple(sorted((signature(node.this), signature(node.expression)), key=repr)))
        if qualifier:
            node = node.transform(lambda child: exp.column(child.name, quoted=child.this.quoted)
                                  if isinstance(child, exp.Column) and isinstance(child.this, exp.Identifier)
                                  and child.table.casefold() == qualifier else child)
        return node.sql(normalize=True, comments=False)

    expressions_used = {signature(item) for item in grouped if not isinstance(item, exp.Column)}

    def prune(node):
        return (isinstance(node, exp.Query) or aggregate(node)
                or (expressions_used and not isinstance(node, (exp.Column, exp.Identifier))
                    and signature(node) in expressions_used))

    def possible_group_key(column):
        return any(column.name.casefold() == key.name.casefold()
                   and (not column.table or not key.table or column.table.casefold() == key.table.casefold())
                   for key in simple_keys)

    invalid = [node for expression in expressions
               for node in expression.walk(prune=prune)
               if isinstance(node, exp.Column) and not node.is_star and not possible_group_key(node)
               and not (having and expression is having.this and not node.table and node.name.casefold() in aliases)]
    return invalid + ([item for item in projections if item.is_star] if not group else [])


def declaration(text, dialect):
    """Read plain CREATE TABLE column declarations as physical input contracts."""
    if not re.search(r"\bcreate\s+table\b", text, re.I):
        return None
    tree = sqlglot.parse_one(text, read=dialect or None)
    if (not isinstance(tree, exp.Create) or tree.expression or not isinstance(tree.this, exp.Schema)
            or any(value for key, value in tree.args.items() if key not in {"this", "kind", "exists"})):
        return None
    fields = tree.this.expressions
    if not fields or not all(isinstance(field, exp.ColumnDef) and isinstance(field.kind, exp.DataType)
                             and not field.constraints for field in fields):
        return None
    name = relation(tree.this.this)
    if temporary_relation(name):
        return None
    types = {field.name: field.kind.sql(dialect=dialect or None) for field in fields}
    return (name, types) if len(types) == len(fields) else None


def sas_units(text):
    """Inventory SAS steps with full source coverage and original statement offsets."""
    cursor = 0
    for region in _sas_regions(text):
        if cursor < region[0]:
            yield cursor, region[0], None, [], "", None
        yield region
        cursor = region[1]
    if cursor < len(text):
        yield cursor, len(text), None, [], "", None


def sas_inline_evidence(text, names):
    """Recognize a bounded literal DATALINES layout with explicit delimiter and informats."""
    inline = re.search(r"(?im)^\s*(datalines|cards)\s*;[ \t]*\r?\n(.*?)^[ \t]*;[ \t]*\r?$", text, re.S)
    if not inline:
        return None
    header = strip_comments(text[:inline.start()])
    infile = re.search(r"""\binfile\s+datalines\s+dlm\s*=\s*(['"])([|,])\1\s+dsd\s+truncover\s*;""", header, re.I)
    input_list = re.search(r"\binput\s+([^;]+);", header, re.I)
    if not infile or not input_list:
        return None
    field = rf"({SAS_COLUMN})(?:\s+:([\w$]+\.))?"
    if not re.fullmatch(rf"{field}(?:\s+{field})*\s*", input_list[1].strip()):
        return None
    fields = re.findall(field, input_list[1], re.I)
    if [name.casefold() for name, _ in fields] != names:
        return None
    lengths = {name.casefold(): value for clause in re.findall(r"\blength\s+([^;]+);", header, re.I)
               for name, value in re.findall(rf"({SAS_COLUMN})\s+(\$?\d+)", clause)}
    types = []
    widths = []
    for name, informat in fields:
        kind = {"": "DOUBLE", "yymmdd10.": "DATE", "datetime19.": "TIMESTAMP_NTZ"}.get(informat.casefold())
        declared = lengths.get(name.casefold())
        if not kind and re.fullmatch(r"\$[1-9]\d*\.", informat):
            kind = "STRING"
        if not kind or declared and (declared.startswith("$") != (kind == "STRING")
                                     or kind != "STRING" and declared != "8"):
            return None
        types.append(kind)
        widths.append(min(int(informat[1:-1]), int(declared[1:])) if kind == "STRING" and declared
                      else int(informat[1:-1]) if kind == "STRING" else None)
    rows = []
    try:
        for line in inline[2].splitlines():
            parts = line.split(infile[2])
            if len(parts) != len(names) or any(not cell or any(ch in cell for ch in "'\"\\") for cell in parts):
                return None
            row = []
            for value, kind, width in zip(parts, types, widths):
                if width is not None and len(value.encode("utf-8")) > width:
                    return None
                if kind == "DOUBLE":
                    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value) or len(value) > 32:
                        return None
                    value = str(Decimal(value))
                elif kind == "DATE":
                    value = date.fromisoformat(value).isoformat()
                elif kind == "TIMESTAMP_NTZ":
                    value = datetime.strptime(value, "%d%b%Y:%H:%M:%S").isoformat(sep=" ")
                row.append(value)
            rows.append(row)
            if len(rows) > 32:
                return None
    except (ValueError, InvalidOperation):
        return None
    return {"columns": dict(zip(names, types)), "rows": rows} if rows else None


def _sas_statements(text):
    end = 0
    while (start := SAS_TRIVIA.match(text, end).end()) < len(text):
        end = next((token.end() for token in SAS_TOKEN.finditer(text, start) if token[0] == ";"), len(text))
        clean = strip_comments(text[start:end]).strip()
        if inline := SAS_INLINE.fullmatch(clean):
            terminator = ";;;;" if inline[1] else ";"
            stop = re.compile(rf"^[ \t]*{terminator}[ \t]*\r?$", re.M).search(text, end)
            end = stop.end() if stop else len(text)
        yield start, end, clean


def _sas_macro_groups(text):
    """Retain whole macro definitions and branches without reading their bodies as live steps."""
    statements = iter(_sas_statements(text))
    for record in statements:
        group = [record]
        clean = record[2]
        pair = None
        if re.match(r"%macro\b", clean, re.I):
            pair = ("macro", "mend")
        elif re.match(r"%(?:if|else|do)\b", clean, re.I) and re.search(r"%do\b", re.sub(SAS_STRING, " ", clean), re.I):
            pair = ("do", "end")
        if pair:
            depth = 1
            for row in statements:
                group.append(row)
                for token in re.findall(r"%(\w+)\b", re.sub(SAS_STRING, " ", row[2]).casefold()):
                    depth += (token == pair[0]) - (token == pair[1])
                if depth == 0:
                    break
        yield group, pair is not None


def _sas_regions(text):
    variables = {}
    block = []
    gap = ""
    proc_sql = False
    for group, opaque in _sas_macro_groups(text):
        start, end, clean = group[0]
        if assignment := SAS_LET.fullmatch(clean):
            name = assignment[1].casefold()
            value, unresolved = resolve_macros(assignment[2], variables)
            if not unresolved and SAS_LET_VALUE.fullmatch(value):
                variables[name] = value
                if not block:
                    yield start, end, None, [], "", None
                continue
            variables.pop(name, None)
            if any(token.startswith("%") for token in unresolved):
                variables.clear()
            dynamic_gap = f"Resolve the SAS %LET assignment for {name} and its dependent macros."
        elif opaque:
            if not re.match(r"%macro\b", clean, re.I):
                variables.clear()
            dynamic_gap = "Resolve SAS macros and conditional step execution before converting these outputs."
        else:
            clean, unresolved = resolve_macros(clean, variables)
            group = [(start, end, clean)]
            dynamic_gap = ""
            runtime = SAS_RUNTIME.search(re.sub(SAS_STRING, " ", clean))
            if unresolved or runtime:
                if runtime or any(token.startswith("%") for token in unresolved):
                    variables.clear()
                dynamic_gap = "Resolve SAS macros, includes or runtime-generated code before converting these outputs."
            elif SAS_INLINE.fullmatch(clean):
                dynamic_gap = "Supply the inline SAS data as an explicit input and confirm its column layout."

        header = None if opaque else re.match(r"(data|proc)\b", clean, re.I)
        if header:
            if block:
                yield _sas_step(block, gap)
            proc_sql = not dynamic_gap and re.fullmatch(r"proc\s+sql\s*;", clean, re.I) is not None
            if proc_sql:
                yield start, end, None, [], "", None
                block, gap = [], ""
            else:
                block, gap = group, dynamic_gap
            continue

        end = group[-1][1]
        follows = re.fullmatch(r"(run|quit)\s*;", clean, re.I)
        if block:
            block.extend(group)
            gap = gap or dynamic_gap
            if follows and not opaque:
                yield _sas_step(block, gap)
                block, gap = [], ""
        elif follows:
            if follows[1].casefold() == "quit":
                proc_sql = False
            yield start, end, None, [], "", None
        elif dynamic_gap:
            yield start, end, None, _sas_names(group), dynamic_gap, None
        elif proc_sql and clean != ";":
            yield _sas_sql(clean, start, end)
        else:
            gap = "Review SAS directives or statements outside a supported step." if clean != ";" else ""
            yield start, end, None, [], gap, None
    if block:
        yield _sas_step(block, gap)


def _sas_option(statement, option):
    try:
        topline = without_dataset_options(re.sub(SAS_STRING, "?", statement))
    except ValueError:
        return None
    match = re.search(rf"\b{option}\s*=\s*({SAS_NAME})(?=\s|;|$)", topline, re.I)
    return match[1] if match else None


def _sas_names(records):
    names = []
    for _, _, statement in records:
        # A macro branch can contain a literal writer without committing to its execution.
        command = re.split(r"%then\s+|^%else\s+", re.sub(SAS_STRING, "?", statement), maxsplit=1, flags=re.I)[-1]
        if header := re.match(r"data\s+(.+?);?$", command, re.I | re.S):
            try:
                targets = without_dataset_options(header[1]).split("/", 1)[0].removesuffix(";").split()
            except ValueError:
                targets = []
            names.extend(name for name in targets if name.casefold() != "_null_" and re.fullmatch(SAS_NAME, name))
        elif create := re.match(rf"create\s+(?:table|view)\s+({SAS_NAME})(?=\s|\(|;|$)", command, re.I):
            names.append(create[1])
        elif proc := re.match(r"proc\s+(\w+)\b", command, re.I):
            names.extend(name for option in ("out", "dupout") if (name := _sas_option(command, option)))
            if proc[1].casefold() == "append" and (name := _sas_option(command, "base")):
                names.append(name)
            if proc[1].casefold() == "sort" and not re.search(r"\bout\s*=", command, re.I):
                if name := _sas_option(command, "data"):
                    names.append(name)
        elif re.match(r"output\b", command, re.I) and (name := _sas_option(command, "out")):
            names.append(name)
    return list(dict.fromkeys(names))


def _sas_step(block, gap):
    start, end = block[0][0], block[-1][1]
    names = _sas_names(block)
    if gap:
        return start, end, None, names, gap, None
    if any(not clean.endswith(";") for _, _, clean in block):
        return start, end, None, names, "Recover the incomplete SAS step and confirm its outputs.", None
    body = [clean[:-1].strip() for _, _, clean in block if clean != ";"]
    if body[-1].casefold() in {"run", "quit"}:
        body.pop()
    if re.match(r"data\b", body[0], re.I):
        query, gap = _sas_data(body, names)
    else:
        query = _sas_nodupkey(body)
        gap = ("Confirm ordering that selects one stable survivor in each BY key, including SAS missing values "
               "and the original input order for ties." if query is not None
               else "Convert the SAS procedure and preserve its options, input ordering and output behavior.")
    return start, end, query, names, gap, "table"


def _sas_sql(clean, start, end):
    try:
        diagnostics = []
        query, name, kind, gap = sql_unit(clean, sas_sql_dialect("", diagnostics))
        if query is not None:
            if diagnostics:
                return start, end, None, [name] if name else [], "Resolve SAS literals or CALCULATED expressions.", kind
            typed_dates = False
            for node in list(query.find_all(exp.Var)):
                if node.meta.get("sas_literal"):
                    literal = re.fullmatch(r"""(['"])(\d{1,2}[A-Za-z]{3}\d{4})\1d""", node.name, re.I)
                    if not literal:
                        return start, end, None, [name] if name else [], "Resolve unsupported SAS typed literals.", kind
                    calendar_date = datetime.strptime(literal[2], "%d%b%Y").date().isoformat()
                    node.replace(exp.cast(exp.Literal.string(calendar_date), "DATE"))
                    typed_dates = True
                    continue
                if not node.meta.get("sas_calculated"):
                    continue
                select = node.find_ancestor(exp.Select)
                projection = next((item.this for item in select.expressions if isinstance(item, exp.Alias)
                                   and item.alias.casefold() == node.name.casefold()), None)
                if projection is None or any(item.meta.get("sas_calculated") for item in projection.find_all(exp.Var)):
                    return start, end, None, [name] if name else [], "Resolve nested SAS CALCULATED expressions.", kind
                node.replace(exp.Paren(this=projection.copy()))
            for function in list(query.find_all(exp.Anonymous)):
                if function.meta.get("sas_runtime"):
                    if not isinstance(function.parent, exp.Alias):
                        return start, end, None, [name] if name else [], "Resolve SAS runtime clock arithmetic.", kind
                    function.replace(exp.CurrentTimestamp())
            if typed_dates or re.search(r"\b(?:format|length)\s*=|\bcalculated\b|\bdatetime\s*\(", clean, re.I):
                gap = "Confirm SAS date types, projection formats, lengths, calculated values and runtime clock semantics."
    except (SqlglotError, ValueError, RecursionError):
        query, name, kind, gap = None, None, None, "Resolve unsupported SAS SQL expressions."
    if query is not None and not isinstance(query, exp.Select):
        gap = "Review SAS set operation and missing-value semantics."
    remerges = []
    for select in query.find_all(exp.Select) if query is not None else ():
        summary = any(aggregate.find_ancestor(exp.Window, exp.Select) is select
                      for clause in [*select.selects, select.args.get("having")] if clause is not None
                      for aggregate in find_all_in_scope(clause, exp.AggFunc))
        if summary:
            columns = ungrouped_columns(select) + [item for item in select.selects if item.is_star]
            if columns:
                remerges.append((select, columns))
    if remerges:
        select, columns = remerges[0]
        group = select.args.get("group")
        draft = _sas_remerge_window(select) if len(remerges) == 1 and select is query else None
        query = draft if draft is not None else query
        query.meta["migration_sas_remerge"] = {
            "grain": "detail rows with repeated summary values",
            "group_columns": [item.sql() for item in group.expressions] if group is not None else [],
            "detail_columns": list(dict.fromkeys(column.sql() for column in columns)),
            "window_draft": draft is not None,
        }
        gap = ("Confirm SAS PROC SQL remerge detail grain, repeated summary values and missing-value groups."
               if draft is not None else
               "Recreate the SAS PROC SQL remerge at its original detail grain. Confirm grouping, "
               "HAVING and duplicate behavior before handoff.")
    return start, end, query, [name] if name else _sas_names([(start, end, clean)]), gap, kind


def _sas_remerge_window(select):
    group = select.args.get("group")
    source = select.args.get("from_")
    if (not group or not group.expressions or any(value for key, value in group.args.items() if key != "expressions")
            or not source or not isinstance(source.this, exp.Table)
            or not isinstance(source.this.this, exp.Identifier)
            or any(value for key, value in select.args.items() if key not in {"expressions", "from_", "group", "where"})):
        return None

    qualifier = source.this.alias_or_name.casefold()

    def plain_column(node):
        return (isinstance(node, exp.Column) and isinstance(node.this, exp.Identifier) and not node.this.quoted
                and not node.db and not node.catalog and (not node.table or node.table.casefold() == qualifier))

    aliases = {item.alias.casefold(): item.this for item in select.selects if isinstance(item, exp.Alias)}
    if (not all(plain_column(key) and (key.table or key.name.casefold() not in aliases)
                for key in group.expressions)
            or (where := select.args.get("where")) and where.find(exp.Subquery, exp.Select, exp.AggFunc, exp.Window)):
        return None
    projections = []
    for item in select.selects:
        value = item.this if isinstance(item, exp.Alias) else item
        if plain_column(value) or isinstance(value, exp.Literal):
            projections.append(item.copy())
        elif (isinstance(item, exp.Alias) and isinstance(value, (exp.Sum, exp.Avg, exp.Min, exp.Max, exp.Count))
              and (plain_column(value.this) or isinstance(value, exp.Count)
                   and isinstance(value.this, (exp.Star, exp.Literal)))
              and not any(arg for key, arg in value.args.items() if key not in {"this", "big_int"})):
            projections.append(exp.Alias(this=exp.Window(this=value.copy(), partition_by=[
                key.copy() for key in group.expressions]), alias=item.args["alias"].copy()))
        else:
            return None
    draft = select.copy()
    draft.set("group", None)
    draft.set("expressions", projections)
    return draft


def _sas_data(body, names):
    header, *statements = body
    if len(names) == 2:
        try:
            if (routed := _sas_routed_data(header, statements, names)) is not None:
                return routed, (
                    "Confirm the SAS missing-value branch before handoff. SQL comparison and its complement "
                    "both exclude NULL. Establish which target branch should receive those rows and confirm the output layout."
                )
        except ValueError as exc:
            return None, str(exc)
    if len(names) == 1 and statements:
        if (stack := _sas_stack(header, statements, names[0])) is not None:
            return stack
        if (len(statements) >= 2 and re.fullmatch(rf"data\s+{SAS_NAME}", header, re.I)
                and (ordered := _sas_running_total(statements)) is not None):
            return ordered, (
                "Confirm ordering within each SAS BY group, a unique tie-breaker, special missing values, "
                "accumulator precision and the output column layout."
            )
        try:
            if (projection := _data_projection(header, statements)) is not None:
                return projection, ("Confirm SAS column order, character width and missing-value behavior. "
                                    "Verify input column availability and renamed-column uniqueness against the layout.")
        except ValueError as exc:
            return None, str(exc)
    if any(re.match(r"merge\b", statement, re.I) for statement in statements):
        return None, ("Implement SAS match MERGE/BY row state manually. Confirm sorted inputs, repeated BY keys, "
                      "overlapping columns, retained values and output conditions against the original statements.")
    return None, "Implement SAS row state, assignments and output conditions for each dataset."


def _sas_routed_data(header, statements, names):
    dataset = rf"{SAS_NAME}(?:\s*\([^()]+\))?"
    targets = re.fullmatch(rf"data\s+({dataset})\s+({dataset})", header, re.I)
    if targets is None:
        return None
    projections = [statement for statement in statements if re.match(r"(?:keep|drop)\s+", statement, re.I)]
    control = [statement for statement in statements if statement not in projections]
    if len(control) != 3:
        return None
    source, positive, negative = control
    branch = re.fullmatch(rf"if\s+({SAS_COLUMN}\s*(?:<=|>=|<|>|=)\s*-?\d+)\s+then\s+output\s+({SAS_NAME})",
                          positive, re.I)
    other = re.fullmatch(rf"else\s+output\s+({SAS_NAME})", negative, re.I)
    if (not re.fullmatch(rf"set\s+{SAS_NAME}", source, re.I) or not branch or not other
            or statements.index(negative) != statements.index(positive) + 1
            or {branch[2].casefold(), other[1].casefold()} != {name.casefold() for name in names}
            or branch[2].casefold() == other[1].casefold()):
        return None
    queries = {}
    for name, target in zip(names, targets.groups()):
        query = _data_projection(f"data {target}", [source, *projections, f"if {branch[1]}"],
                                 allow_passthrough=True)
        if query is None:
            return None
        if name.casefold() == other[1].casefold():
            condition = query.args["where"].this
            query = query.where(exp.Not(this=exp.Paren(this=condition.copy())), append=False)
        queries[name] = query
    return queries


def _sas_stack(header, statements, output):
    literal_stack = rf"set\s+({SAS_NAME}(?:\s+{SAS_NAME})+)"
    for index, statement in enumerate(statements):
        if not re.match(r"set\s+", statement, re.I):
            continue
        try:
            inputs = re.fullmatch(literal_stack, without_dataset_options(statement), re.I)
        except ValueError:
            continue
        if inputs:
            break
    else:
        return None

    review = ("Confirm SAS SET concatenation input layouts, column order, character widths and program data "
              "vector missing-value behavior. Preserve input sequence and within-input row ordering where needed.")
    unsupported = ("Recreate SAS SET concatenation with dataset options, self-references or additional statements "
                   "manually. " + review)
    sources = inputs[1].casefold().split()
    if (not re.fullmatch(literal_stack, statement, re.I)
            or any(source.removeprefix("work.") == output.casefold().removeprefix("work.") for source in sources)):
        return None, unsupported
    rest = statements[:index] + statements[index + 1:]
    keep = re.fullmatch(r"keep\s+(.+)", rest[0], re.I | re.S) if len(rest) == 1 else None
    if rest and not keep:
        return None, unsupported
    try:
        options = _dataset(header, "data")
        if options["drop"] or options["rename"] or (options["keep"] and keep):
            return None, unsupported
        columns = _names(keep[1]) if keep else options["keep"]
    except ValueError:
        return None, unsupported
    if not columns or len(set(columns)) != len(columns) or {"_n_", "_error_"} & set(columns):
        return None, "Provide a literal KEEP list to establish the SAS SET concatenation output layout. " + review
    branches = [exp.select(*(exp.column(column) for column in columns)).from_(exp.to_table(source))
                for source in sources]
    query = branches[0]
    for branch in branches[1:]:
        query = exp.Union(this=query, expression=branch, distinct=False)
    query.meta["migration_sas_stack"] = {"columns": columns}
    return query, review


def _sas_by(statement):
    if not (match := re.fullmatch(r"by\s+(.+)", statement, re.I | re.S)):
        return None
    words = iter(match[1].casefold().split())
    order = []
    for word in words:
        direction = "desc" if word == "descending" else "asc"
        column = next(words, "") if direction == "desc" else word
        if (not re.fullmatch(SAS_COLUMN, column) or column in {"descending", "notsorted", "groupformat", "_all_"}
                or any(item["column"] == column for item in order)):
            return None
        order.append({"column": column, "direction": direction})
    return order


def _sas_nodupkey(body):
    if len(body) != 2 or not (order := _sas_by(body[1])):
        return None
    header = body[0]
    if not re.match(r"proc\s+sort\s+", header, re.I):
        return None
    options = re.sub(r"^proc\s+sort\s+", "", header, flags=re.I)
    source = _sas_option(options, "data")
    output = _sas_option(options, "out")
    flags = re.sub(rf"\b(?:data|out)\s*=\s*{SAS_NAME}(?=\s|$)", "", options, flags=re.I).casefold().split()
    if (not source or not output or source.casefold().removeprefix("work.") == output.casefold().removeprefix("work.")
            or flags not in (["nodupkey"], ["nodupkey", "equals"], ["equals", "nodupkey"])
            or len(re.findall(r"\b(?:data|out)\s*=", options, re.I)) != 2):
        return None
    query = exp.select("*").from_(exp.to_table(source.casefold()))
    query.meta["migration_sas_order"] = {
        "kind": "nodupkey", "source": source.casefold(), "keys": [item["column"] for item in order], "by_order": order,
    }
    return query


def _sas_running_total(statements):
    source = re.fullmatch(rf"set\s+({SAS_NAME})", statements[0], re.I)
    if not source:
        return None
    body = [statement.casefold() for statement in statements[1:]]
    keep = []
    if match := re.fullmatch(rf"keep\s+({SAS_COLUMN}(?:\s+{SAS_COLUMN})*)", body[-1]):
        keep = match[1].split()
        body.pop()
    retained = None
    statements = []
    for statement in body:
        if (match := re.fullmatch(rf"retain\s+({SAS_COLUMN})(?:\s+0)?", statement)) and retained is None:
            retained = match[1]
        else:
            statements.append(statement)
    if len(statements) != 3 or not (by := _sas_by(statements[0])):
        return None
    reset = re.fullmatch(rf"if\s+first\.({SAS_COLUMN})\s+then\s+({SAS_COLUMN})\s*=\s*0", statements[1])
    additive = re.fullmatch(rf"({SAS_COLUMN})\s*\+\s*({SAS_COLUMN})", statements[2])
    assigned = re.fullmatch(rf"({SAS_COLUMN})\s*=\s*sum\s*\(\s*\1\s*,\s*({SAS_COLUMN})\s*\)", statements[2])
    update = additive or assigned
    columns = [item["column"] for item in by]
    if (not reset or not update or reset[1] not in columns or reset[2] != update[1]
            or update[1] == update[2] or update[1] in columns or retained not in (None, update[1])
            or (assigned and retained is None) or (keep and update[1] not in keep)):
        return None
    query = exp.select("*").from_(exp.to_table(source[1].casefold()))
    query.meta["migration_sas_order"] = {
        "kind": "running_total", "source": source[1].casefold(), "keys": columns[:columns.index(reset[1]) + 1],
        "by_order": by, "reset": reset[1], "value": update[2], "output": update[1], "keep": keep,
    }
    return query


def sas_ordered_query(spec, order):
    """Build a review draft from engineer-confirmed, literal within-group order."""
    if not isinstance(order, (tuple, list)) or not 1 <= len(order) <= 32:
        raise ValueError("Provide the confirmed SAS row ordering, including a stable tie-breaker.")
    normalized = []
    names = set(spec["keys"])
    if spec["kind"] == "running_total":
        names.add(spec["output"])
    for item in order:
        if not isinstance(item, dict) or not isinstance(item.get("column"), str) or item.get("direction") not in ("asc", "desc"):
            raise ValueError("Each ordering entry needs a literal column and ASC or DESC direction.")
        column = item["column"].casefold()
        if not re.fullmatch(SAS_COLUMN, column) or column in names:
            raise ValueError("Use distinct literal input ordering columns outside the BY partition and generated accumulator.")
        names.add(column)
        normalized.append({"column": column, "direction": item["direction"]})
    required = spec["by_order"][len(spec["keys"]):]
    if normalized[:len(required)] != required:
        raise ValueError("Preserve the SAS BY columns and directions after the reset key before appending tie-breakers.")
    window = {
        "partition_by": [exp.column(key) for key in spec["keys"]],
        "order": exp.Order(expressions=[
            exp.Ordered(this=exp.column(item["column"]), desc=item["direction"] == "desc",
                        nulls_first=item["direction"] == "asc") for item in normalized
        ]),
    }
    source = exp.to_table(spec["source"])
    if spec["kind"] == "nodupkey":
        rank = exp.Window(this=exp.RowNumber(), **window)
        return exp.select("*").from_(source).qualify(exp.EQ(this=rank, expression=exp.Literal.number(1)))
    if spec["kind"] != "running_total":
        raise ValueError("Unknown SAS order-dependent operation.")
    amount = exp.Coalesce(this=exp.column(spec["value"]), expressions=[exp.Literal.number(0)])
    running = exp.Window(this=exp.Sum(this=amount), **window,
                         spec=exp.WindowSpec(kind="ROWS", start="UNBOUNDED", start_side="PRECEDING", end="CURRENT ROW"))
    total = exp.alias_(running, spec["output"])
    columns = [total if name == spec["output"] else exp.column(name) for name in spec["keep"]] or ["*", total]
    return exp.select(*columns).from_(source)


def _data_projection(header, statements, *, allow_passthrough=False):
    sets = [(index, statement) for index, statement in enumerate(statements) if re.match(r"set\b", statement, re.I)]
    if len(sets) != 1:
        return None
    set_index, set_statement = sets[0]

    def dataset_options(statement, keyword):
        try:
            options = _dataset(statement, keyword)
            if options["where"] is not None:
                raise ValueError("Review the input WHERE= predicate and its evaluation order.")
            return options
        except ValueError as exc:
            raise ValueError(
                f"Resolve the {keyword.upper()} dataset options. Use one literal dataset with plain "
                f"KEEP=, DROP= or RENAME= only. {exc}"
            ) from exc

    output = dataset_options(header, "data")
    inputs = dataset_options(set_statement, "set")
    source = re.match(rf"set\s+({SAS_NAME})", set_statement, re.I)
    if not source:
        return None
    options, option_statements = {}, set()
    for index, statement in enumerate(statements):
        if match := re.match(r"(keep|drop|rename)\b(?!\s*=)\s*(.*)", statement, re.I | re.S):
            key = match[1].casefold()
            if key in options:
                raise ValueError(f"Combine repeated SAS {key.upper()} statements into one literal list.")
            options[key] = _renames(match[2]) if key == "rename" else _names(match[2])
            option_statements.add(index)
    if (not allow_passthrough and not options
            and not any(spec[key] for spec in (inputs, output) for key in ("keep", "drop", "rename"))):
        return None

    values, hidden = {}, set()
    known = False

    def variable(name):
        if name in values:
            return values[name].copy()
        if known or name in hidden:
            raise ValueError(f"Resolve SAS variable {name} after the preceding KEEP, DROP and RENAME operations.")
        return exp.column(name)

    def project(spec):
        nonlocal values, known
        keep, drop, rename = spec.get("keep"), set(spec.get("drop", ())), spec.get("rename", {})
        if {"_n_", "_error_"} & (set(keep or ()) | drop | rename.keys() | set(rename.values())):
            raise ValueError("Resolve references to SAS automatic DATA-step variables _N_ and _ERROR_.")
        if unavailable := (drop if known else drop & hidden) - values.keys():
            raise ValueError("Resolve SAS DROP variables removed in an earlier phase: " + ", ".join(sorted(unavailable)))
        if keep is not None:
            if len(set(keep)) != len(keep) or set(keep) & drop:
                raise ValueError("Resolve repeated or conflicting SAS KEEP and DROP variables in the same phase.")
            values = {name: variable(name) for name in keep}
            known = True
        if set(rename) & drop or any(new in values and new not in rename and new not in drop for new in rename.values()):
            raise ValueError("Resolve conflicting SAS DROP and RENAME variables or duplicate output names.")
        renamed = {new: variable(old) for old, new in rename.items()}
        if not known:
            hidden.update(name for name in drop | rename.keys() if name not in values)
        values = {rename.get(name, name): value for name, value in values.items() if name not in drop}
        values.update(renamed)

    def expression(value):
        tree = sqlglot.parse_one(value, into=exp.Condition)
        classes = {"Column", "Identifier", "Literal", "Paren", "Add", "Sub", "Mul",
                   "Neg", "EQ", "NEQ", "LT", "LTE", "GT", "GTE", "And", "Or", "Not"}
        if any(type(node).__name__ not in classes for node in tree.walk()) or any(
            c.table or re.fullmatch(r"(?:first|last|_n_|_error_)", c.name, re.I) for c in tree.find_all(exp.Column)
        ):
            raise ValueError("Unsupported SAS scalar expression")

        def substitute(node):
            if not isinstance(node, exp.Column):
                return node
            value = variable(node.name.casefold())
            return value if isinstance(value, (exp.Column, exp.Literal, exp.Paren)) else exp.Paren(this=value)

        return tree.transform(substitute)

    try:
        project(inputs)
        filters = []
        assigned = False
        for index, statement in enumerate(statements):
            if index == set_index or index in option_statements:
                continue
            if index < set_index:
                return None
            if match := re.fullmatch(r"if\s+(.+)", statement, re.I | re.S):
                filters.append(expression(match[1]))
            elif match := re.fullmatch(rf"({SAS_COLUMN})\s*=\s*(.+)", statement, re.S):
                name = match[1].casefold()
                if name in {"_n_", "_error_"}:
                    return None
                values[name] = expression(match[2])
                assigned = True
            else:
                return None
        # DATA-step KEEP/DROP and RENAME use the body names. Output options see the statement RENAME names.
        project(options)
        project(output)
        if known and not values:
            raise ValueError("Confirm at least one output column after applying the SAS KEEP and DROP operations.")
        if not known and assigned:
            raise ValueError("Provide an explicit SAS KEEP list to establish the output layout after assignments.")
        columns = [value if isinstance(value, exp.Column) and value.name == name else exp.alias_(value, name)
                   for name, value in values.items()]
        if not known:
            columns.insert(0, exp.Star(except_=[exp.column(name) for name in sorted(hidden)]))
        query = exp.select(*columns).from_(exp.to_table(source[1].casefold()))
        for predicate in filters:
            query = query.where(predicate)
        return query
    except (SqlglotError, RecursionError):
        return None


def project_yaml(text):
    """Read inert dbt metadata. No template evaluation or configuration inheritance."""
    if any(marker in text for marker in ("{{", "{%", "{#")):
        raise ValueError("Templated dbt configuration requires review")
    return read_yaml(text)[0]


def dbt_model_name(path):
    return PurePosixPath(path).stem
