"""Bounded requests, local launch permissions and machine-readable failures."""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def compact(value: Any) -> str:
    """Serialize a value as compact UTF-8-friendly JSON text.

    Args:
        value: JSON-compatible value to serialize.

    Returns:
        JSON text with whitespace between tokens omitted.
    """
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


class AgentError(Exception):
    """Represent a sanitized, machine-readable agent operation failure."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        """Create an error with its stable code and response details.

        Args:
            code: Stable error identifier exposed to clients.
            message: User-facing summary of the failure.
            **details: Additional structured fields included in the response.
        """
        super().__init__(message)
        self.code, self.details = code, details

    def response(self) -> dict[str, Any]:
        """Return the error in the agent's response envelope."""
        return {"error": {"code": self.code, "message": str(self), **self.details}}


@dataclass(frozen=True)
class AccessPolicy:
    """Hold the operation permissions granted to one local agent launch."""

    allow_write: bool = False
    workspaces: tuple[str, ...] | None = None
    import_roots: tuple[str, ...] = ()
    allow_config_write: bool = False
    allow_llm: bool = False
    allowed_llm_origins: tuple[str, ...] = ()
    allowed_credential_refs: tuple[str, ...] = ()
    allow_application_config: bool = False
    allow_admin: bool = False

    def require(self, effect: str) -> None:
        """Raise when the launch policy does not grant an effect.

        Args:
            effect: Permission category requested by the operation.

        Raises:
            AgentError: If the requested effect is not authorized.
        """
        permitted = {
            'config': self.allow_write and self.allow_config_write,
            'network': self.allow_write and self.allow_llm,
            'application': self.allow_write and self.allow_config_write
                and self.allow_application_config and self.workspaces is None,
            'admin': self.allow_write and self.allow_config_write
                and self.allow_admin and self.workspaces is None,
        }
        if not permitted.get(effect, False):
            code = 'network_not_allowed' if effect == 'network' else 'requires_local_admin'
            raise AgentError(code, f'{effect} requires explicit local launch authorization')

    def permits(self, workspace: str) -> bool:
        """Check whether a workspace is within this launch's allowlist.

        Args:
            workspace: Workspace identifier to check.

        Returns:
            Whether this policy allows access to the workspace.
        """
        return self.workspaces is None or workspace in self.workspaces

    def import_path(self, value: str) -> Path:
        """Resolve and validate a path beneath an explicitly allowed import root.

        Args:
            value: User-supplied directory or ZIP path.

        Returns:
            The resolved import path.

        Raises:
            AgentError: If the path is outside the roots or is missing or a symlink.
        """
        path = Path(value).resolve()
        if not any(path.is_relative_to(Path(root).resolve()) for root in self.import_roots):
            raise AgentError("forbidden", "Import path is outside configured allowed roots")
        if not path.exists() or path.is_symlink():
            raise AgentError("invalid_path", "Import path must be an existing directory or ZIP")
        return path


class QueryOptions(BaseModel):
    """Bound query size, detail, traversal, and serialized response options."""
    model_config = ConfigDict(extra="forbid")
    detail_level: Literal["summary", "standard", "detailed"] = "summary"
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = Field(default=None, max_length=1024)
    max_depth: int = Field(default=15, ge=1, le=30)
    max_items: int = Field(default=2000, ge=1, le=20000)
    max_chars: int = Field(default=12000, ge=512, le=100000)
    collapse_temporary: bool | None = None


class AgentSettings(BaseModel):
    """Persisted controls for whether local agent access is enabled."""
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool = True
    allow_write: bool = True
    allow_source: bool = True
    default_detail: Literal["summary", "standard", "detailed"] = "summary"
    max_chars: int = Field(default=12000, ge=512, le=100000)
    audit_reads: bool = False

    @classmethod
    def from_store(cls, store: Any, workspace: str) -> AgentSettings:
        """Load the agent access settings for a workspace.

        Args:
            store: Workspace store providing persisted settings.
            workspace: Workspace identifier.

        Returns:
            Validated settings, using model defaults when no settings exist.
        """
        return cls.model_validate(store.setting(workspace, "agent_access", {}))

    @staticmethod
    def access_path(home: Path, workspace: str) -> Path:
        """Build the path to a workspace's credential-free access snapshot.

        Args:
            home: Runtime data home.
            workspace: Workspace identifier.

        Returns:
            The JSON snapshot path.

        Raises:
            AgentError: If the workspace identifier is malformed.
        """
        if not re.fullmatch(r"[a-f0-9]{32}", workspace):
            raise AgentError("not_found", "Workspace does not exist")
        return home / "agent" / "access" / (workspace + ".json")

    def save(self, store: Any, workspace: str) -> None:
        """Persist settings and publish the DB-free worker access snapshot.

        Args:
            store: Workspace store used for durable settings.
            workspace: Workspace identifier whose settings are saved.
        """
        # Also publish a credential-free revocation snapshot for DB-free job polling.
        path = self.access_path(store.home, workspace)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix("." + uuid.uuid4().hex + ".tmp")
        temporary.write_text(compact(self.model_dump()), encoding="utf-8")
        temporary.replace(path)
        store.set_setting(workspace, "agent_access", self.model_dump())


def job_settings(home: Path, workspace: str, record: dict[str, Any]) -> AgentSettings:
    """Load current workspace agent settings for a persisted job.

    Args:
        home: Runtime data home containing any access snapshot.
        workspace: Workspace identifier.
        record: Job record containing its launch-time access settings.

    Returns:
        Validated settings from the snapshot, or from the job record if absent.
    """
    path = AgentSettings.access_path(home, workspace)
    if path.exists():
        return AgentSettings.model_validate_json(path.read_text(encoding="utf-8"))
    return AgentSettings.model_validate(record.get("access", {}))
