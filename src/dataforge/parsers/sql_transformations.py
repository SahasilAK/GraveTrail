"""Conservative, scope-preserving SQL transformation facts with original evidence."""
from __future__ import annotations

from collections import Counter
from typing import Any

from sqlglot import Dialect, exp
from sqlglot.optimizer.scope import Scope


def identifier(node: exp.Expression | None) -> str:
    """Render an SQLGlot identifier while preserving quoted spelling.

    Args:
        node: Identifier-like expression, if available.

    Returns:
        SQL name text, or an empty string for ``None``."""
    if isinstance(node, exp.Identifier):
        return '"' + node.name.replace('"', '""') + '"' if node.args.get("quoted") else node.name
    return node.name if node is not None else ""


def relation(table: exp.Table) -> str:
    """Render a relation name with SQL Server temporary prefixes preserved.

    Args:
        table: SQLGlot table expression.

    Returns:
        Qualified relation name with quoting for dotted identifier parts."""
    parts = []
    for part in table.parts:
        prefix = "##" if part.args.get("global_") else "#" if part.args.get("temporary") else ""
        name = prefix + part.name
        parts.append('"' + name.replace('"', '""') + '"' if "." in name else name)
    return ".".join(parts)


def _projection_ranges(code: str, dialect: Dialect) -> list[tuple[int, int]]:
    """Find source character ranges for SELECT projection expressions.

    Token boundaries preserve parentheses and comments absent from AST metadata.

    Args:
        code: Original SQL statement text.
        dialect: SQLGlot dialect used to tokenize the statement.

    Returns:
        Start/end character offsets for projection ranges."""
    tokens = dialect.tokenize(code)
    ranges = []
    endings = {"FROM", "INTO", "WHERE", "GROUP_BY", "HAVING", "QUALIFY", "WINDOW",
               "ORDER_BY", "LIMIT", "OFFSET", "FETCH", "UNION", "EXCEPT", "INTERSECT", "SEMICOLON"}
    for index, token in enumerate(tokens):
        if token.token_type.name != "SELECT":
            continue
        cursor = index + 1
        if cursor < len(tokens) and tokens[cursor].token_type.name in {"DISTINCT", "ALL"}:
            cursor += 1
        if cursor < len(tokens) and tokens[cursor].token_type.name in {"ON", "TOP"}:
            cursor += 1
            if cursor < len(tokens) and tokens[cursor].token_type.name == "L_PAREN":
                prefix_depth = 1
                cursor += 1
                while cursor < len(tokens) and prefix_depth:
                    prefix_depth += (tokens[cursor].token_type.name == "L_PAREN") - (tokens[cursor].token_type.name == "R_PAREN")
                    cursor += 1
            else:
                cursor += 1
            if cursor < len(tokens) and tokens[cursor].token_type.name == "PERCENT":
                cursor += 1
            if cursor + 1 < len(tokens) and tokens[cursor].token_type.name == "WITH" and tokens[cursor + 1].text.upper() == "TIES":
                cursor += 2
        start = tokens[cursor].start if cursor < len(tokens) else token.end + 1
        depth = 0
        for next_token in tokens[cursor:]:
            kind = next_token.token_type.name
            if depth == 0 and (kind in endings or kind == "R_PAREN"):
                ranges.append((start, next_token.start))
                break
            if depth == 0 and kind == "COMMA":
                ranges.append((start, next_token.start))
                start = next_token.end + 1
            if kind == "L_PAREN":
                depth += 1
            elif kind == "R_PAREN":
                depth -= 1
        else:
            ranges.append((start, len(code)))
    return ranges


def _original_range(projection: exp.Expression, ranges: list[tuple[int, int]], code: str) -> tuple[int, int] | None:
    """Find the smallest original source range containing a parsed projection.

    Args:
        projection: Parsed SQL projection.
        ranges: Candidate source ranges.
        code: Original SQL statement text.

    Returns:
        The trimmed source offsets, or ``None`` if no range contains the projection.
    """
    offsets = [(n.meta["start"], n.meta["end"]) for n in projection.walk()
               if "start" in n.meta and "end" in n.meta]
    if not offsets:
        return None
    low, high = min(a for a, _ in offsets), max(b for _, b in offsets)
    matches = [(a, b) for a, b in ranges if a <= low and high < b]
    if not matches:
        return None
    a, b = min(matches, key=lambda item: item[1] - item[0])
    while a < b and code[a].isspace():
        a += 1
    while b > a and code[b - 1].isspace():
        b -= 1
    return a, b


def _original(projection: exp.Expression, ranges: list[tuple[int, int]], code: str) -> str:
    """Recover the original source text covering one parsed projection.

    Args:
        projection: Parsed projection expression.
        ranges: Candidate source ranges returned by ``_projection_ranges``.
        code: Original SQL statement text.

    Returns:
        The smallest containing source range, or an empty string when unavailable."""
    span = _original_range(projection, ranges, code)
    return code[span[0]:span[1]] if span is not None else ""


def _record(table: str, column: str, scope: str, expression: str, category: str="expression", coverage: list[str] | None=None, **extra: Any) -> dict[str, Any]:
    """Build one SQL column derivation record with its evidence status.

    Args:
        table: Target table or intermediate query name.
        column: Target output column name.
        scope: Query scope identifier.
        expression: Original projection text.
        category: Transformation category.
        coverage: Unresolved conditions associated with the record.
        **extra: Additional fields specific to a record type.

    Returns:
        Derivation mapping in the persisted parser result shape."""
    coverage = list(coverage or [])
    return {"target_table": table, "target_column": column, "scope": scope, "target_version": "",
            "expression": expression, "category": category, "status": "unresolved" if coverage else "verified",
            "inputs": [], "coverage": coverage, "branch": 0, "ordinal": 0, **extra}


def _write_ranges(code: str, dialect: Dialect, *, values: bool = False) -> list[tuple[int, int]]:
    """Recover assignment or first VALUES-row spans without AST regeneration."""
    tokens = dialect.tokenize(code)
    keyword = 'VALUES' if values else 'SET'
    index = next((i for i, token in enumerate(tokens) if token.token_type.name == keyword), None)
    if index is None:
        return []
    cursor = index + (2 if values else 1)
    if cursor >= len(tokens):
        return []
    start, depth, ranges = tokens[cursor].start, 0, []
    for token in tokens[cursor:]:
        kind = token.token_type.name
        if depth == 0 and (kind in {'WHERE', 'RETURNING', 'SEMICOLON'} or values and kind == 'R_PAREN'):
            ranges.append((start, token.start))
            break
        if depth == 0 and kind == 'COMMA':
            ranges.append((start, token.start))
            start = token.end + 1
        if kind == 'L_PAREN':
            depth += 1
        elif kind == 'R_PAREN':
            depth -= 1
    else:
        ranges.append((start, len(code)))
    return [(a + len(code[a:b]) - len(code[a:b].lstrip()), b - len(code[a:b]) + len(code[a:b].rstrip()))
            for a, b in ranges]


def _postgres_update(tree: exp.Update, code: str, dialect: Dialect, target: exp.Table) -> list[dict[str, Any]] | None:
    """Map a narrow SET slice to isolated old values; never infer write order."""
    if dialect.__class__.__name__.casefold() != 'postgres':
        return None
    if (any(value for key, value in tree.args.items() if key not in {'this', 'expressions', 'where'})
            or not isinstance(target.this, exp.Identifier)
            or any(value for key, value in target.args.items() if key not in {'this', 'db', 'catalog', 'alias'})):
        return None
    assignments = tree.expressions
    if not assignments or any(not isinstance(a, exp.EQ) or not isinstance(a.this, exp.Column)
                              or a.this.table or not isinstance(a.this.this, exp.Identifier) for a in assignments):
        return None
    names = [identifier(a.this.this) for a in assignments]
    keys = [name[1:-1] if name.startswith('"') else name.casefold() for name in names]
    if len(set(keys)) != len(keys):
        return None
    scalar = (exp.Column, exp.Identifier, exp.Literal, exp.Null, exp.Boolean, exp.Paren,
              exp.Neg, exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Mod)
    predicate = (*scalar, exp.Where, exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE,
                 exp.And, exp.Or, exp.Not, exp.Is)
    nodes = [(a.expression, scalar) for a in assignments]
    if tree.args.get('where') is not None:
        nodes.append((tree.args['where'], predicate))
    allowed_qualifier = target.args.get('alias')
    allowed_qualifier = allowed_qualifier.this if allowed_qualifier is not None else target.this
    for node, allowed in nodes:
        if any(not isinstance(child, allowed) for child in node.walk()):
            return None
        for column in node.find_all(exp.Column):
            qualifier = column.args.get('table')
            if (column.name.upper() == 'DEFAULT' and not column.this.args.get('quoted')
                    or column.args.get('db') or column.args.get('catalog') or (
                    qualifier is not None and identifier(qualifier) != identifier(allowed_qualifier))):
                return None
    spans = _write_ranges(code, dialect)
    if len(spans) != len(assignments):
        return None
    table = relation(target)
    result = []
    for ordinal, (assignment, name, (start, end)) in enumerate(zip(assignments, names, spans)):
        category = 'direct' if isinstance(assignment.expression, exp.Column) else 'expression'
        if not list(assignment.expression.find_all(exp.Column)):
            category = 'constant'
        record = _record(table, name, '', code[start:end], category, [
            'UPDATE prior rows and unchanged columns are not established; partial writes and writer order are unresolved'],
            ordinal=ordinal, _expression_offset=start)
        for node, role in [(assignment.expression, 'value'), (tree.args.get('where'), 'row_filter')]:
            if node is not None:
                for column in node.find_all(exp.Column):
                    item = {'table': table, 'column': identifier(column.this), 'role': role,
                            'scope': 'update:prior', 'version': 'prior'}
                    if item not in record['inputs']:
                        record['inputs'].append(item)
        record['inputs'].append({'table': table, 'column': '', 'role': 'rowset',
                                 'scope': 'update:prior', 'version': 'prior'})
        result.append(record)
    return result


def _postgres_values(tree: exp.Insert, code: str, dialect: Dialect, target: exp.Table) -> list[dict[str, Any]] | None:
    """Map one explicit literal row while retaining unknown existing target rows."""
    if dialect.__class__.__name__.casefold() != 'postgres':
        return None
    schema, values = tree.this, tree.expression
    if (not isinstance(schema, exp.Schema) or not isinstance(values, exp.Values)
            or len(values.expressions) != 1
            or any(value for key, value in tree.args.items() if key not in {'this', 'expression'})
            or not isinstance(target.this, exp.Identifier)
            or any(value for key, value in target.args.items() if key not in {'this', 'db', 'catalog'})):
        return None
    columns, row = schema.expressions, values.expressions[0]
    if not columns or not isinstance(row, exp.Tuple) or len(columns) != len(row.expressions):
        return None
    if any(not isinstance(c, exp.Identifier) for c in columns):
        return None
    keys = [c.name if c.args.get('quoted') else c.name.casefold() for c in columns]
    if len(set(keys)) != len(keys):
        return None
    for value in row.expressions:
        if isinstance(value, exp.Neg) and isinstance(value.this, exp.Literal) and not value.this.is_string:
            continue
        if not isinstance(value, (exp.Literal, exp.Null, exp.Boolean)):
            return None
    spans = _write_ranges(code, dialect, values=True)
    if len(spans) != len(columns):
        return None
    return [_record(relation(target), identifier(column), '', code[start:end], 'constant', [
        'INSERT VALUES describes inserted rows only; prior target rows and omitted-column defaults are not established'],
        ordinal=ordinal, _expression_offset=start)
        for ordinal, (column, (start, end)) in enumerate(zip(columns, spans))]


def extract_transformations(tree: exp.Expression, code: str, dialect: Dialect, scopes: list[Scope], target: exp.Table | None=None) -> list[dict[str, Any]]:
    """Extract scope-preserving column derivations and explicit uncertainty coverage.

    Args:
        tree: Parsed SQL statement tree.
        code: Original SQL statement text.
        dialect: SQLGlot dialect used to parse the statement.
        scopes: Active SQLGlot query scopes.
        target: Optional physical target table for the statement.

    Returns:
        Column derivation records; unsupported boundaries remain unresolved."""
    target_name = relation(target) if target is not None else "__result__"
    root_scope = "" if target is not None else "result:0"
    lateral_aliases = dialect.__class__.__name__.casefold() in {
        "snowflake", "duckdb", "redshift", "databricks", "spark", "clickhouse"}
    if isinstance(tree, exp.Update) and target is not None:
        update = _postgres_update(tree, code, dialect, target)
        if update is not None:
            return [*update, _record(target_name, '*', root_scope, code, 'partial_write', [
                'UPDATE prior rows and unchanged columns are not established'], ordinal=len(update))]
    if isinstance(tree, exp.Insert) and isinstance(tree.expression, exp.Values):
        inserted = _postgres_values(tree, code, dialect, target) if target is not None else None
        if inserted is not None:
            return [*inserted, _record(target_name, '*', root_scope, code, 'partial_write', [
                'INSERT VALUES prior target rows and omitted-column defaults are not established'], ordinal=len(inserted))]
        return [_record(target_name, '*', root_scope, code, coverage=[
            'Unsupported INSERT VALUES column transformation'])]
    if isinstance(tree, (exp.Update, exp.Merge, exp.Delete)):
        return [_record(target_name, "*", root_scope, code, coverage=[
            f"Unsupported {tree.key.upper()} column transformation"])]
    if any(with_.args.get("recursive") for with_ in tree.find_all(exp.With)):
        return [_record(target_name, "*", root_scope, code, coverage=["Recursive SQL is not resolved"])]
    unsupported_sets = sorted({node.key.upper() for node in tree.find_all(exp.SetOperation)
                               if not isinstance(node, exp.Union)})
    if unsupported_sets:
        return [_record(target_name, "*", root_scope, code, coverage=[
            f"Unsupported {'/'.join(unsupported_sets)} set operation; value branch mapping is not resolved"])]
    if not scopes:
        if isinstance(tree, exp.Insert):
            return [_record(target_name, "*", root_scope, code, coverage=["INSERT without SELECT is not resolved"])]
        return []

    destinations = {}
    for index, scope in enumerate(scopes):
        parent = scope.expression.parent
        alias = parent.alias_or_name if isinstance(parent, (exp.CTE, exp.Subquery)) else ""
        kind = "cte" if isinstance(parent, exp.CTE) else "query"
        destinations[id(scope)] = (alias or f"__query_{index}", f"{kind}:{index}")
    roots = [scope for scope in scopes if scope.parent is None]
    for root in roots:
        destinations[id(root)] = target_name, root_scope

    # UNION branches write the parent's output columns, with independent evidence.
    def share_destination(scope: Scope) -> None:
        """Assign UNION child scopes to their parent's target destination.

        Args:
            scope: Parent query scope whose set-operation children are visited."""
        for child in scope.set_operation_scopes:
            destinations[id(child)] = destinations[id(scope)]
            share_destination(child)

    for scope in reversed(scopes):
        share_destination(scope)

    ranges = _projection_ranges(code, dialect)
    # SQLGlot drops unary plus. Preserve that distinction when classifying
    # GROUP BY positions, including parentheses/comments around the number.
    plus_positions = set()
    previous = None
    for token in dialect.tokenize(code):
        if token.text == '(':
            continue
        if previous is not None and previous.text == '+':
            plus_positions.add(token.start)
        previous = token
    records = []
    branch_counts = {}

    def output_names(scope: Scope) -> list[str]:
        """Return known output names for a query scope and its set branches.

        Args:
            scope: Query scope whose projected output names are inspected.

        Returns:
            Output names in projection order."""
        parent = scope.expression.parent
        if isinstance(parent, (exp.CTE, exp.Subquery)):
            alias = parent.args.get("alias")
            if alias and alias.args.get("columns"):
                return [identifier(column) for column in alias.args["columns"]]
        if scope.set_operation_scopes:
            return output_names(scope.set_operation_scopes[0])
        if not isinstance(scope.expression, exp.Select):
            return []
        return [identifier(p.args.get("alias")) if isinstance(p, exp.Alias)
                else identifier(p.this) if isinstance(p, exp.Column) else "*" if isinstance(p, exp.Star)
                else "" for p in scope.expression.expressions]

    def name_key(name: str) -> str:
        """Normalize quoted and unquoted output names for matching.

        Args:
            name: SQL output column spelling.

        Returns:
            Case-folded unquoted name or case-preserved quoted name."""
        return name[1:-1].replace('""', '"') if name.startswith('"') else name.casefold()

    for scope in scopes:
        query = scope.expression
        if not isinstance(query, exp.Select):
            continue
        table, scope_key = destinations[id(scope)]
        coverage = []
        output_scope = scope
        owners = []
        while True:
            owner = output_scope.expression
            owners.append(owner)
            while isinstance(owner.parent, exp.Subquery):
                owner = owner.parent
                owners.append(owner)
            if not output_scope.parent or output_scope not in output_scope.parent.set_operation_scopes:
                break
            output_scope = output_scope.parent
        if any(isinstance(owner, exp.SetOperation) and owner.args.get('distinct') for owner in owners):
            coverage.append('Set duplicate-selection context is not resolved')
        for owner in owners:
            if owner.args.get('limit') is not None or owner.args.get('offset') is not None:
                coverage.append('Row limiting/offset selection context is not resolved')
            if owner.args.get('sample') is not None:
                coverage.append('Query sampling selection context is not resolved')
        names = output_names(output_scope)
        if isinstance(tree, (exp.Insert, exp.Create)) and not scope_key and isinstance(tree.this, exp.Schema):
            columns = tree.this.expressions
            names = [identifier(c.this if isinstance(c, exp.ColumnDef) else c) for c in columns]
        if isinstance(tree, exp.Insert) and not scope_key and not isinstance(tree.this, exp.Schema):
            names = []
            coverage.append("INSERT target column mapping requires an explicit list or trusted schema")
        if len(names) != len(query.expressions):
            coverage.append("Output and projection cardinality mismatch")
        name_counts = Counter(name_key(name) for name in names if name and name != "*")
        duplicate_names = {name for name, count in name_counts.items() if count > 1}
        if output_scope.set_operation_scopes:
            leaves = []

            def collect_leaves(item):
                if item.set_operation_scopes:
                    for child in item.set_operation_scopes:
                        collect_leaves(child)
                else:
                    leaves.append(item)

            collect_leaves(output_scope)
            if len({len(s.expression.expressions) for s in leaves}) != 1:
                coverage.append("UNION branch cardinality mismatch")
            if any(s.expression.find(exp.Star) is not None for s in leaves):
                coverage.append("Set operation wildcard positions require trusted schema expansion")
        mapping = {name: source for name, (_, source) in scope.selected_sources.items()}
        if any(isinstance(source, exp.Table) and source.args.get('sample') is not None
               for source in mapping.values()):
            coverage.append('Table sampling selection context is not resolved')
        projection_aliases = [(position, name_key(identifier(p.args["alias"])))
                              for position, p in enumerate(query.expressions) if isinstance(p, exp.Alias)]

        def lookup(alias):
            if isinstance(alias, exp.Identifier) and alias.args.get("quoted"):
                return mapping.get(alias.name)
            matches = [source for name, source in mapping.items() if name.casefold() == alias.name.casefold()]
            return matches[0] if len(matches) == 1 else None
        destination = (table, scope_key)
        branch = branch_counts.get(destination, 0)
        branch_counts[destination] = branch + 1

        def source_ref(source):
            if isinstance(source, exp.Table) and isinstance(source.this, exp.Identifier):
                return relation(source), ""
            if isinstance(source, Scope):
                return destinations.get(id(source), ("", ""))
            return "", ""

        def add_input(record, source, column, role):
            source_table, source_scope = source_ref(source)
            if not source_table:
                record["coverage"].append("Dynamic or unsupported relation source")
                return
            item = {"table": source_table, "column": column, "role": role, "scope": source_scope, "version": ""}
            if item not in record["inputs"]:
                record["inputs"].append(item)

        def resolve(record, column, role):
            if not column.table and any(alias == name_key(identifier(column.this))
                                        and (resolving_context or lateral_aliases and position != ordinal)
                                        for position, alias in projection_aliases):
                record["coverage"].append(f"Projection alias dependency is not resolved: {column.name}")
                return
            source = lookup(column.args["table"]) if column.table else None
            if not column.table and len(mapping) == 1:
                source = next(iter(mapping.values()))
            if source is None:
                record["coverage"].append(f"Unresolved or ambiguous column: {column.sql()}")
                return
            if isinstance(source, exp.Table):
                alias = source.args.get("alias")
                if alias and alias.args.get("columns"):
                    record["coverage"].append("Base-table column alias mapping requires trusted schema")
                    return
            name = identifier(column.this)
            if isinstance(source, Scope) and sum(name_key(n) == name_key(name) for n in output_names(source)) != 1:
                record["coverage"].append(f"Intermediate output column cannot be established: {name}")
                return
            add_input(record, source, name, role)

        def dependencies(node, role, record):
            if isinstance(node, exp.Column):
                resolve(record, node, role)
                return
            if isinstance(node, (exp.Select, exp.SetOperation, exp.Subquery)):
                record["coverage"].append("Scalar or correlated subquery expression is not resolved")
                return
            if isinstance(node, (exp.Parameter, exp.Placeholder, exp.Var)):
                record["coverage"].append("Runtime expression is not resolved")
            if isinstance(node, exp.Anonymous):
                record["coverage"].append(f"Unknown function semantics: {node.name}")
            if (isinstance(node, exp.Func) and not isinstance(node, exp.AggFunc)
                    and not isinstance(node.parent, exp.Window) and not list(node.iter_expressions())):
                record["coverage"].append(f"Runtime function value is not a known constant: {node.key}")
            if isinstance(node, exp.If):
                dependencies(node.this, "value_selection", record)
                for key in ("true", "false"):
                    if node.args.get(key) is not None:
                        dependencies(node.args[key], role, record)
                return
            if isinstance(node, exp.Filter):
                dependencies(node.this, role, record)
                dependencies(node.expression, "value_selection", record)
                return
            if isinstance(node, exp.Case):
                if node.this is not None:
                    dependencies(node.this, "value_selection", record)
                for conditional in node.args.get("ifs", []):
                    dependencies(conditional.this, "value_selection", record)
                    dependencies(conditional.args["true"], role, record)
                if node.args.get("default") is not None:
                    dependencies(node.args["default"], role, record)
                return
            if isinstance(node, exp.Window):
                if node.args.get("alias") is not None:
                    record["coverage"].append("Named window partition/order dependencies are not resolved")
                for source in mapping.values():
                    add_input(record, source, "", "rowset")
                dependencies(node.this, role, record)
                for partition in node.args.get("partition_by", []):
                    dependencies(partition, "partition", record)
                if node.args.get("order") is not None:
                    dependencies(node.args["order"], "order", record)
                if node.args.get("spec") is not None:
                    dependencies(node.args["spec"], "order", record)
                return
            if isinstance(node, exp.AggFunc):
                for source in mapping.values():
                    add_input(record, source, "", "rowset")
            if isinstance(node, exp.Count) and isinstance(node.this, exp.Star):
                for source in mapping.values():
                    add_input(record, source, "", "rowset")
                return
            for child in node.iter_expressions():
                dependencies(child, role, record)

        for ordinal, projection in enumerate(query.expressions):
            resolving_context = False
            expression = _original(projection, ranges, code)
            name = names[ordinal] if ordinal < len(names) else ""
            local_coverage = coverage.copy()
            if name_key(name) in duplicate_names:
                local_coverage.append(f"Duplicate output column name prevents unique target mapping: {name}")
                name = ""
            if not name:
                local_coverage.append("Output column name cannot be established")
            if not expression:
                local_coverage.append("Original projection expression range cannot be established; see statement evidence")
            value = projection.this if isinstance(projection, exp.Alias) else projection
            category = ("direct" if isinstance(value, exp.Column) else "window" if isinstance(value, exp.Window)
                        else "case" if isinstance(value, exp.Case) else "cast" if isinstance(value, exp.Cast)
                        else "aggregate" if isinstance(value, exp.AggFunc) else "expression")
            record = _record(table, name or "*", scope_key, expression, category, local_coverage,
                             branch=branch, ordinal=ordinal)
            original_span = _original_range(projection, ranges, code)
            if original_span is not None:
                record['_expression_offset'] = original_span[0]
            if isinstance(tree, exp.Insert) and not scope_key and not isinstance(tree.this, exp.Schema):
                record["target_mapping_missing"] = True
                record["projection_count"] = len(query.expressions)
            star = value.this if isinstance(value, exp.Column) and isinstance(value.this, exp.Star) else value
            if isinstance(star, exp.Star):
                record["category"] = "wildcard"
                explicit_targets = (not scope_key and isinstance(tree, (exp.Insert, exp.Create))
                                    and isinstance(tree.this, exp.Schema))
                record["wildcard_safe"] = (not any(star.args.values()) and not output_scope.set_operation_scopes
                                           and not explicit_targets)
                record["target_column"] = "*"
                record["coverage"].append("Wildcard requires trusted schema expansion")
                wildcard_mapping = [lookup(value.args["table"])] if isinstance(value, exp.Column) else list(mapping.values())
                for source in wildcard_mapping:
                    if isinstance(source, exp.Table) and source.args.get("alias") and source.args["alias"].args.get("columns"):
                        record["wildcard_safe"] = False
                        record["coverage"].append("Base-table column alias mapping requires trusted schema")
                    add_input(record, source, "*", "value")
            else:
                dependencies(value, "value", record)
                if not record["inputs"] and not record["coverage"]:
                    record["category"] = "constant"
            resolving_context = True
            for key in ("where", "having", "qualify"):
                if query.args.get(key) is not None:
                    dependencies(query.args[key], "row_filter", record)
            for join in query.args.get("joins", []):
                for source in mapping.values():
                    add_input(record, source, "", "rowset")
                if join.args.get("on") is not None:
                    dependencies(join.args["on"], "join", record)
                if join.args.get("using") or join.args.get("method") == "NATURAL":
                    record["coverage"].append("JOIN USING/NATURAL matching context is not resolved")
            if query.args.get("group") is not None:
                group = query.args['group']
                for grouping in group.expressions:
                    while isinstance(grouping, exp.Paren):
                        grouping = grouping.this
                    positional = grouping.is_int or isinstance(grouping, exp.Neg) and grouping.this.is_int
                    if positional:
                        if grouping.meta.get('start') in plus_positions:
                            record['coverage'].append('Unary-plus grouping syntax is not resolved as a position')
                            continue
                        position = int(grouping.sql())
                        if (dialect.__class__.__name__.casefold() not in {
                                'dialect', 'postgres', 'duckdb', 'snowflake', 'bigquery'}
                                or not 1 <= position <= len(query.expressions)):
                            record['coverage'].append('GROUP BY position cannot be established for this dialect')
                            continue
                        selected = query.expressions[position - 1]
                        selected = selected.this if isinstance(selected, exp.Alias) else selected
                        # This is a source expression, not a reference to a SELECT alias.
                        resolving_context = False
                        dependencies(selected, 'value_selection', record)
                        resolving_context = True
                    else:
                        dependencies(grouping, 'value_selection', record)
                if any(value for key, value in group.args.items() if key != 'expressions'):
                    record['coverage'].append('Extended grouping context is not resolved')
            distinct = query.args.get('distinct')
            if distinct is not None:
                if distinct.args.get('on') is not None:
                    dependencies(distinct.args['on'], 'value_selection', record)
                    record['coverage'].append('DISTINCT ON row choice is not resolved')
                else:
                    resolving_context = False
                    for selected in query.expressions:
                        selected = selected.this if isinstance(selected, exp.Alias) else selected
                        if selected.is_star:
                            record['coverage'].append('DISTINCT wildcard selection requires a known output layout')
                        else:
                            dependencies(selected, 'value_selection', record)
                    resolving_context = True
                for source in mapping.values():
                    add_input(record, source, '', 'rowset')
            if query.args.get("order") is not None:
                record["coverage"].append("Query-level ordering context is not resolved")
            record["coverage"] = list(dict.fromkeys(record["coverage"]))
            record["status"] = "unresolved" if record["coverage"] else "verified"
            records.append(record)
    return records
