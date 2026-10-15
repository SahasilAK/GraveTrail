"""SQLGlot AST extraction with scope-local direct column attribution."""
from __future__ import annotations

import logging

import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel, OptimizeError, ParseError, TokenError
from sqlglot.optimizer.scope import Scope, traverse_scope

from dataforge.models import AssetRef, Diagnostic, Operation, ParseResult, Usage, statements

log = logging.getLogger(__name__)
# SQLGlot fallback warnings include raw imported statements; keep sensitive source out of logs.
logging.getLogger("sqlglot").setLevel(logging.ERROR)


def table_name(table: exp.Table) -> str:
    return ".".join('"' + p.name.replace('"', '""') + '"' if "." in p.name else p.name for p in table.parts)


def target_table(node):
    target = node.this if isinstance(node, (exp.Create, exp.Insert, exp.Update, exp.Delete, exp.Merge)) else None
    if isinstance(target, exp.Schema):
        target = target.this
    return target if isinstance(target, exp.Table) else None


def usage_context(column) -> str:
    ancestor = column.parent
    while ancestor is not None:
        for klass, name in [(exp.Join, "JOIN"), (exp.Where, "WHERE"), (exp.Group, "GROUP BY"),
                            (exp.Having, "HAVING"), (exp.Order, "ORDER BY"), (exp.Update, "UPDATE"),
                            (exp.Merge, "MERGE"), (exp.Select, "SELECT")]:
            if isinstance(ancestor, klass):
                return name
        ancestor = ancestor.parent
    return "EXPRESSION"


def declared_schema(tree, start, end, operation_index):
    """Explicit typed DDL only; schema-changing statements invalidate earlier declarations."""
    if not isinstance(tree, (exp.Create, exp.Alter, exp.Drop)):
        return []
    if str(tree.args.get("kind", "")).upper() not in {"TABLE", "VIEW"}:
        return []
    if isinstance(tree, exp.Drop):
        return [{"table": table_name(target), "columns": None, "start_line": start,
                 "end_line": end, "operation_index": operation_index}
                for target in tree.args.get("tables", []) if isinstance(target, exp.Table)]
    target = tree.this.this if isinstance(tree.this, exp.Schema) else tree.this
    if not isinstance(target, exp.Table):
        return []
    columns = None
    if isinstance(tree, exp.Create) and isinstance(tree.this, exp.Schema):
        definitions = [c for c in tree.this.expressions if isinstance(c, exp.ColumnDef)]
        constraints = (exp.ColumnDef, exp.Constraint, exp.PrimaryKey, exp.ForeignKey,
                       exp.UniqueColumnConstraint, exp.CheckColumnConstraint)
        simple_schema = all(isinstance(c, constraints) for c in tree.this.expressions)
        properties = tree.args.get("properties")
        simple_properties = properties is None or all(isinstance(p, exp.TemporaryProperty)
                                                      for p in properties.expressions)
        if (simple_schema and simple_properties and definitions and len(definitions) <= 4096
                and all(c.args.get("kind") is not None for c in definitions)):
            columns = [{"name": c.name, "type": c.args["kind"].sql()} for c in definitions]
    records = [{"table": table_name(target), "columns": columns, "start_line": start,
                "end_line": end, "operation_index": operation_index}]
    if isinstance(tree, exp.Alter):
        for action in tree.args.get("actions", []):
            if isinstance(action, (exp.SwapTable, exp.AlterRename)) and isinstance(action.this, exp.Table):
                records.append({**records[0], "table": table_name(action.this), "columns": None})
    return records


def parse_sql(content: str, dialect: str = "") -> ParseResult:
    result = ParseResult()
    for code, start, end in statements(content):
        try:
            tree = sqlglot.parse_one(code, read=dialect or None, error_level=ErrorLevel.RAISE)
            if tree is None:
                continue
            if isinstance(tree, (exp.Command, exp.Block)):
                result.diagnostics.append(Diagnostic("Unsupported SQL command or procedural block; no guessed lineage", start))
                continue
            all_scopes = list(traverse_scope(tree) or [])
            active = {}

            def visit(scope):
                if id(scope) in active:
                    return
                active[id(scope)] = scope
                for _, source in scope.selected_sources.values():
                    if isinstance(source, Scope):
                        visit(source)
                for child in [*scope.set_operation_scopes, *scope.subquery_scopes]:
                    visit(child)

            for scope in all_scopes:
                if scope.parent is None:
                    visit(scope)
            cte_scopes = {s.expression.parent.alias_or_name.casefold(): s for s in all_scopes
                          if isinstance(s.expression.parent, exp.CTE)}
            if isinstance(tree, (exp.Update, exp.Delete, exp.Merge)):
                for table in tree.find_all(exp.Table):
                    if table.find_ancestor(exp.CTE) is None and table.name.casefold() in cte_scopes:
                        visit(cte_scopes[table.name.casefold()])
            scopes = [s for s in all_scopes if id(s) in active]
            inactive_nodes = {id(n) for s in all_scopes if id(s) not in active for n in s.expression.walk()}
            target = target_table(tree)
            temp = bool(tree.find(exp.TemporaryProperty)) or (target is not None and target.name.startswith("#"))
            targets = [AssetRef(table_name(target), temp)] if target is not None else []
            base_tables: dict[int, exp.Table] = {}
            for scope in scopes:
                for _, source in scope.selected_sources.values():
                    if isinstance(source, exp.Table) and isinstance(source.this, exp.Identifier):
                        base_tables[id(source)] = source
            cte_names = {c.alias_or_name.casefold() for c in tree.find_all(exp.CTE)}
            # DML owns table references outside query scopes (UPDATE FROM / MERGE USING).
            if not isinstance(tree, (exp.Select, exp.Union, exp.Create, exp.Insert)):
                for table in tree.find_all(exp.Table):
                    if table is not target and table.name.casefold() not in cte_names and id(table) not in inactive_nodes:
                        if isinstance(table.this, exp.Identifier):
                            base_tables[id(table)] = table
            sources = list({table_name(t): AssetRef(table_name(t)) for t in base_tables.values()}.values())
            usages = []
            handled = set()

            def attribute(column, mapping, scope=None):
                handled.add(id(column))
                alias = column.table if isinstance(column, exp.Column) else ""
                name = column.name if isinstance(column, exp.Column) else "*"
                star = column.this if isinstance(column, exp.Column) else column
                wildcard_safe = isinstance(star, exp.Star) and not any(star.args.values())
                source = None
                if alias:
                    source = mapping.get(alias.casefold())
                    # A correlated subquery may reference an enclosing scope directly.
                    parent = scope.parent if scope else None
                    while source is None and parent:
                        parent_mapping = {k.casefold(): v[1] for k, v in parent.selected_sources.items()}
                        source = parent_mapping.get(alias.casefold())
                        parent = parent.parent
                elif len({id(v) for v in mapping.values()}) == 1:
                    source = next(iter(mapping.values()))
                elif name == "*":
                    for item in mapping.values():
                        if isinstance(item, exp.Table):
                            usages.append(Usage(table_name(item), "*", "SELECT", "", "*", "unresolved",
                                                wildcard_safe=wildcard_safe))
                    return
                else:
                    # Do not attribute unqualified ORDER BY aliases to a source column.
                    if scope and usage_context(column) == "ORDER BY" and name in scope.expression.named_selects:
                        return
                    result.diagnostics.append(Diagnostic(
                        f"Ambiguous unqualified column {name}; base table cannot be established", start, symbol=name))
                    return
                if isinstance(source, exp.Table):
                    usages.append(Usage(table_name(source), name, usage_context(column), alias,
                                        column.parent.sql() if column.parent else column.sql(),
                                        "unresolved" if name == "*" else "verified", wildcard_safe=wildcard_safe))
                elif source is None and alias:
                    result.diagnostics.append(Diagnostic(f"Unresolved column alias {alias}", start, symbol=alias))
                # Scope sources are CTEs/subqueries. Their inner references are counted once.

            for scope in scopes:
                mapping = {k.casefold(): v[1] for k, v in scope.selected_sources.items()}
                for col in [*scope.columns, *scope.stars]:
                    if id(col) not in handled:
                        attribute(col, mapping, scope)
                if isinstance(scope.expression, exp.Select):
                    for projection in scope.expression.expressions:
                        if isinstance(projection, exp.Star):
                            attribute(projection, mapping, scope)
            if isinstance(tree, (exp.Update, exp.Delete, exp.Merge)):
                mapping = {t.alias_or_name.casefold(): t for t in tree.find_all(exp.Table)
                           if isinstance(t.this, exp.Identifier) and t.name.casefold() not in cte_names and id(t) not in inactive_nodes}
                for table in tree.find_all(exp.Table):
                    if table.name.casefold() in cte_scopes and id(table) not in inactive_nodes:
                        mapping[table.alias_or_name.casefold()] = cte_scopes[table.name.casefold()]
                if target is not None:
                    mapping[table_name(target).casefold()] = target
                for col in tree.find_all(exp.Column):
                    if id(col) not in handled and id(col) not in inactive_nodes:
                        # Assignment LHS is a write, not a read of the old target value.
                        if isinstance(col.parent, exp.EQ) and col.parent.this is col and col.parent.parent is tree:
                            continue
                        attribute(col, mapping)
            if target is not None and not targets[0].name:
                result.diagnostics.append(Diagnostic("Dynamic SQL target cannot be resolved", start))
                continue
            if sources or targets or usages:
                kind = tree.key.upper() if target is not None else "SELECT"
                result.operations.append(Operation(kind, sources, targets, code, start, end, usages=usages))
            elif not isinstance(tree, (exp.Set, exp.Use)):
                result.diagnostics.append(Diagnostic("No statically analyzable table references", start, severity="info"))
            declarations = declared_schema(tree, start, end, len(result.operations) - 1)
            if declarations:
                result.metadata.setdefault("declared_schemas", []).extend(declarations)
        except (ParseError, TokenError, OptimizeError, ValueError, RecursionError) as exc:
            # SQL errors may quote imported secrets; store only the type and source location.
            log.info("sql_parse_failed", extra={"line": start, "error_type": type(exc).__name__})
            result.diagnostics.append(Diagnostic(f"SQL parse failed ({type(exc).__name__}); check dialect and syntax", start, "error"))
    return result
