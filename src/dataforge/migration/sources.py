"""Bounded lexical inventory and conservative SQL/SAS/dbt source lowering."""
import re
from pathlib import PurePosixPath

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.tokens import TokenType

from dataforge.dbt.yaml import read_yaml

DYNAMIC_SAS = re.compile(r"%[a-z_]\w*|&[a-z_]\w*|\bdatalines\d*\b|\bcards\d*\b", re.I)
SAS_NAME = r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?"
SAS_OUTPUT = re.compile(rf"\b(?:DATA\s+|CREATE\s+(?:TABLE|VIEW)\s+)({SAS_NAME}(?:\s+{SAS_NAME})*)", re.I)
SAS_COMMENT = re.compile(r"/\*.*?\*/|(?:^|(?<=;))\s*\*[^;]*;", re.S)
SAS_BLOCK_OR_STRING = re.compile(r'''/\*.*?\*/|'(?:[^']|'')*'|"(?:[^"]|"")*"''', re.S)
MUTATIONS = (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Drop, exp.Alter, exp.TruncateTable)
SECRET_FILE = re.compile(r"(?:^|/)(?:profiles\.ya?ml|secrets\.[^/]+|\.env[^/]*|[^/]+\.(?:pem|key|pfx))(?:$|/)", re.I)
SCRIPT_BLOCK = re.compile(r"\b(?:create\s+(?:(?:or\s+replace|or\s+alter)\s+)?(?:proc(?:edure)?|function|trigger)"
                          r"|begin\b|do\s+\$\$)", re.I)
SQL_IDENTIFIER = r'(?:[A-Za-z_][\w$]*|"(?:""|[^"])+"|`(?:``|[^`])+`|\[[^\]]+\])'
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


def sql_regions(text, dialect, *, protect_blocks=True):
    """Split top-level SQL and keep an uncertain compound suffix together."""
    start = 0
    first_token = True
    try:
        tokens = sqlglot.tokenize(text, read=dialect or None)
    except (SqlglotError, ValueError, RecursionError):
        yield 0, len(text), False
        return
    for token in tokens:
        if protect_blocks and first_token and SCRIPT_BLOCK.match(text, token.start):
            yield start, len(text), True
            return
        first_token = token.token_type == TokenType.SEMICOLON
        if first_token:
            end = token.end + 1
            yield start, end, False
            start = end
    if start < len(text):
        yield start, len(text), False


def relation(table):
    if not isinstance(table, exp.Table) or not all(isinstance(p, exp.Identifier) for p in table.parts):
        raise ValueError("Dynamic, external or function-based table reference")
    return ".".join(p.sql() if p.quoted else p.name.casefold() for p in table.parts)


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
    return list(dict.fromkeys(names))


def sql_unit(text, dialect):
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
        if (kind in {"table", "view"} and isinstance(query, (exp.Select, exp.Union))
                and not any(value for key, value in tree.args.items() if key not in allowed)
                and isinstance(tree.this, exp.Table)):
            return query, name, kind, ""
        return None, name, None, "Recreate DDL, column definitions or nonrelational behavior explicitly."
    if isinstance(tree, MUTATIONS):
        subject = tree.this.this if isinstance(tree.this, exp.Schema) else tree.this
        return None, relation(subject) if isinstance(subject, exp.Table) else None, None, (
            "Establish ordering, keys and current-state or history semantics for this side effect."
        )
    if isinstance(tree, exp.Select) and isinstance(into := tree.args.get("into"), exp.Into):
        name = relation(into.this)
        if any(value for key, value in into.args.items() if key != "this") or into.this.name.startswith("#"):
            return None, name, None, "Establish temporary result lifetime and ordering before migration."
        body = tree.copy()
        body.set("into", None)
        return body, name, "table", "Review SELECT INTO materialization semantics for the new dbt table."
    if isinstance(tree, (exp.Select, exp.Union)):
        return tree, None, None, ""
    return None, None, None, "Convert or document the procedural, configuration or operational statement."


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
    types = {field.name: field.kind.sql(dialect=dialect or None) for field in fields}
    return (name, types) if len(types) == len(fields) else None


def sas_units(text):
    """Keep SAS execution blocks together. Only lower a narrow stateless subset."""
    visible = SAS_BLOCK_OR_STRING.sub(lambda match: " " if match[0].startswith("/*") else match[0], text)
    if DYNAMIC_SAS.search(visible):
        names = []
        for match in SAS_OUTPUT.finditer(visible):
            names.extend(re.split(r"\s+", match[1].strip()))
        yield 0, len(text), None, list(dict.fromkeys(names)), "Resolve macros, includes or inline data before conversion.", None
        return
    block = None
    for start, end in spans(text):
        clean = SAS_COMMENT.sub(" ", text[start:end]).strip()
        header = re.match(r"(data|proc)\b", clean, re.I)
        if header and block is None:
            block = (start, clean)
            if re.fullmatch(r"proc\s+sql\s*;", clean, re.I):
                yield start, end, None, [], "", None
            continue
        if block is not None:
            first, statement = block
            data = statement.lower().startswith("data")
            proc_sql = bool(re.match(r"proc\s+sql\s*;", statement, re.I))
            if proc_sql and not re.match(r"(?:quit|run)\s*;", clean, re.I):
                yield from _sas_sql(text, start, end)
            elif re.match(r"(?:quit|run)\s*;", clean, re.I):
                if data:
                    yield _sas_data(text, first, end)
                elif proc_sql:
                    yield start, end, None, [], "", None
                else:
                    names = re.findall(rf"\bout\s*=\s*({SAS_NAME})", text[first:end], re.I)
                    yield first, end, None, names, "Convert SAS procedure and its options manually.", None
                block = None
            continue
        if re.fullmatch(r"(?:quit|run)\s*;", clean, re.I):
            yield start, end, None, [], "", None
            continue
        yield start, end, None, [], "Review SAS directives or statements outside a supported step." if clean else "", None
    if block:
        start, statement = block
        if re.match(r"proc\s+sql\s*;", statement, re.I):
            yield len(text), len(text), None, [], "Confirm termination and options of the SAS SQL procedure.", None
        else:
            yield start, len(text), None, [], "Recover the incomplete SAS step and identify all outputs.", None


def _sas_sql(text, start, end):
    try:
        query, name, kind, gap = sql_unit(text[start:end], "")
    except (SqlglotError, ValueError, RecursionError):
        query, name, kind, gap = None, None, None, "Resolve unsupported SAS SQL expressions."
    if not name and (match := re.search(rf"\bcreate\s+(?:table|view)\s+({SAS_NAME})", text[start:end], re.I)):
        name = match[1]
    if query is not None and not isinstance(query, exp.Select):
        gap = "Review SAS set operation and missing-value semantics."
    yield start, end, query, [name] if name else [], gap, kind


def _sas_data(text, start, end):
    clean = SAS_COMMENT.sub(" ", text[start:end]).strip()
    header = re.match(r"data\s+([^;]*);", clean, re.I)
    if not header:
        return start, end, None, [], "Identify DATA step outputs.", None
    # Dataset options and output switches remain part of the manual obligation.
    names = re.findall(SAS_NAME, re.sub(r"\([^)]*\)", "", header[1]).split("/", 1)[0])
    names = [name for name in names if name.casefold() != "_null_"]
    statements = [statement.strip() for statement in clean[header.end():].split(";") if statement.strip()]
    projection = None
    if (len(names) == 2 and len(statements) == 4 and statements[-1].casefold() == "run"
            and re.fullmatch(rf"data\s+{SAS_NAME}\s+{SAS_NAME}\s*;", header[0], re.I)):
        source = re.fullmatch(rf"set\s+({SAS_NAME})", statements[0], re.I)
        branch = re.fullmatch(r"if\s+([A-Za-z_]\w*\s*(?:<=|>=|<|>|=)\s*-?\d+)\s+then\s+output\s+([A-Za-z_]\w*)",
                              statements[1], re.I)
        other = re.fullmatch(r"else\s+output\s+([A-Za-z_]\w*)", statements[2], re.I)
        if (source and branch and other and branch[2].casefold() != other[1].casefold()
                and {branch[2].casefold(), other[1].casefold()} == {name.casefold() for name in names}):
            condition = sqlglot.parse_one(branch[1], into=exp.Condition)
            queries = {
                branch[2].casefold(): exp.select("*").from_(source[1]).where(condition.copy()),
                other[1].casefold(): exp.select("*").from_(source[1]).where(exp.Not(this=exp.Paren(this=condition))),
            }
            return start, end, queries, names, (
                "Confirm the SAS missing-value branch before handoff. SQL comparison and its complement "
                "both exclude NULL. Establish which target branch should receive those rows and confirm the output layout."
            ), "table"
    if (len(names) == 1 and len(statements) >= 3 and statements[-1].casefold() == "run"
            and re.fullmatch(rf"data\s+{SAS_NAME}\s*;", header[0], re.I)):
        projection = _data_projection(statements[:-1])
    return start, end, projection, names, (
        "Confirm SAS column order, character width and missing-value behavior."
        if projection is not None else "Implement SAS row state, assignments and output conditions for each dataset."
    ), "table"


def _data_projection(statements):
    source = re.fullmatch(rf"set\s+({SAS_NAME})", statements[0], re.I)
    if not source:
        return None
    keep = re.fullmatch(r"keep\s+([A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*)", statements[-1], re.I)
    if not keep:
        return None
    variables = {}
    filters = []

    def expression(value):
        tree = sqlglot.parse_one(value, into=exp.Condition)
        classes = {"Column", "Identifier", "Literal", "Paren", "Add", "Sub", "Mul",
                   "Neg", "EQ", "NEQ", "LT", "LTE", "GT", "GTE", "And", "Or", "Not"}
        if any(type(node).__name__ not in classes for node in tree.walk()) or any(
            c.table or re.fullmatch(r"(?:first|last|_n_|_error_)", c.name, re.I) for c in tree.find_all(exp.Column)
        ):
            raise ValueError("Unsupported SAS scalar expression")
        return tree.transform(lambda node: variables[node.name.casefold()].copy()
                              if isinstance(node, exp.Column) and node.name.casefold() in variables else node)

    try:
        for statement in statements[1:-1]:
            if match := re.fullmatch(r"if\s+(.+)", statement, re.I | re.S):
                filters.append(expression(match[1]))
            elif match := re.fullmatch(r"([A-Za-z_]\w*)\s*=\s*(.+)", statement, re.S):
                name = match[1].casefold()
                variables[name] = expression(match[2])
            else:
                return None
        query = exp.select(*(exp.alias_(variables[name.casefold()], name) if name.casefold() in variables
                             else exp.column(name) for name in keep[1].split())).from_(source[1])
        for predicate in filters:
            query = query.where(predicate)
        return query
    except (SqlglotError, ValueError, RecursionError):
        return None


def project_yaml(text):
    """Read inert dbt metadata. No template evaluation or configuration inheritance."""
    if any(marker in text for marker in ("{{", "{%", "{#")):
        raise ValueError("Templated dbt configuration requires review")
    return read_yaml(text)[0]


def dbt_model_name(path):
    return PurePosixPath(path).stem
