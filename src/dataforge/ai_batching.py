"""Pure bounded multi-unit prompts; responses retain independent unit authority."""
from __future__ import annotations

import json
from copy import copy

from dataforge.ai_budget import project_profile, request_allowance
from dataforge.ai_wire import decode_project_result


def next_batch_width(current, *, clean_streak, outcome):
    if outcome == 'size_failure':
        return max(1, current // 2)
    return min(8, current * 2) if clean_streak >= 3 else current


def batch_prompt(units, execution, contexts):
    from dataforge.llm import analysis_prompt
    items, systems, schema = [], [], None
    for unit in units:
        local = copy(execution)
        local.catalog = contexts[unit.unit_id]
        system, user, _ = analysis_prompt(unit, 'project_lineage', local)
        if system not in systems:
            systems.append(system)
        # Templates contain a single serialized context; retain its instructions.
        marker = user.find('{')
        context, _ = json.JSONDecoder().raw_decode(user[marker:])
        schema = context.pop('schema')
        items.append(context)
    system = '\n'.join(systems) + (
        '\nBATCH protocol 1: return one JSON object with an items array. Each item '
        'uses the supplied single-unit schema and its own unit_id. Never mix '
        'evidence across items. Missing/unsupported work must be explicit.')
    return system, json.dumps({'batch_version': 1, 'item_schema': schema, 'items': items},
                              ensure_ascii=False, separators=(',', ':'))


def pack_batch(pending, contexts, execution, profile, *, width, privacy_chars):
    selected, files = [], set()
    first = pending[0]
    for unit in pending:
        if (unit.source_kind, unit.extension) != (first.source_kind, first.extension):
            break
        if unit.source_kind == 'dbt' and unit.job_id != first.job_id:
            break
        if len(files | {unit.file_id}) > (execution.request.max_files_per_request or 100):
            break
        candidate = [*selected, unit]
        if len(candidate) > min(8, width):
            break
        system, user = batch_prompt(candidate, execution, contexts)
        sizing = profile.model_copy(update={'output_mode': 'automatic'})
        output = sum(project_profile(sizing, u).max_tokens for u in candidate)
        if output > profile.max_tokens or not request_allowance(profile, system, user, privacy_chars=privacy_chars,
                                                               context_chars=execution.request.max_context_chars).valid:
            break
        selected.append(unit)
        files.add(unit.file_id)
    return tuple(selected)


def decode_batch_response(raw, units, *, settings=None):
    from dataforge.llm import response_object
    payload = response_object(raw)
    if set(payload) != {'items'} or not isinstance(payload['items'], list) or len(payload['items']) > 8:
        raise ValueError('invalid_batch_envelope')
    expected = {u.unit_id: u for u in units}
    good, errors, seen = {}, {}, set()
    for item in payload['items']:
        uid = item.get('unit_id') if isinstance(item, dict) else None
        if not isinstance(uid, str) or uid not in expected:
            continue
        if uid in seen:
            good.pop(uid, None)
            errors[uid] = 'duplicate_batch_item'
            continue
        seen.add(uid)
        try:
            good[uid] = decode_project_result('project_lineage', item, expected[uid], settings=settings)
        except ValueError:
            errors[uid] = 'invalid_batch_item'
    for uid in expected.keys() - good.keys():
        errors.setdefault(uid, 'missing_batch_item')
    return good, errors
