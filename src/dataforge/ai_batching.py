"""Pure bounded multi-unit prompts; responses retain independent unit authority."""
from __future__ import annotations

import json
from copy import copy
from dataclasses import dataclass

from dataforge.ai_budget import project_profile, request_allowance
from dataforge.ai_wire import decode_project_result


@dataclass(frozen=True)
class PlannedRequest:
    payload: dict
    serialized_payload: str
    part_ids: tuple[str, ...]
    reserved_output: int
    budget: object
    system: str
    user: str


def extraction_instructions():
    from dataforge.ai_analysis_models import PartExtraction
    from dataforge.llm import PROMPTS
    instructions = (PROMPTS / 'project_lineage' / 'extract.md').read_text(encoding='utf-8')
    return instructions + '\nReturn {"items": [item, ...]}. Item schema:\n' + json.dumps(
        PartExtraction.model_json_schema(), ensure_ascii=False, separators=(',', ':'))


def pack_request(pending_parts, profile, context):
    """Greedy file-first packing bounded by the complete provider body and output."""
    from dataforge.ai_budget import request_budget
    from dataforge.llm import Adapter
    system = extraction_instructions()
    sources = context['sources']
    selected, items, definitions = [], [], {}
    output_estimate = 0
    reserve = profile.max_tokens
    last = None
    for part in pending_parts:
        source = sources[part.file_id]
        code = source.code[part.start_offset:part.end_offset]
        detail = context.get('work_inputs', {}).get(part.part_id)
        candidate = {'part': part.model_dump(), 'path': source.path, 'source': code if detail is None else '',
                     'saved_details': detail}
        estimate = max(128, 128 + len(json.dumps(candidate, ensure_ascii=False).encode('utf-8')) // 2)
        if output_estimate + estimate > reserve:
            if selected:
                break
            raise ValueError('part_output_estimate_exceeds_budget')
        candidate_definitions = {**definitions, **{entry['entry_id']: entry for entry in
            context.get('definitions', {}).get(part.part_id, [])}}
        user = json.dumps({'protocol_version': 5, 'items': [*items, candidate],
                           'definitions': list(candidate_definitions.values())}, ensure_ascii=False, separators=(',', ':'))
        _, payload = Adapter.completion_request(profile, system, user)
        serialized = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        disclosed = sum(len(i['source']) for i in [*items, candidate]) + sum(
            len(e.get('source', '')) for e in candidate_definitions.values())
        budget = request_budget(profile, serialized, reserve, disclosed_characters=disclosed)
        if not budget.fits:
            if selected:
                break
            raise ValueError(','.join(budget.reasons))
        selected.append(part.part_id)
        items.append(candidate)
        definitions = candidate_definitions
        output_estimate += estimate
        last = PlannedRequest(payload, serialized, tuple(selected), reserve, budget, system, user)
    if last is None:
        raise ValueError('empty_request')
    return last


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
