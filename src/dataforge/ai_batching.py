"""Pure bounded multi-unit prompts; responses retain independent unit authority."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class PlannedRequest:
    payload: dict
    serialized_payload: str
    part_ids: tuple[str, ...]
    reserved_output: int
    budget: object
    system: str
    user: str


@lru_cache(maxsize=1)
def _extraction_schema():
    from dataforge.ai_analysis_models import PartExtraction
    return json.dumps(PartExtraction.model_json_schema(), ensure_ascii=False, separators=(',', ':'))


def extraction_instructions():
    from dataforge.llm import PROMPTS
    instructions = (PROMPTS / 'project_lineage' / 'extract.md').read_text(encoding='utf-8')
    return instructions + '\nReturn {"items": [item, ...]}. Item schema:\n' + _extraction_schema()


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
        candidate = {'part': part.model_dump(), 'path': source.path, 'source': code if part.work_kind != 'consolidation' else '',
                     'saved_details': detail}
        estimate = 256 + len((code if detail is None else json.dumps(detail, ensure_ascii=False)).encode('utf-8')) // 2
        if output_estimate + estimate > reserve:
            if selected:
                break
            raise ValueError('part_output_estimate_exceeds_budget')
        candidate_definitions = {**definitions, **{entry['entry_id']: entry for entry in
            context.get('definitions', {}).get(part.part_id, [])}}
        user = json.dumps({'protocol_version': 5, 'items': [*items, candidate],
                           'definitions': list(candidate_definitions.values()), 'settings': context.get('settings', {})},
                          ensure_ascii=False, separators=(',', ':'))
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
