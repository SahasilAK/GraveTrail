"""Source-backed expression components; only complete, validated unions become facts."""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass

from dataforge.ai_analysis_models import (
    DerivationCandidate,
    DerivationInput,
    EvidenceCitation,
    NormalizedFact,
    ProjectLineageResponse,
    ValidationReport,
)
from dataforge.models import stable_id


def merge_extraction_revision(original, replacement):
    """Retain original facts unless explicitly superseded; conflicts stay visible."""
    from dataforge.ai_analysis_models import PartExtraction
    result = PartExtraction.model_validate(original).model_copy(deep=True)
    known = {d.fact_id for op in result.operations for d in op.derivations}
    superseded = set(replacement.superseded_fact_ids)
    if superseded - known:
        raise ValueError('unknown_superseded_fact')
    retired = set(replacement.superseded_operation_ids)
    if retired - {op.operation_id for op in result.operations}:
        raise ValueError('unknown_superseded_operation')
    result.operations = [op for op in result.operations if op.operation_id not in retired]
    result.revision += 1
    result.superseded_fact_ids = sorted(set(result.superseded_fact_ids) | superseded)
    result.definitions.extend(replacement.definitions)
    result.missing_context = replacement.missing_context
    result.unresolved.extend(replacement.unresolved)
    by_id = {op.operation_id: op for op in result.operations}
    for op in result.operations:
        op.derivations = [d for d in op.derivations if d.fact_id not in superseded]
    for op in replacement.operations:
        if op.operation_id not in by_id:
            by_id[op.operation_id] = op
            continue
        old = by_id[op.operation_id]
        for name in ('reads', 'writes', 'usages', 'derivations', 'limitations', 'context_ids'):
            values = getattr(old, name)
            for value in getattr(op, name):
                if value not in values:
                    if name == 'derivations' and any(d.fact_id == value.fact_id for d in values):
                        result.unresolved.append('conflicting_replacement:' + value.fact_id)
                        for previous in values:
                            if previous.fact_id == value.fact_id:
                                previous.status = 'unresolved'
                        value = value.model_copy(update={'status': 'unresolved'})
                    values.append(value)
    result.operations = list(by_id.values())
    result.omitted |= replacement.omitted
    result.coverage = 'partial' if result.unresolved or result.missing_context or result.omitted else replacement.coverage
    return result




@dataclass(frozen=True)
class ConsolidationWork:
    part: object
    inputs: dict
    overflow: bool = False


def plan_file_consolidation(parts, limits):
    from dataforge.ai_batching import extraction_instructions
    from dataforge.ai_budget import request_budget
    from dataforge.llm import Adapter
    from dataforge.models import stable_id
    if len(parts) < 2:
        return []
    groups = {}
    for part, result in parts:
        for operation in result.operations:
            groups.setdefault(operation.scope, []).append((part, operation))
    work = []
    for scope, entries in sorted(groups.items()):
        if len({p.part_id for p, _ in entries}) < 2:
            continue
        base = entries[0][0]
        evidence = [r for _, op in entries for r in [*op.evidence,
            *[r for usage in op.usages for r in usage.evidence],
            *[r for d in op.derivations for r in [*d.evidence, *([d.expression] if d.expression else [])]]]]
        part = base.model_copy(update={'part_id': stable_id('consolidation5', base.file_id, base.content_hash, scope),
            'work_kind': 'consolidation', 'scope': scope,
            'start_offset': min(p.start_offset for p, _ in entries),
            'end_offset': max(p.end_offset for p, _ in entries), 'context_references': evidence})
        inputs = {'operations': [op.model_dump() for _, op in entries],
                  'part_ids': sorted({p.part_id for p, _ in entries})}
        user = json.dumps({'protocol_version': 5, 'items': [{'part': part.model_dump(), 'source': '',
                           'saved_details': inputs}], 'definitions': []}, ensure_ascii=False)
        _, payload = Adapter.completion_request(limits, extraction_instructions(), user)
        serialized = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        overflow = not request_budget(limits, serialized, limits.max_tokens).fits or len(user.encode()) // 2 + 128 > limits.max_tokens
        work.append(ConsolidationWork(part, inputs, overflow))
    return work


def assemble_file_extraction(source, parts, consolidations, *, provenance):
    from dataforge.ai_analysis_models import FileExtraction, PartExtraction
    combined = PartExtraction(part_id='combined')
    for _, item in parts:
        combined = merge_extraction_revision(combined, item.model_copy(update={'superseded_fact_ids': [], 'superseded_operation_ids': []}))
    for item in consolidations:
        combined = merge_extraction_revision(combined, item)
    return FileExtraction(file_id=source.file_id, content_hash=source.content_hash, source_kind=source.source_kind,
        part_ids=[p.part_id for p, _ in parts], operations=combined.operations,
        assets=[a for _, result in parts for a in result.assets],
        unresolved=[*combined.unresolved, *[m.reason + ':' + m.symbol for _, r in parts for m in r.missing_context],
                    *['context_not_supplied:' + entry for p, _ in parts for entry in p.context_omissions]],
        semantic_coverage='partial' if combined.unresolved or combined.omitted or any(
            r.coverage not in {'complete', 'no_operations'} or r.missing_context for _, r in parts) else 'model_reported_complete',
        provenance=provenance)




def validate_fragment(claim, context, operations, visible, names):
    from dataforge.ai_source_views import identifier_name
    from dataforge.ai_validation import _bounded_dml, _same_derivation, input_key
    if not context.unit.source_focus or not visible:
        return None
    span = [claim.expression_start_offset, claim.expression_end_offset]
    if not any(max(span[0], s['start_offset']) < min(span[1], s['end_offset']) for s in visible):
        return None
    matches = []
    for operation, start, stop, key in operations:
        for record in [*operation.derivations, *_bounded_dml(operation, context)]:
            if record.get('status') != 'verified' or record.get('coverage'):
                continue
            complete = claim.model_copy(update={'inputs': [DerivationInput.model_validate(i) for i in record['inputs']],
                                                'fragment': False})
            if (not _same_derivation(complete, record, context) or not start <= span[0] < span[1] <= stop
                    or ('_expression_offset' in record and span[0] != start + record['_expression_offset'])):
                continue
            expected = set(input_key(record['inputs'], context))
            if not set(input_key([i.model_dump() for i in claim.inputs], context)) <= expected:
                continue
            if any(identifier_name(i.column or i.table) not in names for i in claim.inputs):
                continue
            matches.append(key)
    if len(set(matches)) != 1:
        return None
    fields = claim.model_dump(exclude={'evidence', 'expression', 'inputs'})
    fields['fragment'] = False
    return {'candidate_id': stable_id(context.unit.unit_id, 'fragment', json.dumps(fields, sort_keys=True),
                                     json.dumps([i.model_dump() for i in claim.inputs], sort_keys=True)),
            'unit_id': context.unit.unit_id, 'claim': fields, 'span': span,
            'inputs': [i.model_dump() for i in claim.inputs],
            'ranges': [[max(span[0], s['start_offset']), min(span[1], s['end_offset'])] for s in visible
                       if max(span[0], s['start_offset']) < min(span[1], s['end_offset'])]}


def compose_fragments(reports, context):
    """No model call or whole-expression prompt: combine only complete source coverage."""
    from dataforge.ai_validation import validate_project_response
    groups = defaultdict(list)
    for report in reports:
        for fragment in report.fragments:
            groups[json.dumps(fragment['claim'], sort_keys=True)].append(fragment)
    result = ValidationReport()
    for fragments in groups.values():
        first = fragments[0]
        start, end = first['span']
        cursor = start
        for a, b in sorted(r for f in fragments for r in f['ranges']):
            if a > cursor:
                break
            cursor = max(cursor, b)
        if cursor < end:
            continue
        inputs = {json.dumps(i, sort_keys=True): i for f in fragments for i in f['inputs']}
        claim = DerivationCandidate.model_validate({**first['claim'],
            'expression': context.source_text[start:end], 'inputs': [inputs[key] for key in sorted(inputs)],
            'evidence': EvidenceCitation.from_unit(context.unit)})
        validated = validate_project_response(ProjectLineageResponse(unit_id=context.unit.unit_id,
            derivations=[claim]), context)
        for fact in validated.accepted:
            fact.detail['source_view_units'] = sorted({f['unit_id'] for f in fragments})
        result.accepted.extend(validated.accepted)
        result.rejected.extend(validated.rejected)
        result.unresolved.extend(validated.unresolved)
    return result


def fragment_review_facts(report, unit):
    """Review bounded dependency components, never resend the whole expression."""
    result = []
    for fragment in report.fragments:
        fields = fragment['claim']
        for index, item in enumerate(fragment['inputs'] or [None]):
            result.append(NormalizedFact(kind='derivation', unit_id=unit.unit_id,
                evidence_key='fragment', evidence=EvidenceCitation.from_unit(unit),
                candidate_id=stable_id(fragment['candidate_id'], str(index)),
                table=fields['target_table'], column=fields['target_column'],
                scope=fields.get('scope', ''), branch=fields.get('branch', 0),
                version=fields.get('version', ''), ordinal=fields.get('ordinal', 0),
                expression=unit.code[fragment['span'][0]-unit.start_offset:fragment['span'][1]-unit.start_offset],
                operation='expression_component:' + fields['category'], inputs=[item] if item else []))
    return result


def review_facts(report, unit):
    # Derived unions are reviewed through their persisted source components.
    return [f for f in report.accepted if not f.detail.get('source_view_units')] + fragment_review_facts(report, unit)


def retain_reviewed_fragments(report, rejected_ids):
    report.fragments = [f for f in report.fragments if not any(
        stable_id(f['candidate_id'], str(i)) in rejected_ids for i in range(max(1, len(f['inputs']))))]
