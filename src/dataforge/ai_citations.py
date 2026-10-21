"""Source-only expression references; location references never establish lineage semantics."""
from __future__ import annotations

import hashlib
import re
from functools import lru_cache

import sqlglot
from sqlglot import exp

from dataforge.models import stable_id, statements
from dataforge.parsers.sas import strip_comments
from dataforge.parsers.sql_transformations import _projection_ranges


def _trim(code, start, end):
    while start < end and code[start].isspace():
        start += 1
    while end > start and code[end - 1].isspace():
        end -= 1
    return start, end


def _rhs(assignment, code, tokens):
    lhs = assignment.this
    offsets = [n.meta['end'] for n in lhs.walk() if 'end' in n.meta]
    if not isinstance(lhs, exp.Column) or not offsets:
        return None
    equals = next((i for i, t in enumerate(tokens) if t.start > max(offsets)), None)
    if equals is None or tokens[equals].text != '=' or equals + 1 >= len(tokens):
        return None
    first, depth, cases = equals + 1, 0, 0
    stop = len(code)
    for index, token in enumerate(tokens[first:], first):
        kind = token.token_type.name
        if (depth == cases == 0 and kind in {'COMMA', 'FROM', 'WHERE', 'WHEN', 'SEMICOLON', 'RETURNING'}
                and tokens[index - 1].token_type.name != 'DOT'):
            stop = token.start
            break
        depth += (kind == 'L_PAREN') - (kind == 'R_PAREN')
        cases += (kind == 'CASE') - (kind == 'END')
    return _trim(code, tokens[first].start, stop)


@lru_cache(maxsize=16)
def _source_spans(code, extension, dialect):
    """Syntax and original token ranges only; no dependency/ownership/parser answers."""
    spans = [(0, len(code), 'unit', 0, 0, '')] if extension == '.sas' else []
    cursor, proc_sql = 0, False
    for statement_index, (raw, _, _) in enumerate(statements(code, sas=extension == '.sas')):
        start = code.find(raw, cursor)
        if start < 0:
            raise ValueError('Original statement range unavailable')
        cursor = start + len(raw)
        clean = strip_comments(raw).strip() if extension == '.sas' else raw
        if extension == '.sas':
            # Host-paged static PROC SQL statements retain .sas but omit the PROC header.
            if statement_index == 0 and re.match(r'(?:select|create|insert|update|delete|merge)\b', clean, re.I):
                proc_sql = True
            if re.match(r'proc\s+sql\b', clean, re.I):
                proc_sql = True
                continue
            if re.match(r'(?:proc|data|run|quit)\b', clean, re.I):
                proc_sql = False
            if not proc_sql:
                assignment = re.fullmatch(r'([A-Za-z_]\w*)\s*=.+;?', clean, re.S)
                if assignment:
                    spans.append((start, cursor, 'assignment', statement_index, 0, assignment[1]))
                continue
        try:
            reader = sqlglot.Dialect.get_or_raise(dialect or None)
            ranges = _projection_ranges(raw, reader)
            try:
                tree = sqlglot.parse_one(raw, read=reader)
            except sqlglot.errors.SqlglotError:
                if extension != '.sas':
                    raise
                tree = None
            projections = []
            for query_index, query in enumerate(tree.find_all(exp.Select) if tree is not None else []):
                for ordinal, projection in enumerate(query.expressions):
                    positions = [(n.meta['start'], n.meta['end']) for n in projection.walk()
                                 if 'start' in n.meta and 'end' in n.meta]
                    if not positions:
                        continue
                    lo, hi = min(a for a, _ in positions), max(b for _, b in positions)
                    candidates = [(a, b) for a, b in ranges if a <= lo <= hi < b]
                    if not candidates:
                        continue
                    a, b = _trim(raw, *min(candidates, key=lambda span: span[1] - span[0]))
                    bound = sqlglot.parse_one('SELECT ' + raw[a:b], read=reader)
                    if (not isinstance(bound, exp.Select) or len(bound.expressions) != 1
                            or bound.expressions[0].sql(normalize=True, comments=False)
                            != projection.sql(normalize=True, comments=False)):
                        continue
                    projections.append((start + a, start + b, 'projection', statement_index,
                                        ordinal, f'query_{query_index}:{projection.alias_or_name}'))
            spans.extend(projections)
            # SAS modifiers/constants can exceed the generic dialect grammar. These are
            # lexical source ranges only; the SAS semantic validator still owns acceptance.
            if extension == '.sas' and not projections:
                for ordinal, (a, b) in enumerate(ranges):
                    a, b = _trim(raw, a, b)
                    spans.append((start + a, start + b, 'projection', statement_index, ordinal, 'lexical'))
            if tree is not None:
                tokens = reader.tokenize(raw)
                for update in tree.find_all(exp.Update):
                    for ordinal, assignment in enumerate(update.expressions):
                        if not isinstance(assignment, exp.EQ):
                            continue
                        span = _rhs(assignment, raw, tokens)
                        if span is None:
                            continue
                        a, b = span
                        bound = sqlglot.parse_one('SELECT ' + raw[a:b], read=reader)
                        if (isinstance(bound, exp.Select) and len(bound.expressions) == 1
                                and bound.expressions[0].sql(normalize=True, comments=False)
                                == assignment.expression.sql(normalize=True, comments=False)):
                            spans.append((start + a, start + b, 'assignment', statement_index,
                                          ordinal, assignment.this.name))
        except (sqlglot.errors.SqlglotError, ValueError, RecursionError, IndexError):
            continue  # Unknown syntax retains strict legacy citations; never guess a range.
    return tuple(spans)


def source_references(unit, settings=None):
    from dataforge.ai_semantic import source_view, unit_dialect

    settings = settings or {}
    dialect = unit_dialect(unit, settings)
    visible = source_view(unit, dialect)
    result, seen = [], set()
    for a, b, kind, statement, ordinal, name in _source_spans(unit.code, unit.extension, dialect):
        start, end = unit.start_offset + a, unit.start_offset + b
        if (not 0 <= a < b <= len(unit.code) or b - a > 20000
                or not any(v['start_offset'] <= start < end <= v['end_offset'] for v in visible)):
            continue
        key = (start, end, kind)
        if key in seen:
            continue
        seen.add(key)
        text = unit.code[a:b]
        reference_id = stable_id('expression-reference-v1', unit.unit_id, unit.file_id, unit.content_hash,
                                 unit.job_id, unit.extension, dialect, str(start), str(end), kind,
                                 hashlib.sha256(text.encode()).hexdigest())
        result.append({'reference_id': reference_id, 'kind': kind, 'statement': statement,
                       'ordinal': ordinal, 'name': name, 'start_offset': start, 'end_offset': end, 'text': text})
    return sorted(result, key=lambda item: (item['start_offset'], item['end_offset'], item['kind']))
