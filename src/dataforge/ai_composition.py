"""Source-backed expression components; only complete, validated unions become facts."""
from __future__ import annotations

import json
from collections import defaultdict

from dataforge.ai_analysis_models import (
    DerivationCandidate,
    DerivationInput,
    EvidenceCitation,
    NormalizedFact,
    ProjectLineageResponse,
    ValidationReport,
)
from dataforge.models import stable_id


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
