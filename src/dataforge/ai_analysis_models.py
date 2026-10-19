"""Bounded project-analysis contracts; model output never grants publication rights."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AnalysisMode = Literal['parser', 'hybrid', 'ai']
Name = Annotated[str, Field(min_length=1, max_length=500)]
Role = Literal['value', 'value_selection', 'row_filter', 'join', 'partition', 'order', 'rowset']
Version = Annotated[str, Field(max_length=500)] | Annotated[int, Field(ge=0, le=100000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class AnalysisRequest(StrictModel):
    mode: AnalysisMode = 'parser'
    file_ids: list[Name] | None = Field(default=None, max_length=10000)
    force_parser: bool = False
    refresh_ai: bool = False
    additional_ai_review: bool = False
    max_provider_attempts: int = Field(default=200, ge=1, le=2000)
    max_output_tokens_total: int = Field(default=200000, ge=1000, le=2000000)
    max_seconds: int = Field(default=1800, ge=30, le=14400)

    @model_validator(mode='after')
    def unique_files(self):
        if self.file_ids is not None and len(set(self.file_ids)) != len(self.file_ids):
            raise ValueError('Selected file IDs must be unique')
        return self


class AnalysisUnit(StrictModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    unit_id: Name
    file_id: Name
    content_hash: Name
    path: str = Field(max_length=4000)
    extension: Literal['.sql', '.sas']
    job_id: str = Field(default='', max_length=500)
    first: int = Field(ge=1)
    last: int = Field(ge=1)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=1)
    code: str = Field(min_length=1, max_length=200000)

    @model_validator(mode='after')
    def ordered(self):
        if self.last < self.first or self.end_offset - self.start_offset != len(self.code):
            raise ValueError('Unit coordinates must delimit its exact code')
        if self.last - self.first != self.code.count('\n'):
            raise ValueError('Unit line coordinates must match code')
        return self


class EvidenceCitation(StrictModel):
    unit_id: Name
    file_id: Name
    content_hash: Name
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=200000)

    @model_validator(mode='after')
    def ordered(self):
        if self.end_line < self.start_line or self.end_offset <= self.start_offset:
            raise ValueError('Evidence coordinates are reversed')
        return self

    @classmethod
    def from_unit(cls, unit):
        return cls(unit_id=unit.unit_id,file_id=unit.file_id,content_hash=unit.content_hash,
                   start_line=unit.first,end_line=unit.last,start_offset=unit.start_offset,
                   end_offset=unit.end_offset,quote=unit.code)

    def assert_unit(self, unit):
        if self != self.from_unit(unit):
            raise ValueError('Evidence must cite the complete original unit with exact identity and coordinates')


class Coverage(StrictModel):
    status: Literal['complete', 'partial', 'unsupported', 'no_operations'] = 'partial'
    unsupported: list[Name] = Field(default_factory=list, max_length=100)


class AssetCandidate(StrictModel):
    name: Name
    kind: Literal['table', 'view', 'dataset'] = 'table'
    role: Literal['read', 'write', 'declaration']
    evidence: EvidenceCitation


class TableRelationship(StrictModel):
    source: Name
    target: Name
    operation: str = Field(min_length=1, max_length=100)
    evidence: EvidenceCitation


class ColumnCandidate(StrictModel):
    table: Name
    column: Name
    context: str = Field(min_length=1, max_length=100)
    alias: str = Field(default='', max_length=500)
    expression: str = Field(default='', max_length=20000)
    evidence: EvidenceCitation


class DerivationInput(StrictModel):
    table: Name
    column: str = Field(max_length=500)
    role: Role = 'value'
    scope: str = Field(default='', max_length=500)
    version: Version = ''


class DerivationCandidate(StrictModel):
    target_table: Name
    target_column: Name
    expression: str = Field(min_length=1, max_length=20000)
    category: str = Field(min_length=1, max_length=100)
    scope: str = Field(default='', max_length=500)
    branch: int = Field(default=0, ge=0, le=100000)
    version: Version = ''
    ordinal: int = Field(default=0, ge=0, le=100000)
    inputs: list[DerivationInput] = Field(default_factory=list, max_length=100)
    evidence: EvidenceCitation
    expression_start_offset: int | None = Field(default=None, ge=0)
    expression_end_offset: int | None = Field(default=None, ge=1)

    @model_validator(mode='after')
    def expression_span(self):
        a,b = self.expression_start_offset,self.expression_end_offset
        if a is None and b is None:
            position = self.evidence.quote.find(self.expression)
            if position < 0 or self.evidence.quote.find(self.expression, position + 1) >= 0:
                raise ValueError('Omitted expression offsets require a unique exact substring')
            a = self.evidence.start_offset + position
            b = a + len(self.expression)
            self.expression_start_offset, self.expression_end_offset = a,b
        elif a is None or b is None:
            raise ValueError('Supply both expression offsets or omit both')
        if not self.evidence.start_offset <= a < b <= self.evidence.end_offset:
            raise ValueError('Expression is outside full-unit evidence')
        if self.evidence.quote[a-self.evidence.start_offset:b-self.evidence.start_offset] != self.expression:
            raise ValueError('Expression span must match original text exactly')
        return self


class ProjectLineageResponse(StrictModel):
    unit_id: Name
    assets: list[AssetCandidate] = Field(default_factory=list, max_length=100)
    relationships: list[TableRelationship] = Field(default_factory=list, max_length=100)
    columns: list[ColumnCandidate] = Field(default_factory=list, max_length=100)
    derivations: list[DerivationCandidate] = Field(default_factory=list, max_length=100)
    unresolved_symbols: list[Name] = Field(default_factory=list, max_length=100)
    coverage: Coverage = Field(default_factory=Coverage)

    def assert_unit(self, unit):
        if self.unit_id != unit.unit_id:
            raise ValueError('Response references an unknown unit')
        for claim in [*self.assets,*self.relationships,*self.columns,*self.derivations]:
            claim.evidence.assert_unit(unit)


class ReviewDecision(StrictModel):
    candidate_id: Name
    decision: Literal['supported','contradicted','insufficient_evidence']
    evidence: list[EvidenceCitation] = Field(default_factory=list,max_length=20)
    reason: str = Field(default='',max_length=2000)

    @model_validator(mode='after')
    def supported_evidence(self):
        if self.decision != 'insufficient_evidence' and not self.evidence:
            raise ValueError('A supported or contradicted verdict requires original evidence')
        return self


class LineageReviewResponse(StrictModel):
    decisions: list[ReviewDecision] = Field(max_length=100)

    @model_validator(mode='after')
    def unique(self):
        if len({d.candidate_id for d in self.decisions}) != len(self.decisions):
            raise ValueError('Duplicate candidate decisions')
        return self

    def assert_candidates(self, expected):
        if {d.candidate_id for d in self.decisions} != set(expected):
            raise ValueError('Review must decide exactly the host-issued candidates')


class ValidationContext(StrictModel):
    unit: AnalysisUnit
    workspace_id: str = ''
    source_text: str = ''
    settings: dict[str, Any] = Field(default_factory=dict)
    catalog: list[dict[str, Any]] = Field(default_factory=list)
    parser_result: Any = None


class NormalizedFact(StrictModel):
    kind: Literal['table_edge','direct_usage','derivation']
    unit_id: Name
    evidence_key: Name
    evidence: EvidenceCitation
    candidate_id: str = ''
    source: str = ''
    target: str = ''
    table: str = ''
    column: str = ''
    expression: str = ''
    scope: str = ''
    branch: int = 0
    version: Version = ''
    ordinal: int = 0
    inputs: list[DerivationInput] = Field(default_factory=list,max_length=100)
    operation: str = ''
    status: Literal['verified','inferred','unresolved'] = 'inferred'
    origin: Literal['parser','ai','both'] = 'ai'
    detail: dict[str, Any] = Field(default_factory=dict)


class ClaimDecision(StrictModel):
    candidate_id: str = ''
    reason: str
    status: Literal['accepted','rejected','unresolved']
    evidence: EvidenceCitation | None = None


class ValidationReport(StrictModel):
    assets: list[dict[str, Any]] = Field(default_factory=list)
    accepted: list[NormalizedFact] = Field(default_factory=list)
    rejected: list[ClaimDecision] = Field(default_factory=list)
    unresolved: list[ClaimDecision] = Field(default_factory=list)
    coverage: Coverage = Field(default_factory=Coverage)


class ReconciliationReport(StrictModel):
    facts: list[NormalizedFact] = Field(default_factory=list)
    decisions: list[ClaimDecision] = Field(default_factory=list)
    counts: dict[str,int] = Field(default_factory=dict)


class UnitAttemptResult(StrictModel):
    unit_id: str
    task: str
    result: ProjectLineageResponse | LineageReviewResponse | None = None
    record_id: str = ''
    outcome: str = 'validated'
    reason: str = ''
    usage: dict[str,Any] = Field(default_factory=dict)
    usage_known: bool = False
    attempts: int = 0
    requested_model: str = ''
    resolved_model: str | None = None
    finish_reason: str | None = None
    prompt_hash: str = ''

    @property
    def response(self):
        return self.result


class AnalysisReport(StrictModel):
    run_id: str = ''
    mode: AnalysisMode
    status: str
    complete: bool = False
    counts: dict[str,int] = Field(default_factory=dict)
    usage_known: bool = False
    reasons: list[str] = Field(default_factory=list)
