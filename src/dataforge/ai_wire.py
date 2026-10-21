"""Project protocol v3 expression references; strict legacy v2 payloads remain readable."""
from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache

from pydantic import Field, create_model

from dataforge.ai_analysis_models import (
    AssetCandidate,
    ColumnCandidate,
    DerivationCandidate,
    EvidenceCitation,
    LineageReviewResponse,
    Name,
    ProjectLineageResponse,
    ReviewDecision,
    StrictModel,
    TableRelationship,
)


class EvidenceReference(StrictModel):
    unit_id: Name


class SourceCitationError(ValueError):
    """A fixed host code, safe to retain without source text or provider input."""


def _wire_model(model, **overrides):
    # Copy field constraints, not canonical validators that need hydrated source text.
    fields = {name: (field.annotation, deepcopy(field)) for name, field in model.model_fields.items()}
    fields.update(overrides)
    return create_model(model.__name__ + 'Wire', __base__=StrictModel, **fields)


WireAsset = _wire_model(AssetCandidate, evidence=(EvidenceReference, ...))
WireRelationship = _wire_model(TableRelationship, evidence=(EvidenceReference, ...))
WireColumn = _wire_model(ColumnCandidate, evidence=(EvidenceReference, ...))
WireDerivation = _wire_model(DerivationCandidate, evidence=(EvidenceReference, ...),
    expression=(str, Field(default='', max_length=20000)), expression_reference=(Name | None, None))
WireDecision = _wire_model(ReviewDecision, evidence=(list[EvidenceReference], Field(default_factory=list, max_length=20)))
WIRE_MODELS = {
    'project_lineage': _wire_model(ProjectLineageResponse,
        assets=(list[WireAsset], Field(default_factory=list, max_length=100)),
        relationships=(list[WireRelationship], Field(default_factory=list, max_length=100)),
        columns=(list[WireColumn], Field(default_factory=list, max_length=100)),
        derivations=(list[WireDerivation], Field(default_factory=list, max_length=100))),
    'lineage_review': _wire_model(LineageReviewResponse, decisions=(list[WireDecision], Field(max_length=100))),
}
CANONICAL = {'project_lineage': ProjectLineageResponse, 'lineage_review': LineageReviewResponse}


@lru_cache(maxsize=2)
def _schema_json(task):
    return json.dumps(WIRE_MODELS[task].model_json_schema())


def wire_schema(task):
    # Schema generation is model-static; return an isolated copy to each caller.
    return json.loads(_schema_json(task))


def decode_project_result(task, payload, unit, *, settings=None):
    values = WIRE_MODELS[task].model_validate(payload).model_dump()
    citation = EvidenceCitation.from_unit(unit).model_dump()

    def hydrate(reference):
        if reference['unit_id'] != unit.unit_id:
            raise ValueError('Evidence references an unknown immutable unit')
        return citation.copy()

    if task == 'project_lineage':
        references = None
        for group in ('assets', 'relationships', 'columns', 'derivations'):
            for claim in values[group]:
                claim['evidence'] = hydrate(claim['evidence'])
                if group == 'derivations':
                    reference_id = claim.pop('expression_reference')
                    if reference_id is not None:
                        if references is None:
                            from dataforge.ai_citations import source_references
                            references = {r['reference_id']: r for r in source_references(unit, settings)}
                        reference = references.get(reference_id)
                        if reference is None:
                            raise SourceCitationError('unknown_source_expression_reference')
                        for field, expected in [('expression', reference['text']),
                                                ('expression_start_offset', reference['start_offset']),
                                                ('expression_end_offset', reference['end_offset'])]:
                            if claim.get(field) not in (None, '') and claim[field] != expected:
                                raise SourceCitationError('conflicting_source_expression_reference')
                            claim[field] = expected
    else:
        for decision in values['decisions']:
            decision['evidence'] = [hydrate(ref) for ref in decision['evidence']]
    result = CANONICAL[task].model_validate(values)
    if task == 'project_lineage':
        result.assert_unit(unit)
    return result


def encode_project_result(result):
    values = result.model_dump()
    if isinstance(result, ProjectLineageResponse):
        for group in ('assets', 'relationships', 'columns', 'derivations'):
            for claim in values[group]:
                claim['evidence'] = {'unit_id': claim['evidence']['unit_id']}
    else:
        for decision in values['decisions']:
            decision['evidence'] = [{'unit_id': ref['unit_id']} for ref in decision['evidence']]
    return values
