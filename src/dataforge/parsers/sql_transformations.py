"""Conservative, scope-preserving SQL transformation facts with original evidence."""
from __future__ import annotations

from collections import Counter

from sqlglot import exp
from sqlglot.optimizer.scope import Scope


def identifier(node):
    if isinstance(node, exp.Identifier):
        return '"' + node.name.replace('"', '""') + '"' if node.args.get("quoted") else node.name
    return node.name if node is not None else ""


def relation(table):
    parts = []
    for part in table.parts:
        prefix = "##" if part.args.get("global_") else "#" if part.args.get("temporary") else ""
        name = prefix + part.name
        parts.append('"' + name.replace('"', '""') + '"' if "." in name else name)
    return ".".join(parts)


def _projection_ranges(code, dialect):
    """Token boundaries preserve parentheses/comments absent from AST source metadata."""
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


def _original(projection, ranges, code):
    offsets = [(n.meta["start"], n.meta["end"]) for n in projection.walk()
               if "start" in n.meta and "end" in n.meta]
    if not offsets:
        return ""
    low, high = min(a for a, _ in offsets), max(b for _, b in offsets)
    matches = [(a, b) for a, b in ranges if a <= low and high < b]
    if not matches:
        return ""
    a, b = min(matches, key=lambda item: item[1] - item[0])
    return code[a:b].strip()


def _record(table, column, scope, expression, category="expression", coverage=None, **extra):
    coverage = list(coverage or [])
    return {"target_table": table, "target_column": column, "scope": scope, "target_version": "",
            "expression": expression, "category": category, "status": "unresolved" if coverage else "verified",
            "inputs": [], "coverage": coverage, "branch": 0, "ordinal": 0, **extra}


def extract_transformations(tree, code, dialect, scopes, target=None):
    """Return static facts; unresolved boundaries never fabricate source column names."""
    target_name = relation(target) if target is not None else "__result__"
    root_scope = "" if target is not None else "result:0"
    lateral_aliases = dialect.__class__.__name__.casefold() in {
        "snowflake", "duckdb", "redshift", "databricks", "spark", "clickhouse"}
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
    def share_destination(scope):
        for child in scope.set_operation_scopes:
            destinations[id(child)] = destinations[id(scope)]
            share_destination(child)

    for scope in reversed(scopes):
        share_destination(scope)

    ranges = _projection_ranges(code, dialect)
    records = []
    branch_counts = {}

    def output_names(scope):
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

    def name_key(name):
        return name[1:-1].replace('""', '"') if name.startswith('"') else name.casefold()

    for scope in scopes:
        query = scope.expression
        if not isinstance(query, exp.Select):
            continue
        table, scope_key = destinations[id(scope)]
        coverage = []
        output_scope = scope
        while output_scope.parent and output_scope in output_scope.parent.set_operation_scopes:
            output_scope = output_scope.parent
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
                dependencies(query.args["group"], "value_selection", record)
            if query.args.get("order") is not None:
                record["coverage"].append("Query-level ordering context is not resolved")
            record["coverage"] = list(dict.fromkeys(record["coverage"]))
            record["status"] = "unresolved" if record["coverage"] else "verified"
            records.append(record)
    return records
