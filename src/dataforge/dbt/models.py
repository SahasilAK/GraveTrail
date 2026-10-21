"""Immutable project contracts and bounded non-secret analysis settings."""
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from dataforge.models import Diagnostic, ParseResult


class DbtSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    mode: Literal['source', 'enriched', 'artifact'] = 'source'
    artifact_paths: list[str] = Field(default_factory=list)
    dialect: str = ''
    public_vars: dict[str, JsonValue] = Field(default_factory=dict)
    target_label: str | None = None
    projects: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)

    @field_validator('dialect')
    @classmethod
    def dialect_known(cls, value):
        from sqlglot import Dialect
        if value not in Dialect.classes:
            raise ValueError('Unknown SQL dialect')
        return value

    @field_validator('artifact_paths')
    @classmethod
    def paths_safe(cls, values):
        from dataforge.ingestion import safe_relative
        return [safe_relative(value) for value in values]

    @field_validator('projects')
    @classmethod
    def overrides_safe(cls, values):
        from dataforge.dbt.yaml import safe_resource_path
        for root, settings in values.items():
            safe_resource_path(root)
            if 'projects' in settings:
                raise ValueError('Nested project overrides are unsupported')
            cls.model_validate(settings)
        return values


@dataclass(frozen=True)
class DbtLimits:
    max_depth: int = 64
    max_nodes: int = 100000
    max_relationships: int = 100000
    max_macro_depth: int = 30
    max_excerpt: int = 8000
    max_report_bytes: int = 1024 * 1024
    max_snapshot_bytes: int = 256 * 1024 * 1024


@dataclass(frozen=True)
class SourceRef:
    file_id: str
    content_hash: str
    relative_path: str


@dataclass(frozen=True)
class EvidenceRef:
    source: SourceRef
    start_line: int
    end_line: int
    start_offset: int
    end_offset: int
    excerpt: str
    json_pointer: str | None = None
    origin: str = 'source_static'


@dataclass(frozen=True)
class DbtContext:
    mode: str = 'source'
    artifact_file_ids: tuple[str, ...] = ()
    dialect: str = ''
    target_label: str | None = None
    public_vars: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectSnapshot:
    project_id: str
    root_path: str
    package_name: str
    sources: tuple[SourceRef, ...]
    fingerprint: str
    context: DbtContext


@dataclass(frozen=True)
class DbtResource:
    resource_id: str
    unique_id: str | None
    project_id: str
    package_name: str
    resource_type: str
    name: str
    version: str | None
    enabled: bool
    definition: EvidenceRef
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DbtRelationship:
    source_id: str
    target_id: str
    kind: str
    status: str
    evidence: tuple[EvidenceRef, ...]


@dataclass(frozen=True)
class RelationBinding:
    resource_id: str
    database: str | None
    schema: str | None
    identifier: str
    quoted: tuple[bool, bool, bool]
    context_id: str
    status: str
    evidence: tuple[EvidenceRef, ...]


@dataclass(frozen=True)
class DbtProjectResult:
    snapshot: ProjectSnapshot
    resources: tuple[DbtResource, ...] = ()
    relationships: tuple[DbtRelationship, ...] = ()
    bindings: tuple[RelationBinding, ...] = ()
    file_results: tuple[tuple[dict, ParseResult], ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    coverage: dict[str, Any] = field(default_factory=dict)
    generated_evidence: tuple[tuple[str, EvidenceRef], ...] = ()

    def to_dict(self):
        value = asdict(self)
        value['file_results'] = [({key: m[key] for key in ('file_id', 'content_hash', 'relative_path', 'extension')}, p.to_dict())
                                 for m, p in self.file_results]
        return value

    @classmethod
    def from_dict(cls, value):
        def evidence(e):
            return EvidenceRef(**{**e, 'source': SourceRef(**e['source'])})
        snap = value['snapshot']
        snapshot = ProjectSnapshot(**{**snap, 'sources': tuple(SourceRef(**s) for s in snap['sources']),
                                     'context': DbtContext(**snap['context'])})
        resources = tuple(DbtResource(**{**r, 'definition': evidence(r['definition'])}) for r in value['resources'])
        relations = tuple(DbtRelationship(**{**r, 'evidence': tuple(evidence(e) for e in r['evidence'])})
                          for r in value['relationships'])
        bindings = tuple(RelationBinding(**{**r, 'evidence': tuple(evidence(e) for e in r['evidence'])})
                         for r in value['bindings'])
        return cls(snapshot, resources, relations, bindings,
                   tuple((m, ParseResult.from_dict(p)) for m, p in value['file_results']),
                   tuple(Diagnostic(**d) for d in value['diagnostics']), value['coverage'],
                   tuple((rid, evidence(ref)) for rid, ref in value.get('generated_evidence', [])))
