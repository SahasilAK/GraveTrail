"""Bind Databricks LATERAL VIEW and PIVOT outputs to their original SQL AST."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from sqlglot import exp
from sqlglot.optimizer.scope import Scope

from dataforge.parsers.sql_databricks import qualified_source


@dataclass(frozen=True)
class GeneratorBinding:
    """An explicitly named generated relation and its supported collection input."""

    node: exp.Lateral
    columns: tuple[str, ...]
    collection: exp.Expression | None


@dataclass(frozen=True)
class PivotOutput:
    """A generated output and the aggregate and key specific to its bucket."""

    name: str
    aggregate: exp.Expression
    key: exp.Expression
    coverage: str = ""


@dataclass(frozen=True)
class PivotBinding:
    """The columns generated and consumed by a pivot over one relation."""

    node: exp.Pivot
    alias: str
    outputs: dict[str, tuple[PivotOutput, ...]]
    consumed: frozenset[str]
    coverage: str = ""


def generator_bindings(scope: Scope) -> dict[str, GeneratorBinding]:
    """Collect LATERAL VIEW aliases in source order, including unsupported generators."""
    bindings = {}
    for alias, (node, _) in scope.selected_sources.items():
        if not isinstance(node, exp.Lateral) or not node.args.get("view"):
            continue
        columns = tuple(node.alias_column_names)
        generator = node.this
        collection = None
        if isinstance(generator, exp.Explode) and not generator.expressions:
            collection = generator.this
            if isinstance(collection, exp.Kwarg):
                collection = collection.expression if collection.this.name.casefold() == "collection" else None
            array_width = 2 if isinstance(generator, exp.Posexplode) else 1
            widths = (array_width, array_width + 1)
            if isinstance(collection, exp.Array):
                widths = (array_width,)
            elif isinstance(collection, (exp.Map, exp.VarMap)):
                widths = (array_width + 1,)
            if len(columns) not in widths or len({name.casefold() for name in columns}) != len(columns):
                collection = None
        bindings[alias] = GeneratorBinding(node, columns, collection)
    return bindings


def visible_generators(
    bindings: dict[str, GeneratorBinding], column: exp.Column,
) -> list[GeneratorBinding]:
    """Expose only earlier generators while resolving a generator's collection."""
    if column.find_ancestor(exp.Pivot) is not None:
        return []
    enclosing = column.find_ancestor(exp.Lateral)
    visible = []
    for binding in bindings.values():
        if binding.node is enclosing:
            break
        visible.append(binding)
    return visible


def pivot_bindings(scope: Scope) -> dict[str, PivotBinding]:
    """Bind PIVOT clauses to the selected sources they transform."""
    bindings = {}
    selected = scope.selected_sources
    for alias, (node, _) in selected.items():
        pivots = node.args.get("pivots") or []
        if pivots and not all(pivot.args.get("unpivot") for pivot in pivots):
            bindings[alias] = _pivot_binding(node, pivots)

    # SQLGlot keeps pivots on some compound relations outside selected_sources.
    compound = list(scope.expression.args.get("joins", []))
    from_ = scope.expression.args.get("from_")
    if from_ is not None and all(node is not from_.this for node, _ in selected.values()):
        compound.append(from_.this)
    for node in compound:
        for pivot in node.args.get("pivots") or []:
            if not pivot.args.get("unpivot"):
                unresolved = PivotBinding(
                    pivot, pivot.alias, {}, frozenset(), "PIVOT over a compound relation requires relation binding")
                return dict.fromkeys(selected, unresolved)
    return bindings


def _pivot_binding(source: exp.Expression, pivots: list[exp.Pivot]) -> PivotBinding:
    pivot = pivots[-1]
    alias = pivot.args.get("alias")
    if len(pivots) != 1 or (alias and alias.args.get("columns")):
        return PivotBinding(pivot, pivot.alias, {}, frozenset(), "PIVOT relation alias layout is not established")

    fields = pivot.args.get("fields", [])
    if len(fields) != 1 or not isinstance(fields[0], exp.In) or fields[0].this is None:
        return PivotBinding(pivot, pivot.alias, {}, frozenset(), "PIVOT key layout is not established")

    field = fields[0]
    key = field.this
    key_parts = key.expressions if isinstance(key, exp.Tuple) else [key]
    if not key_parts or not all(isinstance(part, exp.Column) for part in key_parts):
        return PivotBinding(pivot, pivot.alias, {}, frozenset(), "PIVOT key must reference input columns")

    aggregate_expressions = [item.this if isinstance(item, exp.Alias) else item for item in pivot.expressions]
    consumed = set()
    for expression in [key, *aggregate_expressions]:
        for column in expression.find_all(exp.Column):
            parts = column.parts
            if isinstance(source, exp.Table):
                _, width = qualified_source({source.alias_or_name: source}, parts)
            else:
                width = int(len(parts) > 1 and parts[0].name.casefold() == source.alias_or_name.casefold())
            consumed.add(parts[width].name.casefold())

    values = field.expressions
    names = pivot.args.get("columns", [])
    if not values or len(names) != len(values) * len(aggregate_expressions):
        return PivotBinding(pivot, pivot.alias, {}, frozenset(consumed), "PIVOT output names are not static")

    outputs: dict[str, list[PivotOutput]] = {}
    missing_name = False
    for value_index, value in enumerate(values):
        has_alias = isinstance(value, exp.PivotAlias)
        literal = value.this if has_alias else value
        parts = literal.expressions if isinstance(literal, exp.Tuple) else [literal]
        is_static = len(parts) == len(key_parts) and all(_is_pivot_literal(part) for part in parts)
        for aggregate_index, aggregate in enumerate(aggregate_expressions):
            name = names[value_index * len(aggregate_expressions) + aggregate_index]
            if not name.name or (not has_alias and not isinstance(literal, exp.Literal)):
                missing_name = True
                continue
            reason = ""
            if not is_static:
                reason = "PIVOT bucket is not a static literal of the required width"
            elif aggregate.find(exp.AggFunc) is None:
                reason = "PIVOT aggregate function semantics are not established"
            outputs.setdefault(name.name.casefold(), []).append(PivotOutput(name.sql(), aggregate, key, reason))

    return PivotBinding(
        pivot, pivot.alias, {name: tuple(candidates) for name, candidates in outputs.items()},
        frozenset(consumed), "PIVOT output names are not static" if missing_name else "",
    )


def _is_pivot_literal(node: exp.Expression) -> bool:
    return isinstance(node, (exp.Literal, exp.Boolean, exp.Null)) or (
        isinstance(node, exp.Neg) and isinstance(node.this, exp.Literal) and node.this.is_number
    )


def pivot_group_names(binding: PivotBinding, input_names: list[str]) -> list[str] | None:
    """Return the grouping columns in input order if the entire input is known."""
    if not binding.consumed or any(not name or name == "*" for name in input_names):
        return None
    normalized = [name[1:-1].replace('""', '"').casefold() if name.startswith('"') else name.casefold()
                  for name in input_names]
    if any(count > 1 for count in Counter(normalized).values()):
        return None
    return [name for name, key in zip(input_names, normalized, strict=True) if key not in binding.consumed]


def usage_scope_mapping(
    column: exp.Expression,
    mapping: dict[str, exp.Table | Scope],
    generators: dict[str, GeneratorBinding],
    pivots: dict[str, PivotBinding],
) -> dict[str, exp.Table | Scope] | None:
    """Bind physical usage without attributing generated columns to a base table."""
    generator_keys = {name.casefold() for name in generators}
    physical = {name: source for name, source in mapping.items() if name not in generator_keys}
    if isinstance(column, exp.Star):
        return None if pivots else physical
    if not isinstance(column, exp.Column):
        return physical

    pivot_node = column.find_ancestor(exp.Pivot)
    if pivot_node is not None:
        owners = {name.casefold() for name, binding in pivots.items() if binding.node is pivot_node}
        if len(owners) == 1:
            return {name: source for name, source in physical.items() if name in owners}
        return physical

    qualifiers = set(physical)
    qualifiers.update(binding.node.alias.casefold() for binding in generators.values() if binding.node.alias)
    qualifiers.update(binding.alias.casefold() for binding in pivots.values() if binding.alias)
    parts = [part.name.casefold() for part in column.parts]
    _, width = qualified_source(physical, column.parts)
    if not width and len(parts) > 1 and parts[0] in qualifiers:
        width = 1
    qualifier = parts[width - 1] if width else ""
    name = parts[width]
    for binding in visible_generators(generators, column):
        if qualifier and binding.node.alias.casefold() != qualifier:
            continue
        if qualifier or name in {output.casefold() for output in binding.columns}:
            return None

    for source_alias, binding in pivots.items():
        aliases = {source_alias.casefold(), binding.alias.casefold()}
        if qualifier and qualifier not in aliases:
            continue
        if isinstance(column.this, exp.Star) or name in binding.outputs or name in binding.consumed or binding.coverage:
            return None
        if binding.alias and binding.alias.casefold() not in physical:
            physical[binding.alias.casefold()] = physical[source_alias.casefold()]
    return physical
