"""Conservative, scope-preserving SQL transformation facts with original evidence."""
from __future__ import annotations

from collections import Counter
from functools import cache
from typing import Any

from sqlglot import Dialect, exp
from sqlglot.optimizer.scope import Scope

from dataforge.parsers.sql_databricks import column_parts, is_native_dialect, qualified_source
from dataforge.parsers.sql_databricks_relations import generator_bindings, pivot_bindings, pivot_group_names


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


def is_recursive_self_reference(table: exp.Table, *, case_insensitive: bool = False) -> bool:
    """SQLGlot may expose an unsupported recursive self-read as a physical table."""
    if not isinstance(table.this, exp.Identifier) or table.args.get("db") or table.args.get("catalog"):
        return False

    def key(part):
        return part.name.casefold() if case_insensitive or not part.args.get("quoted") else part.name

    cte = table.find_ancestor(exp.CTE)
    while cte is not None:
        if (isinstance(cte.parent, exp.With) and cte.parent.args.get("recursive")
                and key(cte.args["alias"].this) == key(table.this)):
            return True
        cte = cte.find_ancestor(exp.CTE)
    return False


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
    shared_sql = dialect.parser_class is type(dialect).parser_class
    databricks = is_native_dialect(dialect)
    lateral_aliases = dialect.__class__.__name__.casefold() in {
        "snowflake", "duckdb", "redshift", "databricks", "spark", "clickhouse"}
    if shared_sql and isinstance(tree, exp.Delete):
        return []  # DELETE can remove rows but cannot write an output column value.
    if isinstance(tree, (exp.Update, exp.Merge, exp.Delete)):
        return [_record(target_name, "*", root_scope, code, coverage=[
            f"Unsupported {tree.key.upper()} column transformation"])]
    if not shared_sql and any(with_.args.get("recursive") for with_ in tree.find_all(exp.With)):
        return [_record(target_name, "*", root_scope, code, coverage=["Recursive SQL is not resolved"])]
    unsupported_sets = sorted({node.key.upper() for node in tree.find_all(exp.SetOperation)
                               if not isinstance(node, exp.Union)})
    if unsupported_sets and not shared_sql:
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
    records = []
    branch_counts = {}
    scope_by_expression = {id(scope.expression): scope for scope in scopes}
    runtime_values = (exp.CurrentTimestamp, exp.CurrentDate, exp.CurrentTime)

    def exists_query(query):
        return (isinstance(query, exp.Select) and isinstance(query.parent, exp.Exists)
                and not any(query.args.get(key) for key in ("group", "having", "qualify", "limit", "offset"))
                and not any(projection.find(exp.AggFunc) for projection in query.expressions))

    def literal_unnest(query):
        return (isinstance(query, exp.Unnest) and len(query.expressions) == 1
                and isinstance(query.expressions[0], exp.Array) and not query.args.get("offset")
                and all(isinstance(value, (exp.Literal, exp.Null, exp.Boolean))
                        for value in query.expressions[0].expressions))

    feedback = {}
    recursive_gaps = {}
    if shared_sql:
        for scope in scopes:
            cte = scope.expression.parent
            if not isinstance(cte, exp.CTE) or not cte.parent.args.get("recursive"):
                continue
            branches = scope.set_operation_scopes
            self_sources = [
                source for child in branches for _, source in child.selected_sources.values()
                if isinstance(source, Scope) and id(source) not in destinations
            ]
            physical_self = any(isinstance(source, exp.Table)
                                and is_recursive_self_reference(source, case_insensitive=databricks)
                                for _, source in scope.selected_sources.values())
            if not self_sources and not physical_self:
                continue
            supported = (isinstance(scope.expression, exp.Union) and not scope.expression.args.get("distinct")
                         and len(branches) == 2 and len(self_sources) == 1
                         and all(isinstance(branch.expression, exp.Select) for branch in branches)
                         and self_sources[0] in [s for _, s in branches[1].selected_sources.values()]
                         and all(not isinstance(p, exp.Star) and not p.is_star
                                 for branch in branches for p in branch.expression.expressions))
            if supported:
                feedback[id(self_sources[0])] = scope
            else:
                recursive_gaps[id(scope)] = "Unsupported recursive CTE shape"

    def name_key(name: str) -> str:
        if name.startswith('"'):
            name = name[1:-1].replace('""', '"')
            return name.casefold() if databricks else name
        return name.casefold()

    @cache
    def bindings(scope: Scope) -> dict[str, exp.Table | Scope]:
        return {name: feedback.get(id(source), source)
                for name, (_, source) in scope.selected_sources.items()}

    @cache
    def generators(scope: Scope):
        return {bindings(scope)[alias]: binding for alias, binding in generator_bindings(scope).items()}

    @cache
    def pivots(scope: Scope):
        return {bindings(scope)[alias]: binding for alias, binding in pivot_bindings(scope).items()}

    def lookup(mapping, alias):
        if alias is None:
            return None
        if not databricks and isinstance(alias, exp.Identifier) and alias.args.get("quoted"):
            return mapping.get(alias.name)
        matches = [source for name, source in mapping.items() if name.casefold() == alias.name.casefold()]
        return matches[0] if len(matches) == 1 else None

    def star_of(projection):
        if isinstance(projection, exp.Star):
            return projection
        parts = column_parts(projection) if databricks else (
            projection.parts if isinstance(projection, exp.Column) else [])
        return parts[-1] if parts and isinstance(parts[-1], exp.Star) else None

    @cache
    def layout(scope: Scope) -> list[tuple[exp.Expression, str, exp.Table | Scope | None]]:
        columns = []
        mapping = bindings(scope)
        for projection in scope.expression.expressions:
            parts = column_parts(projection) if databricks else []
            star = star_of(projection)
            if isinstance(projection, exp.Alias):
                name = identifier(projection.args["alias"])
            elif parts:
                name = identifier(parts[-1])
            elif isinstance(projection, exp.Column):
                name = identifier(projection.this)
            else:
                name = "*" if star is not None else ""
            if shared_sql and star is not None:
                if parts:
                    visible = {**mapping, **{binding.alias: source for source, binding in pivots(scope).items()
                                            if binding.alias}}
                    source, consumed = qualified_source(visible, parts)
                    candidates = [source] if consumed == len(parts) - 1 else []
                elif isinstance(projection, exp.Column):
                    candidates = [lookup(mapping, projection.args["table"])] if len(projection.parts) == 2 else []
                elif any(j.args.get("using") or j.args.get("method") == "NATURAL"
                         for j in scope.expression.args.get("joins", [])):
                    candidates = []  # These joins can coalesce columns and change the star order.
                else:
                    candidates = list(mapping.values())
                if not any(star.args.values()) and candidates:
                    known = []
                    for source in candidates:
                        pivot = pivots(scope).get(source) if databricks else None
                        generator = generators(scope).get(source) if databricks else None
                        if pivot and not pivot.coverage and all(len(items) == 1 for items in pivot.outputs.values()):
                            groups = pivot_group_names(pivot, output_names(source)) if isinstance(source, Scope) else None
                            if groups is None:
                                # Grouping columns precede generated buckets. Their names need a trusted schema.
                                known.append(("*", None))
                            else:
                                known.extend((n, source) for n in groups)
                            known.extend((items[0].name, source) for items in pivot.outputs.values())
                        elif generator:
                            known.extend((n, source) for n in generator.columns)
                        elif isinstance(source, Scope) and source is not scope:
                            outputs = output_names(source)
                            if all(n and n != "*" for n in outputs):
                                known.extend((n, source) for n in outputs)
                                continue
                            break
                        else:
                            break
                    else:
                        columns.extend((projection, n, source) for n, source in known)
                        if known:
                            continue
            columns.append((projection, name, None))
        return columns

    @cache
    def output_names(scope: Scope) -> list[str]:
        """Return known output names for a query scope and its set branches.

        Args:
            scope: Query scope whose projected output names are inspected.

        Returns:
            Output names in projection order."""
        if shared_sql and (isinstance(scope.expression, exp.Values) or literal_unnest(scope.expression)):
            alias = scope.expression.args.get("alias")
            return [identifier(column) for column in alias.columns] if alias else []
        parent = scope.expression.parent
        if isinstance(parent, (exp.CTE, exp.Subquery)):
            alias = parent.args.get("alias")
            if alias and alias.args.get("columns"):
                return [identifier(column) for column in alias.args["columns"]]
        if scope.set_operation_scopes:
            return output_names(scope.set_operation_scopes[0])
        if not isinstance(scope.expression, exp.Select):
            return []
        names = [name for _, name, _ in layout(scope)]
        if shared_sql and scope.is_subquery and names == [""]:
            return ["__scalar__"]
        return names

    for scope in scopes:
        query = scope.expression
        if shared_sql and literal_unnest(query):
            names = output_names(scope)
            if len(names) == 1:
                table, scope_key = destinations[id(scope)]
                records.append(_record(table, names[0], scope_key, "", "constant"))
            continue
        if shared_sql and isinstance(query, exp.Values):
            names = output_names(scope)
            rows = query.expressions
            if (names and rows and len({name_key(n) for n in names}) == len(names)
                    and all(isinstance(row, exp.Tuple) and len(row.expressions) == len(names) for row in rows)):
                table, scope_key = destinations[id(scope)]
                for ordinal, name in enumerate(names):
                    literals = all(isinstance(row.expressions[ordinal], (exp.Literal, exp.Null, exp.Boolean))
                                   for row in rows)
                    records.append(_record(table, name, scope_key, "", "constant" if literals else "expression",
                                           [] if literals else ["VALUES expression is not a static literal"],
                                           ordinal=ordinal))
            continue
        if not isinstance(query, exp.Select):
            continue
        membership_query = shared_sql and exists_query(query)
        table, scope_key = destinations[id(scope)]
        coverage = []
        output_scope = scope
        comparison, comparison_right = False, False
        while output_scope.parent and output_scope in output_scope.parent.set_operation_scopes:
            parent = output_scope.parent
            if shared_sql and isinstance(parent.expression, (exp.Except, exp.Intersect)):
                comparison = True
                comparison_right |= output_scope is parent.set_operation_scopes[1]
            if shared_sql and parent.expression.args.get("by_name"):
                coverage.append("Set operation BY NAME layout is not resolved")
            output_scope = output_scope.parent
        projections = [(query, "", None)] if membership_query else layout(scope)
        names = [""] if membership_query else output_names(output_scope)
        if (isinstance(tree, (exp.Insert, exp.Create)) and not scope_key and isinstance(tree.this, exp.Schema)
                and not tree.meta.get("databricks_insert_by_name")):
            columns = tree.this.expressions
            names = [identifier(c.this if isinstance(c, exp.ColumnDef) else c) for c in columns]
        positional_insert = (isinstance(tree, exp.Insert) and not scope_key and not isinstance(tree.this, exp.Schema)
                             and not (shared_sql and (tree.args.get("by_name")
                                                      or tree.meta.get("databricks_insert_by_name"))))
        explicit_star_insert = (shared_sql and isinstance(tree, exp.Insert) and not scope_key
                                and isinstance(tree.this, exp.Schema)
                                and any(name == "*" and source is None for _, name, source in projections))
        insert_names = names if explicit_star_insert else []
        if positional_insert:
            names = []
            coverage.append("INSERT target column mapping requires an explicit list or trusted schema")
        if len(names) != len(projections) and not explicit_star_insert and (not positional_insert or not shared_sql):
            coverage.append("Output and projection cardinality mismatch")
        name_counts = Counter(name_key(name) for name in names if name and name != "*")
        duplicate_names = {name for name, count in name_counts.items() if count > 1}
        deferred_union = False
        if output_scope.set_operation_scopes:
            leaves = []
            sets = []

            def collect_leaves(item):
                if item.set_operation_scopes:
                    sets.append(item.expression)
                    for child in item.set_operation_scopes:
                        collect_leaves(child)
                else:
                    leaves.append(item)

            collect_leaves(output_scope)
            has_star = any((any(name == "*" and bound is None for _, name, bound in layout(s))
                            if shared_sql else s.expression.find(exp.Star) is not None) for s in leaves)
            deferred_union = (shared_sql and has_star and not positional_insert and not explicit_star_insert
                              and not output_scope.outer_columns
                              and all(isinstance(node, exp.Union) and not node.args.get("distinct")
                                      and not node.args.get("by_name") for node in sets))
            if not deferred_union and len({len(layout(s)) for s in leaves}) != 1:
                coverage.append("Set operation branch cardinality mismatch" if databricks else
                                "UNION branch cardinality mismatch")
            if has_star:
                coverage.append("Set operation wildcard positions require trusted schema expansion")
        if id(output_scope) in recursive_gaps:
            coverage.append(recursive_gaps[id(output_scope)])
        invalid_set = shared_sql and output_scope.set_operation_scopes and any(
            "cardinality mismatch" in gap or "wildcard positions" in gap or "recursive" in gap.lower() or "BY NAME" in gap
            for gap in coverage)
        mapping = bindings(scope)
        generated = generators(scope) if databricks else {}
        pivoted = pivots(scope) if databricks else {}
        visible_mapping = {**mapping, **{pivot.alias: source for source, pivot in pivoted.items() if pivot.alias}}
        projection_aliases = [(position, name_key(identifier(p.args["alias"])), p.this)
                              for position, (p, _, _) in enumerate(projections) if isinstance(p, exp.Alias)]
        controls = tree.meta.get("databricks_controls", []) if databricks and not scope_key else []
        payload_stars = [star for item in query.expressions if (star := star_of(item)) is not None] if controls else []
        payload_excluded = {item.name.casefold() for wildcard in payload_stars
                            for item in wildcard.args.get("except_") or []}
        payload_names = {name_key(n) for n in names if n and n != "*"} if controls else set()
        destination = (table, scope_key)
        branch = branch_counts.get(destination, 0)
        branch_counts[destination] = branch + 1

        def source_ref(source):
            if isinstance(source, exp.Table) and isinstance(source.this, exp.Identifier):
                if shared_sql and is_recursive_self_reference(source, case_insensitive=databricks):
                    return "", ""
                return relation(source), ""
            if isinstance(source, Scope):
                return destinations.get(id(source), ("", ""))
            return "", ""

        def add_input(record, source, column, role):
            if source in generated and not column and role == "rowset":
                collection = generated[source].collection
                if collection is not None:
                    dependencies(collection, role, record)
                return
            source_table, source_scope = source_ref(source)
            if not source_table:
                record["coverage"].append("Dynamic or unsupported relation source")
                return
            item = {"table": source_table, "column": column, "role": role, "scope": source_scope, "version": ""}
            if item not in record["inputs"]:
                record["inputs"].append(item)

        def relation_column(record, source, name, role):
            nonlocal pivot_input
            if source in generated:
                generator = generated[source]
                if name_key(name) in {column.casefold() for column in generator.columns} and generator.collection is not None:
                    dependencies(generator.collection, role, record)
                else:
                    record["coverage"].append(f"Unsupported generator output: {name}")
                return
            pivot = pivoted.get(source) if pivot_input is None else None
            if pivot:
                key = name_key(name)
                candidates = pivot.outputs.get(key, ())
                groups = pivot_group_names(pivot, output_names(source)) if isinstance(source, Scope) else None
                if len(candidates) == 1 and not candidates[0].coverage:
                    if groups is not None and key in {name_key(group) for group in groups}:
                        record["coverage"].append(f"Ambiguous PIVOT output also names a grouping column: {name}")
                        return
                    output = candidates[0]
                    pivot_input = source
                    dependencies(output.aggregate, role, record)
                    dependencies(output.key, "value_selection", record)
                    pivot_input = None
                    if groups is not None:
                        for group in groups:
                            add_input(record, source, group, "value_selection")
                    elif isinstance(source, exp.Table):
                        record["pivot_grouping"] = {"table": relation(source), "output": name,
                                                    "exclude": sorted(pivot.consumed)}
                        record["coverage"].append("PIVOT grouping requires trusted input schema")
                    else:
                        record["coverage"].append("PIVOT grouping requires a complete input layout")
                    return
                if candidates or key in pivot.consumed or pivot.coverage:
                    record["coverage"].append(candidates[0].coverage if len(candidates) == 1 and candidates[0].coverage
                                              else f"PIVOT output cannot be established: {name}")
                    return
            if isinstance(source, exp.Table):
                alias = source.args.get("alias")
                if alias and alias.args.get("columns"):
                    record["coverage"].append("Base-table column alias mapping requires trusted schema")
                    return
            if isinstance(source, Scope):
                outputs = output_names(source)
                matches = sum(name_key(n) == name_key(name) for n in outputs)
                if shared_sql and "*" in outputs and matches <= 1 and id(source) in destinations:
                    source_table, source_scope = source_ref(source)
                    record.setdefault("scoped_columns", []).append({
                        "table": source_table, "scope": source_scope, "column": name, "role": role,
                    })
                    return
                if matches != 1:
                    record["coverage"].append(f"Intermediate output column cannot be established: {name}")
                    return
            add_input(record, source, name, role)

        def defer_unqualified(record, candidates, name, role):
            bindings_to_check = []
            for candidate in candidates:
                if isinstance(candidate, exp.Table):
                    alias = candidate.args.get("alias")
                    if not isinstance(candidate.this, exp.Identifier) or alias and alias.args.get("columns"):
                        return False
                elif "*" in output_names(candidate):
                    return False
                table_name, scope_name = source_ref(candidate)
                if not table_name:
                    return False
                bindings_to_check.append({"table": table_name, "scope": scope_name})
            record.setdefault("unqualified_columns", []).append({
                "column": name, "role": role, "sources": bindings_to_check,
            })
            return True

        def resolve(record, column, role):
            nonlocal active_ordinal, expectation, resolving_context
            parts = column_parts(column) if databricks else column.parts
            name = identifier(parts[-1])
            if (shared_sql and dialect.__class__.__name__ == "Oracle" and len(parts) == 1
                    and not parts[0].args.get("quoted") and name.upper() == "ROWNUM"):
                for source in mapping.values():
                    add_input(record, source, "", "rowset")
                return
            if expectation:
                outputs = [i for i, output_name in enumerate(names) if name_key(output_name) == name_key(name)]
                if len(parts) != 1 or len(outputs) != 1:
                    record["coverage"].append(f"Expectation output cannot be established: {column.sql()}")
                    return
                i = outputs[0]
                projection, projected_name, expanded_source = projections[i]
                saved, active_ordinal = active_ordinal, i
                expectation = False
                if expanded_source is not None:
                    relation_column(record, expanded_source, projected_name, role)
                else:
                    dependencies(projection.this if isinstance(projection, exp.Alias) else projection, role, record)
                expectation = True
                active_ordinal = saved
                return
            aliases = [(position, value) for position, alias, value in projection_aliases if alias == name_key(name)]
            if not databricks and not column.table and any(
                    resolving_context or lateral_aliases and position != active_ordinal for position, _ in aliases):
                record["coverage"].append(f"Projection alias dependency is not resolved: {column.name}")
                return
            if databricks:
                lateral = column.find_ancestor(exp.Lateral)
                in_generator = next((i for i, g in enumerate(generated.values()) if lateral is g.node), len(generated))
                available = dict(list(generated.items())[:in_generator])
                local = {alias: source for alias, source in visible_mapping.items()
                         if source not in generated or source in available}
                local_sources = [source for source in mapping.values()
                                 if source not in generated or source in available]
                source, consumed = qualified_source(local, parts)
                parent = scope.parent if scope.can_be_correlated else None
                # An exposed local struct can have the same name as an outer relation.
                local_field = source is None and parent is not None and len(parts) > 1 and any(isinstance(s, Scope) and any(
                    name_key(n) == name_key(identifier(parts[0])) for n in output_names(s)
                ) for s in local_sources)
                while source is None and len(parts) > 1 and parent and not local_field:
                    source, consumed = qualified_source(bindings(parent), parts)
                    parent = parent.parent
                name = ".".join(identifier(part) for part in parts[consumed:])
                if source is None:
                    first = name_key(identifier(parts[0]))
                    known = [s for s in local_sources if s not in generated and isinstance(s, Scope)
                             and first in {name_key(n) for n in output_names(s)}]
                    generated_matches = [s for s, g in available.items()
                                         if first in {n.casefold() for n in g.columns}]
                    pivot_matches = [s for s, p in pivoted.items() if first in p.outputs] if pivot_input is None else []
                    if pivot_matches:
                        relation_column(record, pivot_matches[0] if len(pivot_matches) == 1 else None, name, role)
                        return
                    unknown = [s for s in local_sources if s not in generated
                               and (isinstance(s, exp.Table) or "*" in output_names(s))]
                    if pivot_input is not None:
                        known = [s for s in known if s is pivot_input]
                        unknown = [s for s in unknown if s is pivot_input]
                    if generated_matches:
                        candidates = [*dict.fromkeys(known), *generated_matches]
                        if len(candidates) != 1:
                            record["coverage"].append(f"Ambiguous generator output: {column.name}")
                            return
                        relation_column(record, candidates[0], name, role)
                        return
                    candidates = [*known, *unknown]
                    if len(candidates) == 1:
                        source = candidates[0]
                    alias_context = column.find_ancestor(exp.Having, exp.Qualify) is not None
                    if len(parts) == 1 and aliases and (not resolving_context or alias_context):
                        preceding = [(p, value) for p, value in aliases if alias_context or p < active_ordinal]
                        if not known and len(preceding) == 1:
                            position, value = preceding[0]
                            previous_context = resolving_context
                            resolving_context = False
                            if not unknown:
                                saved, active_ordinal = active_ordinal, position
                                dependencies(value, role, record)
                                active_ordinal = saved
                                resolving_context = previous_context
                                return
                            if len(unknown) == 1 and isinstance(source, exp.Table):
                                fallback = {"inputs": [], "coverage": []}
                                saved, active_ordinal = active_ordinal, position
                                dependencies(value, role, fallback)
                                active_ordinal = saved
                                if not fallback.get("lateral_choices"):
                                    record.setdefault("lateral_choices", []).append({
                                        "table": relation(source), "column": name, "role": role, **fallback})
                                    resolving_context = previous_context
                                    return
                            resolving_context = previous_context
                        if not known and (preceding or active_ordinal not in {p for p, _ in aliases}):
                            reason = f"Ambiguous or forward projection alias: {column.name}"
                            if len(unknown) == 1 and isinstance(source, exp.Table):
                                record.setdefault("lateral_choices", []).append({
                                    "table": relation(source), "column": name, "role": role,
                                    "inputs": [], "coverage": [reason]})
                            else:
                                record["coverage"].append(reason)
                            return
                    if len(parts) == 1 and not known and scope.can_be_correlated:
                        parent = scope.parent
                        while parent:
                            outer = list(dict.fromkeys(bindings(parent).values()))
                            matches = [s for s in outer if isinstance(s, exp.Table) or any(
                                n == "*" or name_key(n) == first for n in output_names(s))]
                            if matches:
                                if unknown or len(matches) != 1:
                                    if candidates and not (generated or pivoted) and defer_unqualified(
                                            record, candidates, name, role):
                                        return
                                    record["coverage"].append(f"Unqualified correlated column is ambiguous: {column.name}")
                                    return
                                source = matches[0]
                                break
                            parent = parent.parent
                    if (len(parts) == 1 and source is None and len(candidates) > 1
                            and not (generated or pivoted or scope.can_be_correlated)
                            and defer_unqualified(record, candidates, name, role)):
                        return
            else:
                source = lookup(mapping, column.args["table"]) if column.table else None
                if shared_sql and column.table and scope.can_be_correlated:
                    parent = scope.parent
                    while source is None and parent is not None:
                        source = lookup(bindings(parent), column.args["table"])
                        parent = parent.parent
                if not column.table:
                    candidates = list(mapping.values())
                    if shared_sql:
                        candidates = [s for s in candidates if not isinstance(s, Scope)
                                      or any(n == "*" or name_key(n) == name_key(name) for n in output_names(s))]
                    if len(candidates) == 1:
                        source = candidates[0]
                    if shared_sql and scope.can_be_correlated and not isinstance(source, Scope):
                        parent = scope.parent
                        while parent is not None:
                            visible = [s for s in bindings(parent).values() if not isinstance(s, Scope)
                                       or any(n == "*" or name_key(n) == name_key(name) for n in output_names(s))]
                            if visible:
                                if candidates or len(visible) != 1:
                                    if candidates and defer_unqualified(record, candidates, name, role):
                                        return
                                    record["coverage"].append(f"Unqualified correlated column is ambiguous: {column.name}")
                                    return
                                source = visible[0]
                                break
                            parent = parent.parent
                    if shared_sql and not scope.can_be_correlated and len(candidates) > 1:
                        if defer_unqualified(record, candidates, name, role):
                            return
            if source is None:
                record["coverage"].append(f"Unresolved or ambiguous column: {column.sql()}")
                return
            relation_column(record, source, name, role)

        def dependencies(node, role, record):
            if isinstance(node, exp.Column) or databricks and isinstance(node, exp.Dot) and column_parts(node):
                resolve(record, node, role)
                return
            if shared_sql and isinstance(node, exp.Exists):
                child = scope_by_expression.get(id(node.this))
                if child is not None and exists_query(child.expression):
                    add_input(record, child, "", "value_selection" if role == "value" else role)
                else:
                    record["coverage"].append("EXISTS row-membership dependencies are not resolved")
                return
            if shared_sql and isinstance(node, exp.In) and node.args.get("query") is not None:
                for child in node.iter_expressions():
                    dependencies(child, "value_selection" if role == "value" else role, record)
                return
            if isinstance(node, (exp.Select, exp.SetOperation, exp.Subquery)):
                if shared_sql:
                    child = scope_by_expression.get(id(node.this if isinstance(node, exp.Subquery) else node))
                    child_names = output_names(child) if child is not None else []
                    if len(child_names) == 1 and child_names[0] not in {"", "*"}:
                        add_input(record, child, child_names[0], role)
                        return
                record["coverage"].append("Scalar or correlated subquery expression is not resolved")
                return
            if isinstance(node, (exp.Parameter, exp.Placeholder, exp.Var)):
                record["coverage"].append("Runtime expression is not resolved")
            if isinstance(node, exp.Anonymous):
                record["coverage"].append(f"Unknown function semantics: {node.name}")
            if (isinstance(node, exp.Func) and not isinstance(node, exp.AggFunc)
                    and not (shared_sql and isinstance(node, runtime_values))
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
                    dependencies(partition, "partition" if role == "value" or not databricks else role, record)
                if node.args.get("order") is not None:
                    dependencies(node.args["order"], "order" if role == "value" or not databricks else role, record)
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

        for ordinal, (projection, projected_name, expanded_source) in enumerate(projections):
            active_ordinal = ordinal
            resolving_context = False
            pivot_input = None
            expectation = False
            expression = tree.meta.get("databricks_evidence", {}).get(id(projection)) or _original(projection, ranges, code)
            name = names[ordinal] if ordinal < len(names) and not invalid_set and not explicit_star_insert else ""
            local_coverage = coverage.copy()
            if name_key(name) in duplicate_names:
                local_coverage.append(f"Duplicate output column name prevents unique target mapping: {name}")
                name = ""
            if not name and not membership_query:
                local_coverage.append("Output column name cannot be established")
            if not expression and not membership_query:
                local_coverage.append("Original projection expression range cannot be established; see statement evidence")
            value = projection.this if isinstance(projection, exp.Alias) else projection
            category = ("direct" if isinstance(value, exp.Column) or databricks and column_parts(value)
                        else "window" if isinstance(value, exp.Window)
                        else "case" if isinstance(value, exp.Case) else "cast" if isinstance(value, exp.Cast)
                        else "aggregate" if isinstance(value, exp.AggFunc) else "expression")
            record = _record(table, "" if membership_query else name or "*", scope_key, expression,
                             "rowset" if membership_query else category, local_coverage,
                             branch=branch, ordinal=ordinal)
            if deferred_union:
                record["union_projection"] = projected_name
            original_span = _original_range(projection, ranges, code)
            if original_span is not None:
                record['_expression_offset'] = original_span[0]
            if positional_insert:
                record["target_mapping_missing"] = True
                record["projection_count"] = len(projections)
            if shared_sql and (positional_insert or explicit_star_insert):
                record["positional_layout"] = True
                if explicit_star_insert:
                    record["insert_target_names"] = insert_names
                if target is not None and target.args.get("partition"):
                    record["coverage"].append("INSERT partition layout is not resolved")
            if shared_sql and not scope_key and (tree.args.get("by_name") or tree.meta.get("databricks_insert_by_name")):
                record["target_by_name"] = True
            star = star_of(value)
            if membership_query:
                for source in mapping.values():
                    add_input(record, source, "", "rowset")
            elif expanded_source is not None:
                record["category"] = "direct"
                if not comparison_right:
                    relation_column(record, expanded_source, projected_name, "value")
            elif isinstance(star, exp.Star):
                record["category"] = "wildcard"
                explicit_targets = (not scope_key and isinstance(tree, (exp.Insert, exp.Create))
                                    and isinstance(tree.this, exp.Schema))
                record["wildcard_safe"] = (not any(star.args.values()) and (not output_scope.set_operation_scopes or deferred_union)
                                           and (not explicit_targets or explicit_star_insert))
                if shared_sql:
                    record["scoped_wildcard"] = True
                if databricks:
                    record["databricks_wildcard"] = True
                    excluded = star.args.get("except_") or []
                    if excluded and not any(v for k, v in star.args.items() if k != "except_"):
                        if all(isinstance(item, (exp.Column, exp.Identifier)) and not item.args.get("table")
                               for item in excluded):
                            record["wildcard_safe"] = not output_scope.set_operation_scopes and not explicit_targets
                            record["wildcard_exclude"] = [name_key(item.name) for item in excluded]
                            record["wildcard_require_exclusions"] = True
                record["target_column"] = "*"
                record["coverage"].append("Wildcard requires trusted schema expansion")
                wildcard_mapping = list(mapping.values())
                wildcard_column = "*"
                if databricks:
                    parts = column_parts(value)
                    if parts:
                        source, consumed = qualified_source(visible_mapping, parts)
                        if source is None and len(mapping) == 1:
                            source = next(iter(mapping.values()))
                        path = parts[consumed:-1]
                        if path:
                            wildcard_column = ".".join(identifier(part) for part in [*path, star])
                            record["struct_path"] = [part.name for part in path]
                        wildcard_mapping = [source]
                elif isinstance(value, exp.Column):
                    wildcard_mapping = [lookup(mapping, value.args["table"])]
                if databricks and len(wildcard_mapping) == 1 and wildcard_mapping[0] in pivoted:
                    pivot = pivoted[wildcard_mapping[0]]
                    record["wildcard_safe"] &= not bool(pivot.coverage)
                    record["wildcard_exclude"] = sorted(pivot.consumed)
                    record["wildcard_reserved"] = list(pivot.outputs)
                    if pivot.coverage:
                        record["coverage"].append(pivot.coverage)
                for source in wildcard_mapping:
                    if isinstance(source, exp.Table) and source.args.get("alias") and source.args["alias"].args.get("columns"):
                        record["wildcard_safe"] = False
                        record["coverage"].append("Base-table column alias mapping requires trusted schema")
                    add_input(record, source, wildcard_column, "row_membership" if comparison_right else "value")
            else:
                if not comparison_right:
                    dependencies(value, "value", record)
                if not record["inputs"] and not record["coverage"] and not any(record.get(key) for key in (
                        "lateral_choices", "scoped_columns", "unqualified_columns")):
                    record["category"] = "runtime" if shared_sql and value.find(*runtime_values) else "constant"
            if comparison:
                for compare_ordinal, (item, projected, source) in enumerate(projections):
                    active_ordinal = compare_ordinal
                    if source is not None:
                        relation_column(record, source, projected, "row_membership")
                    elif star_of(item) is None:
                        dependencies(item.this if isinstance(item, exp.Alias) else item, "row_membership", record)
                active_ordinal = ordinal
            if shared_sql and scope.is_subquery:
                for source in mapping.values():
                    add_input(record, source, "", "rowset")
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
                dependencies(query.args["group"], "value_selection", record)
            if order := query.args.get("order"):
                if shared_sql and not any(isinstance(term.this, exp.Literal) and term.this.is_int
                                          for term in order.expressions):
                    dependencies(order, "row_filter" if query.args.get("limit") or query.args.get("offset")
                                 else "order", record)
                else:
                    record["coverage"].append("Query-level ordering context is not resolved")
            if databricks and not scope_key:
                for role, predicate in controls:
                    selected_control = role in {"history", "ignore_null_update"}
                    if isinstance(predicate, exp.Star):
                        sources = list(mapping.values())
                        excluded = {item.name.casefold() for item in predicate.args.get("except_") or []}
                        if selected_control and not payload_stars:
                            if len(sources) == 1 and excluded <= payload_names:
                                for name in names:
                                    if name and name_key(name) not in excluded:
                                        add_input(record, sources[0], name, role)
                            else:
                                record["coverage"].append(f"AUTO CDC {role} exclusions do not match the payload")
                            continue
                        if len(sources) == 1 and isinstance(sources[0], exp.Table):
                            record.setdefault("schema_controls", []).append({
                                "table": relation(sources[0]), "role": role,
                                "exclude": sorted(excluded),
                                "payload_exclude": sorted(payload_excluded),
                            })
                        record["coverage"].append("AUTO CDC control wildcard requires trusted source schema")
                    elif selected_control and (name_key(predicate.name) in payload_excluded
                                               or not payload_stars and name_key(predicate.name) not in payload_names):
                        record["coverage"].append(f"AUTO CDC {role} column is outside the selected payload: {predicate.name}")
                    else:
                        dependencies(predicate, role, record)
                resolving_context = False
                expectation = True
                for _, policy, predicate, _ in tree.meta.get("databricks_expectations", []):
                    dependencies(predicate, f"quality_{policy}", record)
            if record.get("lateral_choices"):
                record["coverage"].append("Lateral column alias precedence requires trusted source schema")
            if record.get("scoped_columns"):
                record["coverage"].append("Intermediate wildcard requires a complete output layout")
            if record.get("unqualified_columns"):
                record["coverage"].append("Unresolved or ambiguous column ownership requires complete source schemas")
            record["coverage"] = list(dict.fromkeys(record["coverage"]))
            record["status"] = "unresolved" if record["coverage"] else "verified"
            records.append(record)
    return records
