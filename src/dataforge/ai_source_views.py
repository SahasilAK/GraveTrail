"""Bounded original-source views and indexed context, without fabricated standalone code."""
from __future__ import annotations

import json
import re
from functools import lru_cache

from dataforge.ai_analysis_models import SourceFocus
from dataforge.models import stable_id


def compact_catalog(catalog):
    """Keep declaration provenance, but not redundant complete source quotes/read sites."""
    result, seen = [], set()
    for entry in catalog:
        item = dict(entry)
        if item.get('role') == 'observed':
            item = {k: item[k] for k in ('name', 'role', 'temporary', 'job_id') if k in item}
        if isinstance(item.get('evidence'), dict):
            item['evidence'] = {k: v for k, v in item['evidence'].items() if k != 'quote'}
        key = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            result.append(item)
            seen.add(key)
    return result


@lru_cache(maxsize=32)
def _context_records(serialized):
    records = []
    def visit(value, path):
        encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        if len(encoded) <= 128:
            records.append({'path': path, 'value': value})
        elif isinstance(value, dict):
            for key, child in value.items():
                visit(child, path + '/' + key.replace('~', '~0').replace('/', '~1'))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, path + '/' + str(index))
        elif isinstance(value, str):
            for start in range(0, len(value), 128):
                records.append({'path': path, 'start': start, 'end': min(start + 128, len(value)),
                                'value': value[start:start + 128], 'length': len(value)})
        else:
            records.append({'path': path, 'value': value})
    visit(json.loads(serialized), '')
    return tuple(records)


def context_records(catalog, settings):
    return _context_records(json.dumps({'catalog': compact_catalog(catalog), 'settings': settings},
                                       ensure_ascii=False, sort_keys=True, separators=(',', ':')))


def view_identity(focus):
    return stable_id(focus.parent_id, 'source-context-view-v1', str(focus.start_offset),
                     str(focus.end_offset), str(focus.context_start), str(focus.context_end))


def source_window(unit, ranges):
    """Retain bounded exact anchors around a window; gaps never imply standalone syntax."""
    f = unit.source_focus
    if not f:
        return ranges
    if unit.unit_id != view_identity(f):
        raise ValueError('Invalid host source window identity')
    requested = [(max(unit.start_offset, f.start_offset - 64), min(unit.end_offset, f.end_offset + 64)),
                 (unit.start_offset, min(unit.end_offset, unit.start_offset + 64)),
                 (max(unit.start_offset, unit.end_offset - 64), unit.end_offset)]
    intersections = sorted((max(a, x), min(b, y)) for a, b in ranges for x, y in requested
                           if max(a, x) < min(b, y))
    merged = []
    for start, end in intersections:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def split_source_context(unit, catalog, settings, *, source_only=False):
    """Every split strictly reduces a source interval or context index range."""
    records = context_records(catalog, settings)
    focus = unit.source_focus
    if not focus:
        focus = SourceFocus(parent_id=unit.unit_id, start_offset=unit.start_offset,
            end_offset=unit.end_offset, context_start=0, context_end=len(records))
        return (unit.model_copy(update={'source_focus': focus, 'unit_id': view_identity(focus)}),)
    size = focus.end_offset - focus.start_offset
    context_size = len(json.dumps(records[focus.context_start:focus.context_end], ensure_ascii=False))
    if not source_only and focus.context_end - focus.context_start > 1 and (context_size >= size or size <= 1):
        middle = (focus.context_start + focus.context_end) // 2
        changes = [{'context_end': middle}, {'context_start': middle}]
    elif size > 1:
        middle = (focus.start_offset + focus.end_offset) // 2
        # Prefer a nearby line boundary; every byte still belongs to a work window.
        newline = unit.code.find('\n', middle - unit.start_offset,
            min(focus.end_offset - unit.start_offset, middle - unit.start_offset + size // 8))
        if newline >= 0 and unit.start_offset + newline + 1 < focus.end_offset:
            middle = unit.start_offset + newline + 1
        changes = [{'end_offset': middle}, {'start_offset': middle}]
    else:
        return ()
    return tuple(unit.model_copy(update={'source_focus': (child := focus.model_copy(update=change)),
                 'unit_id': view_identity(child)}) for change in changes)


def minimum_source_view(unit, *, preserve_context=False, context_span=None):
    """Capacity probe only; never schedule this incomplete work range."""
    current = unit.source_focus
    start = current.start_offset if current else unit.start_offset
    focus = SourceFocus(parent_id=current.parent_id if current else unit.unit_id, start_offset=start,
        end_offset=start + 1,
        context_start=current.context_start if current and preserve_context else 0,
        context_end=current.context_end if current and preserve_context else 0)
    if context_span:
        focus = focus.model_copy(update={'context_start': context_span[0], 'context_end': context_span[1]})
    return unit.model_copy(update={'source_focus': focus, 'unit_id': view_identity(focus)})


@lru_cache(maxsize=16)
def _masked_source(code, sas):
    pattern = r"--[^\n]*|/\*.*?\*/|'(?:[^']|'')*'" + (r'|"(?:[^"]|"")*"' if sas else '')
    return re.sub(pattern, lambda match: ' ' * len(match[0]), code, flags=re.S)


_IDENTIFIER = r'"(?:[^\"]|\"\")*"|`(?:[^`]|``)*`|\[(?:[^\]]|\]\])*\]|[A-Za-z_#][\w#]*'
_QUALIFIED_IDENTIFIER = re.compile(r'(?:' + _IDENTIFIER + r')(?:\s*\.\s*(?:' + _IDENTIFIER + r'))*')


def identifier_name(value):
    parts = re.findall(_IDENTIFIER, value)
    def unquote(part):
        if part.startswith(('"', '`', '[')):
            end = ']' if part[0] == '[' else part[0]
            return part[1:-1].replace(end + end, end).casefold()
        return part.casefold()
    return '.'.join(unquote(part) for part in parts)


def _visible_lexical_source(unit, segments):
    masked = _masked_source(unit.code, unit.extension == '.sas')
    return '\n'.join(masked[s['start_offset']-unit.start_offset:s['end_offset']-unit.start_offset] for s in segments)


def visible_identifier_count(unit, segments):
    # Repeated columns may contribute distinct value/filter/window roles.
    return sum(1 for _ in _QUALIFIED_IDENTIFIER.finditer(_visible_lexical_source(unit, segments)))


def visible_names(unit, segments):
    """Names in disclosed lexical source, excluding comments and string values."""
    names = set()
    for match in _QUALIFIED_IDENTIFIER.finditer(_visible_lexical_source(unit, segments)):
        names.add(identifier_name(match[0]))
        names.update(identifier_name(part) for part in re.findall(_IDENTIFIER, match[0]))
    return names
