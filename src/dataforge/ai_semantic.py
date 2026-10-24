"""Host-owned semantic partitions over exact source; never synthetic SQL evidence."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, replace
from functools import lru_cache

import sqlglot
from sqlglot import exp
from sqlglot.tokens import TokenType

from dataforge.ai_analysis_models import ProjectionFocus
from dataforge.models import canonical, stable_id, statements


@lru_cache(maxsize=32)
def _projections(code, dialect=""):
    try:
        trees = sqlglot.parse(code, read=dialect or None)
        if len(trees) != 1:
            return ()
        tree = trees[0]
        query = (
            tree
            if isinstance(tree, exp.Select)
            else tree.expression
            if isinstance(tree, (exp.Create, exp.Insert))
            else None
        )
        if not isinstance(query, exp.Select) or len(query.expressions) < 2:
            return ()
        if isinstance(tree, (exp.Create, exp.Insert)) and isinstance(tree.this, exp.Schema):
            return ()
        # A new dialect clause must be reviewed before it can cross a source gap.
        if any(
            value and key not in {"expressions", "from_", "joins", "where"}
            for key, value in query.args.items()
        ):
            return ()
        if not query.args.get("from_") and query.args.get("where"):
            return ()
        if tree.find(exp.CTE, exp.Subquery, exp.SetOperation, exp.Star, exp.AggFunc, exp.Window):
            return ()
        if len(list(tree.find_all(exp.Select))) != 1:
            return ()
        names = [p.alias_or_name.casefold() for p in query.expressions]
        if not all(names) or len(set(names)) != len(names):
            return ()
        aliases = {p.alias.casefold() for p in query.expressions if p.alias}
        if any(not c.table and c.name.casefold() in aliases for c in query.find_all(exp.Column)):
            return ()
        tokens = sqlglot.Dialect.get_or_raise(dialect or "").tokenize(code)
        select = next(i for i, t in enumerate(tokens) if t.token_type == TokenType.SELECT)
        depth, starts, spans = 0, tokens[select + 1].start, []
        for index, token in enumerate(tokens[select + 1 :], select + 1):
            if token.token_type == TokenType.L_PAREN:
                depth += 1
            elif token.token_type == TokenType.R_PAREN:
                depth -= 1
            elif (
                depth == 0
                and token.token_type in {TokenType.COMMA, TokenType.FROM, TokenType.SEMICOLON}
                and not (token.token_type == TokenType.FROM and tokens[index - 1].token_type == TokenType.DOT)
            ):
                end = token.start
                while end > starts and code[end - 1].isspace():
                    end -= 1
                spans.append((starts, end))
                if token.token_type != TokenType.COMMA:
                    break
                starts = token.end + 1
                while starts < len(code) and code[starts].isspace():
                    starts += 1
        else:
            spans.append((starts, len(code.rstrip())))
        if len(spans) != len(query.expressions):
            return ()
        for (start, end), projection in zip(spans, query.expressions):
            original = projection.sql(normalize=True, comments=False)
            bound = sqlglot.parse_one(code[start:end], read=dialect or None).sql(
                normalize=True, comments=False
            )
            if original != bound:
                return ()
        return tuple(spans)
    except (sqlglot.errors.SqlglotError, ValueError, StopIteration, IndexError, RecursionError):
        return ()


def _focus_bounds(unit, dialect=""):
    spans = _projections(unit.code, dialect) if unit.extension == ".sql" else ()
    if unit.focus:
        f = unit.focus
        if (
            not spans
            or not 0 <= f.ordinal_start < f.ordinal_end <= len(spans)
            or (f.list_start, f.list_end)
            != (unit.start_offset + spans[0][0], unit.start_offset + spans[-1][1])
            or (f.start_offset, f.end_offset)
            != (
                unit.start_offset + spans[f.ordinal_start][0],
                unit.start_offset + spans[f.ordinal_end - 1][1],
            )
            or (unit.source_focus.parent_id if unit.source_focus else unit.unit_id)
            != stable_id(f.parent_id, "projection-v1", str(f.ordinal_start), str(f.ordinal_end))
        ):
            raise ValueError("Invalid host projection partition")
    return spans


def projection_count(unit, dialect=""):
    spans = _focus_bounds(unit, dialect)
    return unit.focus.ordinal_end - unit.focus.ordinal_start if unit.focus else len(spans)


def split_projection_unit(unit, dialect=""):
    spans = _focus_bounds(unit, dialect)
    lo, hi = (unit.focus.ordinal_start, unit.focus.ordinal_end) if unit.focus else (0, len(spans))
    if hi - lo < 2:
        return ()
    parent = unit.focus.parent_id if unit.focus else unit.unit_id
    pages = []
    for a, b in ((lo, (lo + hi) // 2), ((lo + hi) // 2, hi)):
        focus = ProjectionFocus(
            parent_id=parent,
            list_start=unit.start_offset + spans[0][0],
            list_end=unit.start_offset + spans[-1][1],
            start_offset=unit.start_offset + spans[a][0],
            end_offset=unit.start_offset + spans[b - 1][1],
            ordinal_start=a,
            ordinal_end=b,
        )
        pages.append(
            unit.model_copy(
                update={"unit_id": stable_id(parent, "projection-v1", str(a), str(b)), "focus": focus}
            )
        )
    return tuple(pages)


def source_view(unit, dialect=""):
    _focus_bounds(unit, dialect)
    if not unit.focus:
        ranges = [(unit.start_offset, unit.end_offset)]
    else:
        f = unit.focus
        ranges = [
            (unit.start_offset, f.list_start),
            (f.start_offset, f.end_offset),
            (f.list_end, unit.end_offset),
        ]
    from dataforge.ai_source_views import source_window
    ranges = source_window(unit, ranges)
    return [
        {"start_offset": a, "end_offset": b, "code": unit.code[a - unit.start_offset : b - unit.start_offset]}
        for a, b in ranges
    ]


def focused_operation(operation, unit, dialect=""):
    if not unit.focus:
        return operation
    f = unit.focus
    records = [d for d in operation.derivations if f.ordinal_start <= d.get("ordinal", 0) < f.ordinal_end]
    tree = sqlglot.parse_one(unit.code, read=dialect or None)
    query = tree if isinstance(tree, exp.Select) else tree.expression
    allowed = set()
    query_expression = None
    for projection in query.expressions[f.ordinal_start : f.ordinal_end]:
        for column in projection.find_all(exp.Column):
            if column.parent is query:
                if query_expression is None:
                    query_expression = query.sql()
                expression = query_expression
            else:
                expression = column.parent.sql()
            allowed.add((canonical(column.table), canonical(column.name), expression))
    usages = [
        u
        for u in operation.usages
        if (
            (canonical(u.alias), canonical(u.column), u.expression) in allowed
            if u.context.upper() in {"SELECT", "EXPRESSION"}
            else f.ordinal_start == 0
        )
    ]
    return replace(
        operation,
        derivations=records,
        usages=usages,
        table_pairs=operation.table_pairs if f.ordinal_start == 0 else [],
    )


def proc_sql_spans(code):
    """Only static, option-free PROC SQL; stateful and macro wrappers stay whole."""
    parts = list(statements(code, sas=True))
    if len(parts) < 4 or not re.fullmatch(r"\s*proc\s+sql\s*;\s*", parts[0][0], re.I):
        return ()
    if not re.fullmatch(r"\s*quit\s*;\s*", parts[-1][0], re.I):
        return ()
    if re.search(
        r"[%&]|\b(connect|connection|disconnect|execute|reset|dictionary|sqlrc|sqlobs)\b|\binto\s*:",
        code,
        re.I,
    ):
        return ()
    result, cursor = [], 0
    for raw, _, _ in parts[1:-1]:
        start = code.find(raw, cursor)
        if start < 0 or not re.match(
            r"\s*(select|create\s+(table|view)|insert\s+into|update|delete\s+from)\b", raw, re.I
        ):
            return ()
        result.append((start, start + len(raw)))
        cursor = start + len(raw)
    return tuple(result)


def merge_publication_operations(operations):
    """Several foci remain one original writer, with sparse accepted facts combined."""
    merged = {}
    for op in operations:
        if op.evidence_key not in merged:
            merged[op.evidence_key] = op
            continue
        prior = merged[op.evidence_key]
        pairs = []
        for current in (prior, op):
            pairs.extend((current.sources[a], current.targets[b]) for a, b in (current.table_pairs or []))
        for field in ("sources", "targets", "usages", "derivations"):
            values = getattr(prior, field) + getattr(op, field)
            unique = {
                json.dumps(asdict(v) if not isinstance(v, dict) else v, sort_keys=True): v for v in values
            }
            setattr(prior, field, list(unique.values()))
        prior.table_pairs = list(
            dict.fromkeys((prior.sources.index(a), prior.targets.index(b)) for a, b in pairs)
        )
        if op.method != "ai-project":
            prior.method, prior.confidence = op.method, op.confidence
    return list(merged.values())


def unit_dialect(unit, settings):
    dialect = settings.get("dialect_by_extension", {}).get(unit.extension, settings.get("dialect", ""))
    for prefix, value in sorted(settings.get("dialect_by_folder", {}).items(), key=lambda item: len(item[0])):
        if unit.path.startswith(prefix):
            dialect = value
    return dialect


def split_proc_sql_unit(unit):
    if unit.extension != ".sas":
        return ()
    pages = []
    for start, end in proc_sql_spans(unit.code):
        code = unit.code[start:end]
        a, b = unit.start_offset + start, unit.start_offset + end
        pages.append(
            unit.model_copy(
                update={
                    "unit_id": stable_id(unit.unit_id, "proc-sql-v1", str(a), str(b)),
                    "code": code,
                    "start_offset": a,
                    "end_offset": b,
                    "first": unit.first + unit.code.count("\n", 0, start),
                    "last": unit.first + unit.code.count("\n", 0, end),
                }
            )
        )
    return tuple(pages)
