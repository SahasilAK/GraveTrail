"""Pure bounded multi-unit prompts; responses retain independent unit authority."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

# A singleton planned at the input boundary must still fit safe corrective
# feedback. Fit this real envelope too; it is not sent on the first attempt.
RECOVERY_FEEDBACK_RESERVE = {'code': 'x' * 64, 'path': 'x' * 200, 'attempt': 99999999999999999999}


@dataclass(frozen=True)
class PlannedRequest:
    payload: dict
    serialized_payload: str
    part_ids: tuple[str, ...]
    reserved_output: int
    budget: object
    system: str
    user: str
    packing: dict


@lru_cache(maxsize=1)
def _extraction_schema():
    from dataforge.ai_analysis_models import PartExtraction
    return json.dumps(PartExtraction.model_json_schema(), ensure_ascii=False, separators=(',', ':'))


def extraction_instructions():
    from dataforge.llm import PROMPTS
    instructions = (PROMPTS / 'project_lineage' / 'extract.md').read_text(encoding='utf-8')
    return instructions + '\nReturn {"items": [item, ...]}. Item schema:\n' + _extraction_schema()


def pack_request(pending_parts, profile, context):
    """Fit the oldest item first, then fill spare capacity with eligible items."""
    from dataforge.ai_budget import request_budget
    from dataforge.llm import Adapter
    system = extraction_instructions()
    sources = context['sources']
    selected, items, definitions = [], [], {}
    output_estimate = 0
    reserve = profile.max_tokens
    last = None
    stops = set()
    for part in pending_parts:
        source = sources[part.file_id]
        code = source.code[part.start_offset:part.end_offset]
        detail = context.get('work_inputs', {}).get(part.part_id)
        candidate = {'part': part.model_dump(), 'path': source.path, 'source': code if part.work_kind != 'consolidation' else '',
                     'saved_details': detail}
        feedback = context.get('recovery_feedback', {}).get(part.part_id)
        if feedback:
            candidate['validation_feedback'] = feedback
        if part.overlap:
            candidate['overlap'] = [{'reference': ref.model_dump(),
                'source': sources[ref.file_id].code[ref.start_offset:ref.end_offset]} for ref in part.overlap]
        estimate = 256 + len((code if detail is None else json.dumps(detail, ensure_ascii=False)).encode('utf-8')) // 2
        if output_estimate + estimate > reserve:
            if selected:
                stops.add('expected_output_budget')
                continue
            raise ValueError('part_output_estimate_exceeds_budget')
        candidate_definitions = {**definitions, **{entry['entry_id']: entry for entry in
            context.get('definitions', {}).get(part.part_id, [])}}
        user = json.dumps({'protocol_version': 5, 'items': [*items, candidate],
                           'definitions': list(candidate_definitions.values()), 'settings': context.get('settings', {})},
                          ensure_ascii=False, separators=(',', ':'))
        _, payload = Adapter.completion_request(profile, system, user)
        serialized = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        disclosed = sum(len(i['source']) + sum(len(o['source']) for o in i.get('overlap', [])) for i in [*items, candidate]) + sum(
            len(e.get('source', '')) for e in candidate_definitions.values())
        budget = request_budget(profile, serialized, reserve, disclosed_characters=disclosed)
        if not budget.fits:
            if selected:
                stops.update('disclosure_limit' if r == 'explicit_disclosure_limit_exceeded' else
                             'input_budget' if r == 'complete_request_exceeds_input_budget' else r for r in budget.reasons)
                continue
            raise ValueError(','.join(budget.reasons))
        selected.append(part.part_id)
        items.append(candidate)
        definitions = candidate_definitions
        output_estimate += estimate
        last = PlannedRequest(payload, serialized, tuple(selected), reserve, budget, system, user, {})
    if last is None:
        raise ValueError('empty_request')
    last.packing.update(stop_reasons=sorted(stops) or ['no_remaining_work'],
        expected_output_tokens=output_estimate, reserved_output_tokens=reserve,
        input_utilization=last.budget.input_count / last.budget.input_limit if last.budget.input_limit else None,
        configured_output_allowance=profile.max_tokens,
        advertised_output_capacity=profile.model_capabilities.output_tokens if profile.model_capabilities else None)
    return last
