"""Bounded requests, local launch permissions and machine-readable failures."""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def compact(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


class AgentError(Exception):
    def __init__(self, code: str, message: str, **details):
        super().__init__(message)
        self.code, self.details = code, details

    def response(self):
        return {"error": {"code": self.code, "message": str(self), **self.details}}


@dataclass(frozen=True)
class AccessPolicy:
    allow_write: bool = False
    workspaces: tuple[str, ...] | None = None
    import_roots: tuple[str, ...] = ()

    def permits(self, workspace: str):
        return self.workspaces is None or workspace in self.workspaces

    def import_path(self, value: str) -> Path:
        path = Path(value).resolve()
        if not any(path.is_relative_to(Path(root).resolve()) for root in self.import_roots):
            raise AgentError("forbidden", "Import path is outside configured allowed roots")
        if not path.exists() or path.is_symlink():
            raise AgentError("invalid_path", "Import path must be an existing directory or ZIP")
        return path


class QueryOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    detail_level: Literal["summary", "standard", "detailed"] = "summary"
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = Field(default=None, max_length=1024)
    max_depth: int = Field(default=15, ge=1, le=30)
    max_items: int = Field(default=2000, ge=1, le=20000)
    max_chars: int = Field(default=12000, ge=512, le=100000)
    collapse_temporary: bool | None = None


class AgentSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    allow_write: bool = True
    allow_source: bool = True
    default_detail: Literal["summary", "standard", "detailed"] = "summary"
    max_chars: int = Field(default=12000, ge=512, le=100000)
    audit_reads: bool = False

    @classmethod
    def from_store(cls, store, workspace):
        return cls.model_validate(store.setting(workspace, "agent_access", {}))

    @staticmethod
    def access_path(home, workspace):
        if not re.fullmatch(r"[a-f0-9]{32}", workspace):
            raise AgentError("not_found", "Workspace does not exist")
        return home / "agent" / "access" / (workspace + ".json")

    def save(self, store, workspace):
        # Also publish a credential-free revocation snapshot for DB-free job polling.
        path = self.access_path(store.home, workspace)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix("." + uuid.uuid4().hex + ".tmp")
        temporary.write_text(compact(self.model_dump()), encoding="utf-8")
        temporary.replace(path)
        store.set_setting(workspace, "agent_access", self.model_dump())


def job_settings(home, workspace, record):
    path = AgentSettings.access_path(home, workspace)
    if path.exists():
        return AgentSettings.model_validate_json(path.read_text(encoding="utf-8"))
    return AgentSettings.model_validate(record.get("access", {}))
