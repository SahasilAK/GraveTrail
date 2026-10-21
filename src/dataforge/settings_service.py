"""Typed atomic workspace preferences with content revisions and non-escalation."""
import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from dataforge.agent.contracts import AccessPolicy, AgentError, AgentSettings, compact
from dataforge.configuration import (
    AnalysisPreferences,
    LLMResourceSettings,
    ParsingSettings,
    VisualizationSettings,
)
from dataforge.model_capabilities import execution_profile
from dataforge.store import Store


class Resources(LLMResourceSettings):
    max_file_mb: int = Field(default=20, ge=1, le=100)
    max_files: int = Field(default=10000, ge=1, le=100000)
    parse_workers: int = Field(default=1, ge=1, le=8)


class Visualization(VisualizationSettings):
    graph_limit: int = Field(default=150, ge=10, le=1000)
    traversal_depth: int = Field(default=5, ge=1, le=30)
    tree_expansion_depth: int = Field(default=1, ge=0, le=30)


class Privacy(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    external_llm: bool = False
    allow_full_source: bool = False
    max_context_chars: int = Field(default=8000, ge=500, le=100000)
    redact_secrets: bool = True
    llm_history: bool = False
    llm_retention_days: int = Field(default=30, ge=1, le=3650)


class TemporaryPreferences(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    enabled: bool = False


SECTIONS = {'parsing': ParsingSettings, 'analysis': AnalysisPreferences, 'resources': Resources,
            'visualization': Visualization, 'privacy': Privacy, 'agent_access': AgentSettings,
            'temporary_cleanup': TemporaryPreferences}
LOCAL_ADMIN = AccessPolicy(allow_write=True, allow_config_write=True, allow_admin=True)


def revision(store: Store, workspace: str) -> str:
    """Hash the ordered workspace settings, identity, and provider profiles."""
    payload = store.rows('SELECT key,value FROM settings WHERE workspace_id=? ORDER BY key', [workspace])
    payload += store.rows('SELECT name,description FROM workspaces WHERE workspace_id=?', [workspace])
    profiles = store.rows('SELECT profile_id,config FROM llm_profiles WHERE workspace_id=? ORDER BY profile_id', [workspace])
    payload += [{**p, 'config': execution_profile(json.loads(p['config']))} for p in profiles]
    return hashlib.sha256(compact(payload).encode()).hexdigest()


def check_revision(store: Store, workspace: str, expected: str) -> None:
    """Reject a settings update when its expected content revision is stale.

    Raises:
        AgentError: If the operation is invalid, unauthorized, or unavailable."""
    if not expected or expected != revision(store, workspace):
        raise AgentError('conflict', 'Configuration changed; read current settings and retry')


def settings_schema(section: str | None=None) -> dict[str, Any]:
    """Describe all supported settings sections or one section's schema and defaults.

    Raises:
        AgentError: If the operation is invalid, unauthorized, or unavailable."""
    if section is None:
        return {'schema_version': 1, 'sections': list(SECTIONS), 'scope': 'workspace', 'llm_process_cap': 8}
    if section not in SECTIONS:
        raise AgentError('validation_failed', 'Unknown settings section')
    return {'schema_version': 1, 'section': section, 'schema': SECTIONS[section].model_json_schema(),
            'defaults': SECTIONS[section]().model_dump(), 'scope': 'workspace', 'llm_process_cap': 8}


def read_settings(store: Store, workspace: str, section: str) -> dict[str, Any]:
    """Read a workspace settings section with validated values and its current revision.

    Raises:
        AgentError: If the operation is invalid, unauthorized, or unavailable."""
    if section not in SECTIONS:
        raise AgentError('validation_failed', 'Unknown settings section')
    model = SECTIONS[section]
    if section == 'agent_access':
        values = AgentSettings.from_store(store, workspace).model_dump()
    elif section == 'temporary_cleanup':
        values = {'enabled': store.setting(workspace, 'auto_cleanup_temporary', False)}
    else:
        values = {key: store.setting(workspace, key, value) for key, value in model().model_dump().items()}
    return {'schema_version': 1, 'section': section, 'scope': 'workspace',
            'values': model.model_validate(values, strict=True).model_dump(),
            'defaults': model().model_dump(), 'settings_revision': revision(store, workspace)}


def update_settings(store: Store, policy: AccessPolicy, workspace: str, section: str, values: dict[str, Any], expected_revision: str) -> dict[str, Any]:
    """Validate and atomically persist settings after enforcing revision and access checks.

    Args:
        store: Workspace store used for reads and the transactional update.
        policy: Access policy authorizing configuration and any privilege widening.
        workspace: Workspace identifier.
        section: Settings section to update.
        values: Partial values merged with the current section.
        expected_revision: Revision previously read by the caller.

    Returns:
        Changed fields, the new revision, and parsing/reload impact metadata.

    Raises:
        AgentError: If authorization, revision, section, or value validation fails."""
    policy.require('config')
    with store.lock:
        check_revision(store, workspace, expected_revision)
        before = read_settings(store, workspace, section)['values']
        after = SECTIONS[section].model_validate({**before, **values}, strict=True).model_dump()
        widening = False
        if section == 'privacy':
            widening = any(not before[k] and after[k] for k in ('external_llm', 'allow_full_source', 'llm_history'))
            widening |= before['redact_secrets'] and not after['redact_secrets']
            widening |= any(after[k] > before[k] for k in ('max_context_chars', 'llm_retention_days'))
        if section == 'agent_access':
            widening = any(not before[k] and after[k] for k in ('enabled', 'allow_write', 'allow_source'))
            widening |= before['audit_reads'] and not after['audit_reads']
            widening |= after['max_chars'] > before['max_chars']
            levels = ['summary', 'standard', 'detailed']
            widening |= levels.index(after['default_detail']) > levels.index(before['default_detail'])
        if section == 'temporary_cleanup':
            widening = after['enabled'] and not before['enabled']
        if widening:
            policy.require('admin')
        changed = sorted(k for k in before if before[k] != after[k])
        with store.transaction():
            if section == 'agent_access':
                AgentSettings.model_validate(after).save(store, workspace)
            elif section == 'temporary_cleanup':
                store.set_setting(workspace, 'auto_cleanup_temporary', after['enabled'])
            else:
                for key in changed:
                    store.set_setting(workspace, key, after[key])
        return {'changed_fields': changed, 'settings_revision': revision(store, workspace),
                'analysis_required': bool(changed) and section == 'parsing', 'reload_required': False,
                'warnings': ['Analyze to apply parsing changes; existing facts retained'] if changed and section == 'parsing' else []}


def save_ui_settings(store: Store, workspace: str, section: str, values: dict[str, Any]) -> dict[str, Any]:
    """Save local UI preferences through the same validation and atomic update path."""
    return update_settings(store, LOCAL_ADMIN, workspace, section, values, revision(store, workspace))


def read_json_file(path: Path) -> dict[str, Any]:
    """Read a bounded regular UTF-8 JSON file and require a top-level object.

    Raises:
        AgentError: If the operation is invalid, unauthorized, or unavailable."""
    if path.is_symlink() or path.stat().st_size > 1024 * 1024:
        raise AgentError('validation_failed', 'Expected a regular UTF-8 JSON file at most 1 MB')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, RecursionError):
        raise AgentError('validation_failed', 'Expected bounded valid UTF-8 JSON') from None
    if not isinstance(data, dict):
        raise AgentError('validation_failed', 'Expected a JSON object')
    return data
