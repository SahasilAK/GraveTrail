"""Deterministic project evidence checks over whole originals, never AI quote fragments."""
from __future__ import annotations

import json
from dataclasses import asdict, fields

import sqlglot
from pydantic import ValidationError
from sqlglot import exp

from dataforge.ai_analysis_models import (
    ClaimDecision,
    Coverage,
    NormalizedFact,
    ProjectLineageResponse,
    ValidationContext,
    ValidationReport,
)
from dataforge.models import canonical, stable_id
from dataforge.parsers.sas import parse_sas
from dataforge.parsers.sql import parse_sql, table_name, target_table

VALIDATOR_VERSION = "1"


def _identity(value, context):
    return value.strip() if context.settings.get("case_sensitive", False) else canonical(value)


def expression_key(value, dialect=""):
    """Normalize syntax only; literals, qualified ownership and operators remain significant."""
    try:
        tree = sqlglot.parse_one(value, read=dialect or None)
        for node in tree.walk():
            node.comments = None
        return tree.sql(normalize=True)
    except (sqlglot.errors.SqlglotError, ValueError, RecursionError):
        return value.strip()


def input_key(items, context):
    return tuple(sorted((_identity(i["table"], context), _identity(i["column"], context),
                         i.get("role", "value"), i.get("scope", ""), str(i.get("version", "")))
                        for i in items))


def operation_contexts(context, parsed=None, *, scoped=True):
    """Locate parser-owned complete operations in the immutable original, including same-line units."""
    if not isinstance(context, ValidationContext):
        context = ValidationContext.model_validate(context)
    source = context.source_text
    unit = context.unit
    if (not source or source[unit.start_offset:unit.end_offset] != unit.code
            or source.count("\n", 0, unit.start_offset) + 1 != unit.first
            or source.count("\n", 0, unit.end_offset) + 1 != unit.last):
        raise ValueError("Original source and unit coordinates disagree")
    if parsed is None:
        parsed = context.parser_result
    if parsed is None:
        parsed = (parse_sas(source, context.settings.get("library_mappings"), context.settings.get("macros"),
                            context.settings.get("dialect", "")) if unit.extension == ".sas"
                  else parse_sql(source, context.settings.get("dialect", "")))
    located = []
    cursor, previous_code, previous_offset, ordinal = 0, None, -1, 0
    for operation in parsed.operations:
        # Supported wrappers deliberately retain their whole enclosing original for every inner operation.
        if operation.code == previous_code and operation.method in {"sql-procedure-body", "sql-literal"}:
            offset, ordinal = previous_offset, ordinal + 1
        else:
            offset = source.find(operation.code, cursor)
            ordinal = 0
        if offset < 0:
            continue  # Decoded/runtime-expanded code cannot establish original operation identity.
        stop = offset + len(operation.code)
        cursor = max(cursor, stop)
        previous_code, previous_offset = operation.code, offset
        if not unit.start_offset <= offset < stop <= unit.end_offset:
            continue
        if (source.count("\n", 0, offset) + 1 != operation.start
                or source.count("\n", 0, stop) + 1 != operation.end):
            continue
        key = stable_id(context.workspace_id, unit.file_id, unit.content_hash, unit.job_id,
                        str(offset), str(stop), str(ordinal))
        if scoped and unit.focus:
            from dataforge.ai_semantic import focused_operation, source_view, unit_dialect
            source_view(unit, unit_dialect(unit, context.settings))
            operation = focused_operation(operation, unit, unit_dialect(unit, context.settings))
        located.append((operation, offset, stop, key))
    return located


def _detail(operation, start, stop, context):
    # Each normalized claim carries its own usage/derivation below. Copying the
    # entire operation's fact arrays per claim makes wide projections quadratic.
    host = {field.name: getattr(operation, field.name) for field in fields(operation)
            if field.name not in {'sources', 'targets', 'usages', 'derivations'}}
    host['sources'] = [asdict(ref) for ref in operation.sources]
    host['targets'] = [asdict(ref) for ref in operation.targets]
    return {"operation": host, "operation_span": [start, stop],
            "workspace_id": context.workspace_id, "job_id": context.unit.job_id,
            "validator_version": VALIDATOR_VERSION}


def _fact(kind, claim, host_operation, start, stop, key, context, candidate_id, **fields):
    return NormalizedFact(kind=kind, unit_id=context.unit.unit_id, evidence_key=key,
                          evidence=claim.evidence, candidate_id=candidate_id,
                          detail=_detail(host_operation, start, stop, context), **fields)


def _same_derivation(claim, record, context):
    return (_identity(claim.target_table, context) == _identity(record["target_table"], context)
            and _identity(claim.target_column, context) == _identity(record["target_column"], context)
            and claim.expression == record["expression"] and claim.category == record["category"]
            and claim.scope == record.get("scope", "") and claim.branch == record.get("branch", 0)
            and str(claim.version) == str(record.get("target_version", ""))
            and claim.ordinal == record.get("ordinal", 0)
            and input_key([i.model_dump() for i in claim.inputs], context) == input_key(record["inputs"], context))


def _bounded_dml(operation, context):
    """Prove one static UPDATE/MERGE assignment form; everything else explicitly abstains."""
    if context.unit.extension != ".sql" or operation.kind not in {"UPDATE", "MERGE"}:
        return []
    dialect = context.settings.get("dialect", "")
    try:
        tree = sqlglot.parse_one(operation.code, read=dialect or None)
        target = target_table(tree)
        if target is None or not isinstance(target.this, exp.Identifier):
            return []
        if tree.find(exp.CTE, exp.Subquery, exp.Select, exp.Parameter, exp.Placeholder, exp.Join):
            return []
        tables = list(tree.find_all(exp.Table))
        if any(not isinstance(t.this, exp.Identifier) for t in tables):
            return []
        mapping = {}
        for table in tables:
            for name in (table.alias_or_name, table_name(table)):
                normalized = canonical(name)
                if normalized in mapping and mapping[normalized] != table_name(table):
                    return []
                mapping[normalized] = table_name(table)
        contextual = []
        if isinstance(tree, exp.Update):
            if any(tree.args.get(k) for k in ("with_", "returning", "order", "limit")):
                return []
            assignments = tree.expressions
            if tree.args.get("where"):
                contextual.append((tree.args["where"], "row_filter"))
        elif isinstance(tree, exp.Merge):
            whens = tree.args.get("whens")
            whens = whens.expressions if whens else []
            if (len(whens) != 1 or not whens[0].args.get("matched") or whens[0].args.get("source")
                    or whens[0].args.get("condition") is not None
                    or not isinstance(whens[0].args.get("then"), exp.Update)
                    or not isinstance(tree.args.get("using"), exp.Table)):
                return []
            assignments = whens[0].args["then"].expressions
            contextual.append((tree.args["on"], "join"))
        else:
            return []
        records = []
        if len({canonical(a.this.name) for a in assignments if isinstance(a.this, exp.Column)}) != len(assignments):
            return []
        def dependencies(node, role, inputs):
            if isinstance(node, exp.Column):
                if isinstance(node.this, exp.Star):
                    raise ValueError("wildcard")
                if node.table:
                    owner = mapping.get(canonical(".".join(p.name for p in node.parts[:-1])))
                else:
                    owners = set(mapping.values())
                    owner = next(iter(owners)) if len(owners) == 1 else None
                if owner is None:
                    raise ValueError("ambiguous ownership")
                item = {"table": owner, "column": node.name, "role": role, "scope": "", "version": ""}
                if item not in inputs:
                    inputs.append(item)
                return
            if isinstance(node, (exp.Anonymous, exp.Window, exp.AggFunc, exp.Var, exp.Star)):
                raise ValueError("unsupported value semantics")
            if isinstance(node, exp.If):
                dependencies(node.this, "value_selection" if role in {'value', 'value_selection'} else role, inputs)
                for k in ("true", "false"):
                    if node.args.get(k) is not None:
                        dependencies(node.args[k], role, inputs)
                return
            if isinstance(node, exp.Case):
                if node.this is not None:
                    dependencies(node.this, "value_selection" if role in {'value', 'value_selection'} else role, inputs)
                for conditional in node.args.get("ifs", []):
                    dependencies(conditional, role, inputs)
                if node.args.get("default") is not None:
                    dependencies(node.args["default"], role, inputs)
                return
            if isinstance(node, exp.Func) and not list(node.iter_expressions()):
                raise ValueError("runtime function")
            for child in node.iter_expressions():
                dependencies(child, role, inputs)
        tokens = sqlglot.Dialect.get_or_raise(dialect or None).tokenize(operation.code)
        for ordinal, assignment in enumerate(assignments):
            if not isinstance(assignment, exp.EQ) or not isinstance(assignment.this, exp.Column):
                return []
            lhs, rhs = assignment.this, assignment.expression
            if lhs.table and mapping.get(canonical(lhs.table)) != table_name(target):
                return []
            meta = [n.meta for n in lhs.walk() if "end" in n.meta]
            if not meta:
                return []
            end_lhs = max(m["end"] for m in meta)
            equals = next(i for i, token in enumerate(tokens) if token.start > end_lhs)
            if tokens[equals].text != "=":
                return []
            first = equals + 1
            depth = 0
            stop = len(operation.code)
            for token in tokens[first:]:
                kind = token.token_type.name
                if depth == 0 and kind in {"COMMA", "FROM", "WHERE", "WHEN", "SEMICOLON", "RETURNING"}:
                    stop = token.start
                    break
                depth += (kind == "L_PAREN") - (kind == "R_PAREN")
            start = tokens[first].start
            expression = operation.code[start:stop].strip()
            if expression_key(expression, dialect) != rhs.sql(normalize=True):
                return []
            inputs = []
            dependencies(rhs, "value", inputs)
            # Old target values need a pre-write version model; this bounded rule does not invent one.
            if any(canonical(item["table"]) == canonical(table_name(target)) for item in inputs):
                return []
            for node, role in contextual:
                dependencies(node, role, inputs)
            category = ("direct" if isinstance(rhs, exp.Column) else "constant" if not list(rhs.find_all(exp.Column))
                        else "case" if isinstance(rhs, exp.Case) else "cast" if isinstance(rhs, exp.Cast)
                        else "expression")
            records.append({"target_table": table_name(target), "target_column": lhs.name,
                            "expression": expression, "category": category, "scope": "", "branch": 0,
                            "target_version": "", "ordinal": ordinal, "inputs": inputs, "coverage": [],
                            "status": "verified", "_expression_offset": start})
        return records
    except (sqlglot.errors.SqlglotError, ValueError, StopIteration, KeyError, RecursionError):
        return []


def validate_project_response(response, context):
    """Return accepted inferred facts and bounded reasons; confidence/review never establish semantics."""
    if not isinstance(context, ValidationContext):
        context = ValidationContext.model_validate(context)
    report = ValidationReport()
    try:
        response = (response if isinstance(response, ProjectLineageResponse)
                    else ProjectLineageResponse.model_validate(response))
        response.assert_unit(context.unit)
        operations = operation_contexts(context)
    except (ValidationError, ValueError):
        report.rejected.append(ClaimDecision(reason="invalid_contract_or_original_evidence", status="rejected"))
        report.coverage = Coverage(status="unsupported", unsupported=["invalid_contract_or_original_evidence"])
        return report
    report.coverage = response.coverage.model_copy(deep=True)
    def norm(value):
        return _identity(value, context)

    claims = [(kind, claim) for kind in ("assets", "relationships", "columns", "derivations")
              for claim in getattr(response, kind)]
    for kind, claim in claims:
        candidate_id = stable_id(context.workspace_id, context.unit.unit_id, kind,
                                 json.dumps(claim.model_dump(), sort_keys=True))
        if context.unit.focus and context.unit.focus.ordinal_start and kind in {'assets','relationships'}:
            report.rejected.append(ClaimDecision(candidate_id=candidate_id, reason='outside_projection_focus', status='rejected'))
            continue
        matches, unresolved = [], not operations
        for operation, start, stop, key in operations:
            if kind == "assets":
                refs = operation.sources if claim.role == "read" else operation.targets
                matches.extend((operation, start, stop, key, ref) for ref in refs
                               if norm(ref.name) == norm(claim.name) and ref.kind == ("table" if claim.kind in {"view", "dataset"} else claim.kind)
                               and (claim.role != "declaration" or operation.kind == "CREATE"))
            elif kind == "relationships":
                if (claim.operation.upper() == operation.kind.upper()
                        and any(norm(ref.name) == norm(claim.source) for ref in operation.sources)
                        and any(norm(ref.name) == norm(claim.target) for ref in operation.targets)):
                    matches.append((operation, start, stop, key, None))
            elif kind == "columns":
                for usage in operation.usages:
                    if (norm(usage.table) == norm(claim.table) and norm(usage.column) == norm(claim.column)
                            and usage.context.upper() == claim.context.upper()
                            and (not claim.alias or norm(usage.alias) == norm(claim.alias))
                            and (not claim.expression or expression_key(claim.expression) == expression_key(usage.expression))):
                        if usage.status == "verified" and usage.column != "*":
                            matches.append((operation, start, stop, key, usage))
                        else:
                            unresolved = True
            else:
                records = operation.derivations
                gap_records = _bounded_dml(operation, context)
                for record in [*records, *gap_records]:
                    if (norm(claim.target_table) == norm(record["target_table"])
                            and (norm(claim.target_column) == norm(record["target_column"])
                                 or record["target_column"] in {"*", ""})):
                        if record.get("status") != "verified" or record.get("coverage"):
                            unresolved = True
                        elif (_same_derivation(claim, record, context)
                              and start <= claim.expression_start_offset < claim.expression_end_offset <= stop
                              and ("_expression_offset" not in record
                                   or claim.expression_start_offset == start + record["_expression_offset"])):
                            matches.append((operation, start, stop, key, record))
        # A full-unit quote containing two indistinguishable writers cannot select one by array order.
        distinct = {match[3] for match in matches}
        if len(distinct) != 1:
            status = "unresolved" if unresolved or len(distinct) > 1 else "rejected"
            reason = "unsupported_or_ambiguous_semantics" if status == "unresolved" else "semantic_mismatch"
            getattr(report, status).append(ClaimDecision(candidate_id=candidate_id, reason=reason,
                                                        status=status, evidence=claim.evidence))
            continue
        operation, start, stop, key, record = matches[0]
        if kind == "assets":
            asset = asdict(record)
            if claim.role == "declaration":
                asset.update(evidence_key=key, operation=asdict(operation), operation_span=[start, stop])
            if asset not in report.assets:
                report.assets.append(asset)
            continue
        if kind == "relationships":
            fact = _fact("table_edge", claim, operation, start, stop, key, context, candidate_id,
                         source=claim.source, target=claim.target, operation=operation.kind)
        elif kind == "columns":
            fact = _fact("direct_usage", claim, operation, start, stop, key, context, candidate_id,
                         table=record.table, column=record.column, expression=record.expression,
                         operation=record.context)
            fact.detail["usage"] = asdict(record)
        else:
            fact = _fact("derivation", claim, operation, start, stop, key, context, candidate_id,
                         table=record["target_table"], column=record["target_column"], expression=record["expression"],
                         scope=record.get("scope", ""), branch=record.get("branch", 0),
                         version=record.get("target_version", ""), ordinal=record.get("ordinal", 0),
                         inputs=claim.inputs)
            fact.detail["derivation"] = {k: v for k, v in record.items() if not k.startswith("_")}
        if not any(existing.model_dump(exclude={"candidate_id"}) == fact.model_dump(exclude={"candidate_id"})
                   for existing in report.accepted):
            report.accepted.append(fact)
    if operations and not report.accepted and not report.assets:
        report.coverage.status = "partial"
        report.coverage.unsupported = list(dict.fromkeys([*report.coverage.unsupported, "no_supported_claims"]))
    if report.rejected or report.unresolved or response.unresolved_symbols:
        report.coverage.status = "partial"
    return report
