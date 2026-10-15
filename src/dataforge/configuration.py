"""Validated workspace identity and safe, versioned configuration portability."""
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlglot import Dialect


class ParsingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dialect: str = ""
    dialect_by_folder: dict[str, str] = Field(default_factory=dict)
    dialect_by_extension: dict[str, str] = Field(default_factory=dict)
    library_mappings: dict[str, str] = Field(default_factory=dict)
    macros: dict[str, str] = Field(default_factory=dict)
    case_sensitive: bool = False
    expand_wildcards: bool = True
    default_job: str = "workspace"
    job_by_folder: dict[str, str] = Field(default_factory=dict)

    @field_validator("default_job")
    @classmethod
    def job_identifier(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value):
            raise ValueError("Job IDs require 1–64 letters, digits, dots, underscores or hyphens")
        return value

    @field_validator("job_by_folder")
    @classmethod
    def folder_jobs(cls, value):
        for prefix, job in value.items():
            if not prefix or prefix.startswith("/") or "\\" in prefix or ".." in prefix.split("/") or not prefix.endswith("/"):
                raise ValueError("Job folder prefixes must be relative folders ending with /")
            cls.job_identifier(job)
        return value

    @field_validator("dialect")
    @classmethod
    def dialect_known(cls, value):
        if value not in Dialect.classes:
            raise ValueError("Unknown SQL dialect")
        return value

    @field_validator("dialect_by_folder")
    @classmethod
    def folder_dialects_known(cls, value):
        if any(d not in Dialect.classes for d in value.values()):
            raise ValueError("Unknown SQL dialect in folder mappings")
        return value

    @field_validator("dialect_by_extension")
    @classmethod
    def extension_dialects_known(cls, value):
        if any(k not in {".sql", ".sas"} or v not in Dialect.classes for k, v in value.items()):
            raise ValueError("Extension dialects require .sql/.sas keys and known SQL dialects")
        return value


class WorkspaceIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)

    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class VisualizationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    graph_direction: Literal["upstream", "downstream", "combined"] = "upstream"
    collapse_temporary: bool = True
    graph_labels: Literal["compact", "full", "hidden"] = "compact"
    graph_palette: Literal["semantic", "neutral"] = "semantic"
    graph_edge_width: int = Field(default=2, ge=1, le=5)
    source_view_mode: Literal["complete", "relevant"] = "complete"
    source_line_numbers: bool = True

    @classmethod
    def from_store(cls, store, workspace):
        return cls.model_validate({key: store.setting(workspace, key, field.default)
                                   for key, field in cls.model_fields.items()})


class LLMResourceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    llm_concurrency: int = Field(default=1, ge=1, le=4)
    llm_chunk_chars: int = Field(default=4000, ge=500, le=100000)


class AnalysisPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    min_lineage_confidence: float = Field(default=0., ge=0, le=1)
    include_inferred: bool = True
    diagnostic_visibility: Literal["all", "warnings_errors", "errors"] = "all"
    reanalysis_mode: Literal["changed", "all"] = "changed"


class PortableSettings(ParsingSettings, VisualizationSettings, LLMResourceSettings, AnalysisPreferences):
    """Explicit allowlist: no network, secrets, AI retention, or transmission permissions."""
    max_file_mb: int = Field(default=20, ge=1, le=100)
    max_files: int = Field(default=10000, ge=1, le=100000)
    parse_workers: int = Field(default=1, ge=1, le=8)
    graph_limit: int = Field(default=150, ge=10, le=1000)
    traversal_depth: int = Field(default=5, ge=1, le=30)
    tree_expansion_depth: int = Field(default=1, ge=0, le=30)


class WorkspaceConfiguration(WorkspaceIdentity):
    format: Literal["dataforge-metadata-v2"] = "dataforge-metadata-v2"
    settings: PortableSettings = Field(default_factory=PortableSettings)


def export_workspace_configuration(store, workspace: str) -> str:
    with store.lock:
        identities = store.rows("SELECT name,description FROM workspaces WHERE workspace_id=?", [workspace])
        if not identities:
            raise ValueError("Workspace does not exist")
        settings = {r["key"]: json.loads(r["value"]) for r in store.rows(
            "SELECT key,value FROM settings WHERE workspace_id=?", [workspace])
            if r["key"] in PortableSettings.model_fields}
        config = WorkspaceConfiguration(**identities[0], settings=PortableSettings.model_validate(settings))
    return config.model_dump_json(indent=2)


def import_workspace_configuration(store, payload: str | bytes) -> str:
    if len(payload) > 1024 * 1024:
        raise ValueError("Workspace configuration exceeds 1 MB")
    obj = json.loads(payload)
    if not isinstance(obj, dict):
        raise ValueError("Workspace configuration must be a JSON object")
    if obj.get("format") == "dataforge-metadata-v1":
        old_settings = obj.get("settings", {})
        if not isinstance(old_settings, dict):
            raise ValueError("Workspace settings must be a JSON object")
        # Earlier exports included privacy/opaque settings. Never restore those permissions.
        obj = {**obj, "format": "dataforge-metadata-v2", "settings": {
            k: v for k, v in old_settings.items() if k in PortableSettings.model_fields}}
    config = WorkspaceConfiguration.model_validate(obj)
    with store.transaction():
        workspace = store.create_workspace(config.name[:189] + " (imported)", config.description)
        for key, value in config.settings.model_dump().items():
            store.set_setting(workspace, key, value)
    return workspace
