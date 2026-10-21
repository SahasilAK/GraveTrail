"""Shared deterministic automation use cases over the existing application services."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections import Counter
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import asdict
from typing import Any

from pydantic import ValidationError

from dataforge.agent.contracts import (
    AccessPolicy,
    AgentError,
    AgentSettings,
    QueryOptions,
    compact,
    job_settings,
)
from dataforge.agent.jobs import Jobs, status_result
from dataforge.agent.paging import page
from dataforge.ai_service import READS as AI_READS
from dataforge.ai_service import WRITES as AI_WRITES
from dataforge.ai_service import AIOperations
from dataforge.artifacts import READS as ARTIFACT_READS
from dataforge.artifacts import WRITES as ARTIFACT_WRITES
from dataforge.artifacts import ArtifactOperations
from dataforge.asset_identity import asset_label
from dataforge.graph import LineageGraph
from dataforge.ingestion import Importer, Limits
from dataforge.models import canonical
from dataforge.provider_service import READS as PROVIDER_READS
from dataforge.provider_service import WRITES as PROVIDER_WRITES
from dataforge.provider_service import ProviderOperations
from dataforge.reporting import READS as REPORT_READS
from dataforge.reporting import ReportOperations

WRITES = {"create_workspace", "ingest", "analyze", "export", "cleanup_apply",
          'settings_update', 'workspace_update', 'config_import', 'history_archive', 'history_restore',
          'staging_clean', 'staging_restore'} | PROVIDER_WRITES | AI_WRITES | ARTIFACT_WRITES
MAINTENANCE_READS = {'history_preview', 'history_archives', 'staging_preview', 'staging_recoveries',
                     'database_inspect', 'backups_list'}
APPLICATION_ACTIONS = {'theme_list', 'theme_get', 'theme_apply', 'logging_get', 'logging_update', 'runtime_info'}
WRITES |= {'theme_apply', 'logging_update'}
LONG_ACTIONS = {'provider_models', 'provider_test', 'ai_request', 'review_request', 'ai_merge'}


class AgentService(ProviderOperations, AIOperations, ReportOperations, ArtifactOperations):
    """Coordinate authorized automation requests over application services."""
    def __init__(self, store: Any, policy: AccessPolicy | None = None) -> None:
        """Initialize service state, background jobs, and runtime configuration.

        Args:
            store: Workspace store providing persisted data.
            policy: Launch access policy."""
        self.store, self.policy = store, policy or AccessPolicy()
        self.jobs = Jobs(store.home)
        self.runtime_connections = {}
        self.runtime_profiles = {}
        self.provider_transport = None
        import os
        from pathlib import Path

        from dataforge.launcher import application_root
        self.theme_config_path = Path(os.environ.get('DATAFORGE_THEME_CONFIG', str(application_root() / '.streamlit/config.toml')))
        self.configured_storage = os.environ.get('DATAFORGE_STORAGE_LOCATIONS', '')

    def close(self) -> None:
        """Clear runtime connection state and shut down the job executor."""
        for manager in self.runtime_connections.values():
            manager.clear()
        self.runtime_connections.clear()
        self.runtime_profiles.clear()
        self.jobs.close()

    def _workspace(self, workspace: str, write: bool=False, source: bool=False, administrator: bool=False) -> AgentSettings:
        """Validate workspace access and return its agent settings.

        Args:
            workspace: Workspace identifier.
            write: Whether write permission is required.
            source: Whether source permission is required.
            administrator: Whether local administrator permission is required.

        Returns:
        Validated workspace agent settings.
        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        if not self.policy.permits(workspace):
            raise AgentError("forbidden", "Workspace access is not authorized")
        matches = self.store.rows("SELECT workspace_id,name FROM workspaces WHERE workspace_id=?", [workspace])
        if not matches:
            raise AgentError("not_found", "Workspace does not exist; use its exact workspace_id")
        settings = AgentSettings.from_store(self.store, workspace)
        if not administrator and (not settings.enabled or (write and (not self.policy.allow_write or not settings.allow_write))):
            raise AgentError("forbidden", "Agent access or mutation is disabled for this launch/workspace")
        if source and not settings.allow_source:
            raise AgentError("forbidden", "Source retrieval is disabled for this workspace")
        return settings

    def audit(self, workspace: str, action: str, outcome: str) -> None:
        """Append a sanitized operation outcome to the local audit log.

        Args:
            workspace: Workspace identifier.
            action: Operation name.
            outcome: Sanitized outcome or error code."""
        directory = self.store.home / "agent"
        directory.mkdir(exist_ok=True)
        path = directory / "audit.jsonl"
        if path.exists() and path.stat().st_size > 1024 * 1024:
            path.replace(directory / "audit.previous.jsonl")
        with path.open("a", encoding="utf-8") as stream:
            stream.write(compact({"at": time.time(), "workspace_id": workspace,
                                  "action": action, "outcome": outcome}) + "\n")

    def call(self, action: str, workspace_id: str = "", options: dict[str, Any] | None=None, **arguments: Any) -> dict[str, Any]:
        """Validate, authorize, and dispatch one transport-neutral agent operation.

        Args:
            action: Registered operation name.
            workspace_id: Workspace targeted by the operation, if any.
            options: Optional query options supplied by the transport adapter.
            **arguments: Operation-specific arguments.

        Returns:
            The operation's JSON-compatible response.

        Raises:
            AgentError: If the request is unknown, invalid, or unauthorized.
        """
        if action not in {"workspaces", "create_workspace", "summary", "assets", "files", "issues",
                          "lineage", "impact", "batch", "columns", "column_catalog", "column_lineage", "source", "search_code",
                          "ingest", "analyze", "job", "export", "result",
                          "cleanup_inspect", "cleanup_preview", "cleanup_apply", "capabilities",
                          'settings_schema', 'settings_get', 'settings_update', 'workspace_update',
                          'config_export', 'config_import', 'agent_setup', 'agent_self_test'} | APPLICATION_ACTIONS | WRITES | MAINTENANCE_READS | PROVIDER_READS | AI_READS | REPORT_READS | ARTIFACT_READS:
            raise AgentError("invalid_argument", "Unknown operation")
        write = action in WRITES
        try:
            if action == "job":
                return self.job_status(workspace_id, arguments["job_id"], options)
            if action == 'agent_self_test':
                settings = self._workspace(workspace_id)
                values = {**(options or {})}
                values['max_chars'] = min(values.get('max_chars', settings.max_chars), settings.max_chars)
                opts = QueryOptions.model_validate(values)
                result = self._agent_self_test(workspace_id, opts, **arguments)
                if len(compact(result)) > opts.max_chars:
                    raise AgentError('budget_too_small', 'Local handler result exceeds response budget')
                if settings.audit_reads:
                    self.audit(workspace_id, action, 'accepted')
                return result
            with nullcontext() if action in LONG_ACTIONS else self.store.lock:
                if action in {"workspaces", "create_workspace", 'config_import', 'database_inspect', 'backups_list'} or action in APPLICATION_ACTIONS or (action == 'capabilities' and not workspace_id):
                    settings = AgentSettings()
                    if action == 'runtime_info' and workspace_id:
                        settings = self._workspace(workspace_id)
                    if write and (not self.policy.allow_write or self.policy.workspaces is not None):
                        raise AgentError("forbidden", "Workspace creation requires unrestricted explicit write access")
                else:
                    administrator = self.policy.allow_admin and action in {'settings_get', 'settings_schema', 'settings_update'}
                    if administrator:
                        self.policy.require('admin')
                    settings = self._workspace(workspace_id, write=write,
                        source=action in {"source", "result"} or (options or {}).get("detail_level") == "detailed",
                        administrator=administrator)
                values = {"detail_level": settings.default_detail, **(options or {})}
                values["max_chars"] = min(values.get("max_chars", settings.max_chars), settings.max_chars)
                opts = QueryOptions.model_validate(values)
                if opts.detail_level == "detailed" and not settings.allow_source:
                    raise AgentError("forbidden", "Detailed source retrieval is disabled")
                result = getattr(self, "_" + action)(workspace_id, opts, **arguments)
                result = json.loads(compact(result))
                if len(compact(result)) > opts.max_chars:
                    raise AgentError("budget_too_small", "Response exceeds max_chars; narrow the request or increase the budget")
                if write or settings.audit_reads:
                    self.audit(workspace_id, action, "accepted")
                return result
        except AgentError as exc:
            if write:
                self.audit(workspace_id, action, exc.code)
            raise
        except (ValueError, TypeError, ValidationError) as exc:
            raise AgentError("invalid_argument", "Invalid request arguments", reason=type(exc).__name__) from None
        except OSError:
            raise AgentError("io_error", "Local file operation failed; check access and available storage") from None

    def _theme_list(self, w: str, opts: QueryOptions) -> dict[str, Any]:
        """List available theme presets and their base themes.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.

        Returns:
            The operation response data for the requested use case."""
        from dataforge.theme_configuration import PRESETS
        return self._page('', opts, 'themes', [{'name': name, 'base': p['base']} for name, p in PRESETS.items()])

    def _theme_get(self, w: str, opts: QueryOptions) -> dict[str, Any]:
        """Read configured theme state and report that loaded UI state is unavailable.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.

        Returns:
            A public-safe summary of the asset.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        from dataforge.theme_configuration import current_preset
        if w or self.policy.workspaces is not None:
            raise AgentError('requires_local_admin', 'Application theme requires unrestricted launch without a workspace argument')
        configured = current_preset(self.theme_config_path) if self.theme_config_path.is_file() else None
        return {'configured': configured, 'detected': configured, 'loaded': None,
                'reload_required': True, 'note': 'Loaded UI appearance is unavailable to a separate CLI/MCP process'}

    def _theme_apply(self, w: str, opts: QueryOptions, name: str) -> dict[str, Any]:
        """Apply a theme preset under application-scope authorization.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            name: Workspace or preset name.

        Returns:
            The operation response data for the requested use case.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        from dataforge.theme_configuration import apply_preset
        self.policy.require('application')
        if w:
            raise AgentError('validation_failed', 'Application operations do not accept workspace IDs')
        apply_preset(self.theme_config_path, name)
        return self._theme_get(w, opts)

    def _logging_get(self, w: str, opts: QueryOptions) -> dict[str, Any]:
        """Read the persisted application log level.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.

        Returns:
            The operation response data for the requested use case.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        if w or self.policy.workspaces is not None:
            raise AgentError('requires_local_admin', 'Application logging requires unrestricted launch without a workspace argument')
        return {'level': self.store.setting('__application__', 'log_level', 'INFO'), 'scope': 'application'}

    def _logging_update(self, w: str, opts: QueryOptions, level: str) -> dict[str, Any]:
        """Persist an application log-level change and report reload requirements.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            level: Application logging level.

        Returns:
            The operation response data for the requested use case."""
        from dataforge.logging_config import save_application_logging
        self.policy.require('application')
        self._logging_get(w, opts)
        save_application_logging(self.store, level)
        return {**self._logging_get(w, opts), 'reload_required': True}

    def _runtime_info(self, w: str, opts: QueryOptions) -> dict[str, Any]:
        """Report runtime ownership and authorized storage-home information.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.

        Returns:
            The operation response data for the requested use case."""
        from dataforge.storage_locations import allowed_homes
        result = {'ownership': 'One DuckDB owning process per home', 'live_switch': False,
                  'switch': 'Relaunch CLI/MCP with an authorized --home; UI changes only its browser session'}
        if self.policy.workspaces is None:
            result.update(home=str(self.store.home), allowed_homes=allowed_homes(self.store.home, self.configured_storage))
        return result

    def _agent_setup(self, w: str, opts: QueryOptions, client: str='codex', transport: str='stdio', tool_name: str='') -> dict[str, Any]:
        """Build client configuration and available MCP tool schemas.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            client: Client configuration target.
            transport: MCP transport selection.
            tool_name: Optional tool whose schema is requested.

        Returns:
            The operation response data for the requested use case.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        import asyncio
        import sys

        from dataforge.agent.mcp_server import create_server
        if client not in {'codex', 'claude'} or transport not in {'stdio', 'streamable-http'}:
            raise AgentError('validation_failed', 'Use codex/claude and stdio/streamable-http')
        tools = asyncio.run(create_server(self).list_tools())
        args = [] if getattr(sys, 'frozen', False) else ['-m', 'dataforge.cli']
        args += ['--home', str(self.store.home), '--allowed-workspace', w, 'mcp']
        stdio = {'command': sys.executable, 'args': args}
        result = {'stdio': stdio, 'client': client, 'transport': transport,
                  'codex_toml': '[mcp_servers.gravetrail]\ncommand = ' + json.dumps(sys.executable) + '\nargs = ' + json.dumps(args),
                  'claude': {'mcpServers': {'gravetrail': stdio}},
                  'http': {'url': 'http://127.0.0.1:8765/mcp', 'bearer_reference': 'DATAFORGE_MCP_TOKEN',
                           'authentication': 'pre-provisioned bearer; external TLS reverse proxy required'},
                  'tools': [t.name for t in tools], 'ownership': 'Stop any other owner before launching an external client'}
        if tool_name:
            matches = [t for t in tools if t.name == tool_name]
            if not matches:
                raise AgentError('not_found', 'Unknown tool schema')
            result = {'tool': matches[0].model_dump(mode='json')}
        return result

    def _agent_self_test(self, w: str, opts: QueryOptions) -> dict[str, Any]:
        """Check a local MCP handler in process without opening a client transport.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.

        Returns:
            The operation response data for the requested use case.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        import asyncio

        from dataforge.agent.mcp_server import create_server
        result = asyncio.run(create_server(self).call_tool('get_workspace_summary', {'workspace_id': w}))
        if result.isError:
            raise AgentError(result.structuredContent['error']['code'], 'Local MCP handler check failed')
        return {'passed': True, 'method': 'in_process_mcp_handler', 'summary': result.structuredContent,
                'note': 'External stdio/HTTP connectivity is a separate client test'}

    def _capabilities(self, w: str, opts: QueryOptions) -> dict[str, Any]:
        """List agent capabilities with policy-specific authorization state.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.

        Returns:
            The operation response data for the requested use case."""
        from dataforge.agent.capabilities import capability_catalog
        from dataforge.graph_images import png_available
        return self._page(w, opts, 'capabilities', capability_catalog(self, w), schema_version=1,
            graph_image_formats=['svg', 'png'] if png_available() else ['svg'])

    def _settings_schema(self, w: str, opts: QueryOptions, section: str | None=None) -> dict[str, Any]:
        """Return the editable workspace settings schema.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            section: Settings section.

        Returns:
            The operation response data for the requested use case."""
        from dataforge.settings_service import settings_schema
        return settings_schema(section)

    def _settings_get(self, w: str, opts: QueryOptions, section: str) -> dict[str, Any]:
        """Read one workspace settings section.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            section: Settings section.

        Returns:
            The operation response data for the requested use case."""
        from dataforge.settings_service import read_settings
        return read_settings(self.store, w, section)

    def _settings_update(self, w: str, opts: QueryOptions, section: str, values: dict[str, Any], expected_revision: str) -> dict[str, Any]:
        """Update a settings section using the caller’s expected revision.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            section: Settings section.
            values: Settings values to apply.
            expected_revision: Revision expected by the caller.

        Returns:
            The operation response data for the requested use case."""
        from dataforge.settings_service import update_settings
        return update_settings(self.store, self.policy, w, section, values, expected_revision)

    def _workspace_update(self, w: str, opts: QueryOptions, name: str, description: str, expected_revision: str) -> dict[str, Any]:
        """Rename the workspace and update its description after revision validation.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            name: Workspace or preset name.
            description: Workspace description.
            expected_revision: Revision expected by the caller.

        Returns:
            The operation response data for the requested use case."""
        from dataforge.settings_service import check_revision, revision
        self.policy.require('config')
        check_revision(self.store, w, expected_revision)
        self.store.update_workspace(w, name, description)
        return {'workspace_id': w, 'settings_revision': revision(self.store, w)}

    def _config_export(self, w: str, opts: QueryOptions) -> dict[str, Any]:
        """Export workspace configuration in JSON-compatible form.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.

        Returns:
            The operation response data for the requested use case."""
        from dataforge.configuration import export_workspace_configuration
        return {'configuration': json.loads(export_workspace_configuration(self.store, w))}

    def _config_import(self, w: str, opts: QueryOptions, configuration: dict[str, Any]) -> dict[str, Any]:
        """Create a workspace from allowed configuration under config-write policy.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            configuration: Configuration data to import.

        Returns:
            The operation response data for the requested use case.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        from dataforge.configuration import import_workspace_configuration
        self.policy.require('config')
        if self.policy.workspaces is not None:
            raise AgentError('forbidden', 'Configuration import creates a new workspace; unrestricted launch required')
        return {'workspace_id': import_workspace_configuration(self.store, compact(configuration))}

    def _revision(self, w: str) -> list[list[dict[str, Any]]]:
        """Collect source hashes and the latest completed run for query cursor identity.

        Args:
            w: Workspace identifier.

        Returns:
            Source-file hashes and the latest completed run.
        """
        files = self.store.rows("SELECT file_id,content_hash,parsing_status FROM source_files WHERE workspace_id=? ORDER BY file_id", [w])
        runs = self.store.rows("SELECT run_id FROM analysis_runs WHERE workspace_id=? AND status='completed' ORDER BY created_at DESC LIMIT 1", [w])
        return [files, runs]

    def _cleanup_inspect(self, w: str, opts: QueryOptions) -> dict[str, Any]:
        """Summarize cleanup record counts and storage estimates by category.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.

        Returns:
            The operation response data for the requested use case."""
        from dataforge.cleanup import cleanup_plan
        plans = {category: cleanup_plan(self.store, w, category) for category in
                 ('sources', 'lineage', 'columns', 'ai', 'history', 'jobs', 'reset', 'workspace')}
        return {'workspace_id': w, 'categories': {key: {'records': p['records'],
                'logical_bytes_estimate': p['logical_bytes_estimate'], 'file_bytes': p['file_bytes']}
                for key, p in plans.items()}, 'notes': next(iter(plans.values()))['notes'],
                'restricted_categories': {'cache': 'requires_local_ui', 'orphans': 'requires_local_ui',
                                          'application': 'requires_local_ui'}}

    def _cleanup_preview(self, w: str, opts: QueryOptions, category: str='lineage', file_ids: list[str] | None=None, run_id: str | None=None) -> dict[str, Any]:
        """Build a cleanup preview for workspace or authorized application data.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            category: Cleanup category.
            file_ids: Optional source file identifiers.
            run_id: Optional analysis run identifier.

        Returns:
            The operation response data for the requested use case.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        from dataforge.cleanup import cleanup_plan
        if category in {'application', 'cache', 'orphans'}:
            if self.policy.workspaces is not None or not self.policy.allow_application_config:
                raise AgentError('requires_local_ui', 'Shared cleanup inspection requires an unrestricted application-authorized launch; apply in Settings UI')
            plan = cleanup_plan(self.store, '', category)
            return {'category': category, 'records': plan['records'], 'logical_bytes_estimate': plan['logical_bytes_estimate'],
                    'file_bytes': plan['file_bytes'], 'restriction': 'requires_local_ui', 'notes': plan['notes']}
        return cleanup_plan(self.store, w, category, file_ids, run_id)

    def _cleanup_apply(self, w: str, opts: QueryOptions, preview: dict[str, Any], confirmation: str='', backup_first: bool=False) -> dict[str, Any]:
        """Apply a cleanup preview only after backup and permission checks.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            preview: Previously generated maintenance preview.
            confirmation: Exact confirmation text.
            backup_first: Whether to create a full-home backup first.

        Returns:
            The operation response data for the requested use case.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        from dataforge.cleanup import apply_cleanup
        if backup_first and self.policy.workspaces is not None:
            raise AgentError('forbidden', 'Whole-home backup requires unrestricted local access')
        if preview.get('workspace_id') != w or preview.get('category') in {'application', 'cache', 'orphans'}:
            raise AgentError('forbidden', 'Cleanup preview is outside the permitted workspace')
        if not backup_first:
            raise AgentError('validation_failed', 'General cleanup requires a full-home backup; pass the explicit backup option')
        return apply_cleanup(self.store, preview, confirmation, backup_first)

    def _history_preview(self, w: str, opts: QueryOptions, keep_runs: int=20, keep_imports: int=20, batch_size: int=25) -> dict[str, Any]:
        """Preview history retention and derive a token for the current plan.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            keep_runs: Number of analysis runs to retain.
            keep_imports: Number of ingestion reports to retain.
            batch_size: Records handled per maintenance batch.

        Returns:
            The operation response data for the requested use case."""
        from dataforge.cleanup import checked_path
        from dataforge.maintenance import history_plan
        checked_path(self.store.home, 'history-recovery/' + w)
        plan = {'workspace_id': w, 'keep_runs': keep_runs, 'keep_imports': keep_imports, 'batch_size': batch_size,
                **history_plan(self.store, w, keep_runs, keep_imports, batch_size)}
        plan['token'] = hashlib.sha256(compact(plan).encode()).hexdigest()
        return plan

    def _maintenance_confirmation(self, w: str, confirmation: str) -> None:
        """Validate the exact workspace name and unrestricted local launch.

        Args:
            w: Workspace identifier.
            confirmation: Exact confirmation text.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        name = self.store.rows('SELECT name FROM workspaces WHERE workspace_id=?', [w])[0]['name']
        if name != confirmation:
            raise AgentError('validation_failed', 'Type the exact current workspace name to confirm local maintenance')
        if self.policy.workspaces is not None:
            raise AgentError('forbidden', 'Recoverable full-home backup requires an unrestricted local launch')

    def _history_archive(self, w: str, opts: QueryOptions, preview: dict[str, Any], confirmation: str) -> dict[str, Any]:
        """Archive eligible history after refreshing the preview and making a backup.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            preview: Previously generated maintenance preview.
            confirmation: Exact confirmation text.

        Returns:
            The operation response data for the requested use case.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        from dataforge.database_maintenance import backup
        from dataforge.maintenance import archive_history
        self._maintenance_confirmation(w, confirmation)
        current = self._history_preview(w, opts, preview['keep_runs'], preview['keep_imports'], preview['batch_size'])
        if current != preview:
            raise AgentError('conflict', 'History eligibility changed; refresh preview')
        backup_id = backup(self.store).stem
        result = archive_history(self.store, w, preview['keep_runs'], preview['keep_imports'], preview['batch_size'])
        return {**result, 'backup_id': backup_id}

    def _history_archives(self, w: str, opts: QueryOptions) -> dict[str, Any]:
        """List recoverable history archives for the workspace.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.

        Returns:
            The operation response data for the requested use case."""
        from dataforge.cleanup import checked_path
        from dataforge.maintenance import list_archives
        checked_path(self.store.home, 'history-recovery/' + w)
        return self._page(w, opts, 'history_archives', list_archives(self.store, w))

    def _history_restore(self, w: str, opts: QueryOptions, archive_id: str, confirmation: str) -> dict[str, Any]:
        """Restore a selected history archive after local confirmation.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            archive_id: History archive identifier.
            confirmation: Exact confirmation text.

        Returns:
            The operation response data for the requested use case."""
        from dataforge.cleanup import checked_path
        from dataforge.maintenance import restore_history
        self._maintenance_confirmation(w, confirmation)
        checked_path(self.store.home, 'history-recovery/' + w)
        return restore_history(self.store, w, archive_id)

    def _staging_preview(self, w: str, opts: QueryOptions, age_hours: int=24) -> dict[str, Any]:
        """Preview stale temporary files and derive a plan token.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            age_hours: Minimum age in hours for staging candidates.

        Returns:
            The operation response data for the requested use case."""
        from dataforge.temporary_cleanup import temporary_plan
        plan = {'workspace_id': w, 'age_hours': age_hours, **temporary_plan(self.store, w, age_hours)}
        plan['token'] = hashlib.sha256(compact(plan).encode()).hexdigest()
        return plan

    def _staging_clean(self, w: str, opts: QueryOptions, preview: dict[str, Any], confirmation: str, names: list[str] | None=None) -> dict[str, Any]:
        """Clean selected temporary files after preview validation and backup.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            preview: Previously generated maintenance preview.
            confirmation: Exact confirmation text.
            names: Optional selected staging file names.

        Returns:
            The operation response data for the requested use case.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        from dataforge.database_maintenance import backup
        from dataforge.temporary_cleanup import cleanup_temporary
        self._maintenance_confirmation(w, confirmation)
        current = self._staging_preview(w, opts, preview['age_hours'])
        if current != preview:
            raise AgentError('conflict', 'Staging identities changed; refresh preview')
        selected = [f for f in current['files'] if names is None or f['name'] in names]
        if not selected or (names is not None and set(names) - {f['name'] for f in selected}):
            raise AgentError('validation_failed', 'Select files from the fresh staging preview')
        backup_id = backup(self.store).stem
        return {**cleanup_temporary(self.store, w, selected, current['age_hours']), 'backup_id': backup_id}

    def _staging_recoveries(self, w: str, opts: QueryOptions) -> dict[str, Any]:
        """List recoverable temporary-file cleanup records.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.

        Returns:
            The operation response data for the requested use case."""
        from dataforge.temporary_cleanup import temporary_recoveries
        return self._page(w, opts, 'staging_recoveries', temporary_recoveries(self.store, w))

    def _staging_restore(self, w: str, opts: QueryOptions, recovery_id: str, confirmation: str) -> dict[str, Any]:
        """Restore temporary files from a recovery record after confirmation.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            recovery_id: Staging recovery identifier.
            confirmation: Exact confirmation text.

        Returns:
            The operation response data for the requested use case."""
        from dataforge.temporary_cleanup import restore_temporary
        self._maintenance_confirmation(w, confirmation)
        return restore_temporary(self.store, w, recovery_id)

    def _global_metadata(self, w: str) -> None:
        """Require unrestricted application permission for whole-home metadata.

        Args:
            w: Workspace identifier.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        if w or self.policy.workspaces is not None or not self.policy.allow_application_config:
            raise AgentError('requires_local_admin', 'Whole-home metadata requires unrestricted --allow-application-config; no workspace argument')

    def _database_inspect(self, w: str, opts: QueryOptions) -> dict[str, Any]:
        """Inspect database health and storage metadata.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.

        Returns:
            The operation response data for the requested use case."""
        from dataforge.database_maintenance import inspect_database
        self._global_metadata(w)
        return inspect_database(self.store)

    def _backups_list(self, w: str, opts: QueryOptions) -> dict[str, Any]:
        """List bounded local backup metadata for authorized application scope.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.

        Returns:
            The operation response data for the requested use case."""
        import re

        from dataforge.cleanup import checked_path
        self._global_metadata(w)
        directory = checked_path(self.store.home, 'backups')
        files = sorted(directory.glob('*.zip')) if directory.exists() else []
        items = []
        for path in files[:1001]:
            if re.fullmatch('[a-f0-9]{32}', path.stem):
                path = checked_path(self.store.home, path.relative_to(self.store.home))
                items.append({'backup_id': path.stem, 'bytes': path.stat().st_size, 'download': 'local CLI/UI only'})
        return self._page(w, opts, 'backups', items[:1000], boundaries=['backup_limit'] if len(files) > 1000 else [])

    def _current(self, w: str) -> bool:
        """Check whether stored analysis matches current source state.

        Args:
            w: Workspace identifier.

        Returns:
            Whether stored analysis is current for the workspace.
        """
        from dataforge.services import analysis_is_current
        return analysis_is_current(self.store, w)

    def _page(self, w: str, opts: QueryOptions, action: str, items: list[dict[str, Any]],
              **metadata: Any) -> dict[str, Any]:
        """Build a page whose cursor is bound to its query and data revision.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            action: Operation name.
            items: Records to page.
            metadata: Additional response fields.

        Returns:
            A bounded response page with workspace and continuation metadata.
        """
        key = [w, action, self._revision(w), opts.model_dump(exclude={"cursor", "limit", "max_chars"}),
               hashlib.sha256(compact(items).encode()).hexdigest()]
        return page(items, opts, key, workspace_id=w, **metadata)

    def _workspaces(self, w: str, opts: QueryOptions, query: str="") -> dict[str, Any]:
        """List enabled workspaces visible to this policy, optionally filtered by name.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            query: Literal search text.

        Returns:
            The operation response data for the requested use case."""
        items = [{k: row[k] for k in ("workspace_id", "name", "description")}
                 for row in self.store.workspaces() if self.policy.permits(row["workspace_id"])
                 and AgentSettings.from_store(self.store, row["workspace_id"]).enabled
                 and query.casefold() in row["name"].casefold()]
        return self._page(w, opts, ["workspaces", query], items)

    def _create_workspace(self, w: str, opts: QueryOptions, name: str, description: str="") -> dict[str, Any]:
        """Create a workspace and return its stable identifier and name.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            name: Workspace or preset name.
            description: Workspace description.

        Returns:
            The operation response data for the requested use case."""
        return {"workspace_id": self.store.create_workspace(name, description), "name": name}

    def _summary(self, w: str, opts: QueryOptions) -> dict[str, Any]:
        """Return workspace record counts and analysis freshness.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.

        Returns:
            The operation response data for the requested use case."""
        counts = {}
        for table in ("source_files", "assets", "edges", "diagnostics"):
            counts[table] = self.store.rows(f"SELECT count(*) AS n FROM {table} WHERE workspace_id=?", [w])[0]["n"]
        return {"workspace_id": w, **counts, "analysis_current": self._current(w)}

    def _asset(self, w: str, value: str) -> dict[str, Any]:
        """Resolve an asset identifier or name and reject ambiguous matches.

        Args:
            w: Workspace identifier.
            value: Asset ID or name.

        Returns:
        The matching asset record.
        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        if not value or len(value) > 1024:
            raise AgentError("invalid_argument", "Specify an asset ID or table name up to 1024 characters")
        assets = self.store.assets(w)
        exact_id = [a for a in assets if a["asset_id"] == value]
        if exact_id:
            return exact_id[0]
        sensitive = self.store.setting(w, "case_sensitive", False)
        normalize = (lambda x: x.strip().strip('"`[]')) if sensitive else canonical
        name = normalize(value)
        matches = [a for a in assets if normalize(a["name"]) == name]
        if not matches:
            matches = [a for a in assets if normalize(a["name"].split(".")[-1]) == name]
        if len(matches) > 1:
            raise AgentError("ambiguous_asset", "Asset name is ambiguous; use an asset_id",
                             candidates=[self._asset_summary(a) for a in matches[:20]],
                             candidate_count=len(matches))
        if not matches:
            raise AgentError("not_found", "Asset does not exist in this workspace")
        return matches[0]

    @staticmethod
    def _asset_summary(a: dict[str, Any]) -> dict[str, Any]:
        """Select the public summary fields for an asset.

        Args:
            a: Asset record.

        Returns:
            A public-safe summary of the asset.
        """
        return {"asset_id": a["asset_id"], "name": asset_label(a), "kind": a["kind"],
                "temporary": a["temporary"]}

    def _assets(self, w: str, opts: QueryOptions, query: str="") -> dict[str, Any]:
        """Search asset summaries by name.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            query: Literal search text.

        Returns:
            The operation response data for the requested use case.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        if len(query) > 1024:
            raise AgentError("invalid_argument", "Search query is too long")
        items = [self._asset_summary(a) for a in self.store.assets(w) if query.casefold() in a["name"].casefold()]
        return self._page(w, opts, ["assets", query], items, analysis_current=self._current(w))

    def _files(self, w: str, opts: QueryOptions, query: str="") -> dict[str, Any]:
        """Search source-file inventory metadata by relative path.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            query: Literal search text.

        Returns:
            The operation response data for the requested use case."""
        fields = ("file_id", "relative_path", "extension", "parsing_status", "line_count", "content_hash", "file_size", "encoding")
        return self._page(w, opts, ["files", query], [{k: f[k] for k in fields}
            for f in self.store.files(w) if query.casefold() in f["relative_path"].casefold()])

    def _issues(self, w: str, opts: QueryOptions, severity: str="all") -> dict[str, Any]:
        """List workspace diagnostics filtered by severity.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            severity: Severity value.

        Returns:
            The operation response data for the requested use case.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        if severity not in {"all", "info", "warning", "error"}:
            raise AgentError("invalid_argument", "Use all, info, warning or error severity")
        items = self.store.diagnostics(w)
        if severity != "all":
            items = [r for r in items if r["severity"] == severity]
        return self._page(w, opts, ["issues", severity], items, analysis_current=self._current(w))

    def _graph(self, w: str, opts: QueryOptions, keep: str) -> LineageGraph:
        """Build the configured lineage graph after enforcing size limits.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            keep: Asset ID retained while simplifying the graph.

        Returns:
        The configured lineage graph.
        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        assets = self.store.rows("SELECT * FROM assets WHERE workspace_id=? ORDER BY asset_id LIMIT 20001", [w])
        edges = self.store.rows("SELECT edge_id FROM edges WHERE workspace_id=? ORDER BY edge_id LIMIT 100001", [w])
        if len(assets) > 20000 or len(edges) > 100000:
            raise AgentError("resource_limit", "Graph exceeds 20,000 assets or 100,000 evidence edges")
        edges = self.store.edges(w)
        graph = LineageGraph(assets, edges, self.store.setting(w, "min_lineage_confidence", 0.),
                             self.store.setting(w, "include_inferred", True))
        collapse = opts.collapse_temporary
        if collapse is None:
            collapse = self.store.setting(w, "collapse_temporary", False)
        return graph.simplified(keep=[keep]) if collapse else graph

    def _lineage(self, w: str, opts: QueryOptions, asset: str, direction: str="upstream") -> dict[str, Any]:
        """Return bounded lineage around an asset with detail gated by query options.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            asset: Asset ID or name.
            direction: Lineage traversal direction.

        Returns:
            The operation response data for the requested use case.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        if direction not in {"upstream", "downstream", "combined"}:
            raise AgentError("invalid_argument", "Use upstream, downstream or combined direction")
        target = self._asset(w, asset)
        aid = target["asset_id"]
        graph = self._graph(w, opts, aid)
        focused = graph.focus(aid, direction, opts.max_depth, opts.max_items + 1)
        boundaries = []
        if focused.truncated:
            boundaries.append("items_or_missing_metadata")
        for node in focused.nodes:
            neighbors = set()
            if direction in {"upstream", "combined"}:
                neighbors.update(graph.graph.predecessors(node))
            if direction in {"downstream", "combined"}:
                neighbors.update(graph.graph.successors(node))
            if neighbors - set(focused.nodes):
                boundaries.append("depth")
                break
        items = []
        for node in sorted(focused.nodes, key=lambda n: (focused.nodes[n]["name"], n)):
            if node == aid:
                continue
            item = self._asset_summary(focused.nodes[node])
            if opts.detail_level != "summary":
                relationships = []
                incident = list(focused.graph.out_edges(node, data=True))
                if direction != "upstream":
                    incident += list(focused.graph.in_edges(node, data=True))
                for s, t, attrs in incident:
                    for edge in attrs["evidence"]:
                        evidence = {k: edge[k] for k in ("edge_id", "operation_id", "statement_id", "file_id",
                                                        "method", "status", "confidence")}
                        if opts.detail_level == "detailed":
                            evidence.update(self._statement(w, edge["statement_id"]))
                        relationships.append({"source_id": s, "target_id": t,
                                              "intermediates": attrs.get("intermediates", []), **evidence})
                item["relationships"] = relationships
            items.append(item)
        unresolved = sum(graph.nodes[n].get("kind") == "unresolved" for n in focused.nodes)
        evidence = [e for _, _, attrs in focused.graph.edges(data=True) for e in attrs["evidence"]]
        return self._page(w, opts, ["lineage", aid, direction], items, asset_id=aid, asset=target["name"],
            direction=direction, analysis_current=self._current(w), boundaries=sorted(set(boundaries)),
            unresolved_count=unresolved, confidence_min=min((e["confidence"] for e in evidence), default=None),
            statuses=dict(Counter(e["status"] for e in evidence)))

    def _impact(self, w: str, opts: QueryOptions, asset: str) -> dict[str, Any]:
        """Return downstream lineage and counts grouped by asset kind.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            asset: Asset ID or name.

        Returns:
            The operation response data for the requested use case.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        result = self._lineage(w, opts, asset, "downstream")
        result["groups"] = dict(Counter(i["kind"] for i in result["items"]))
        if len(compact(result)) > opts.max_chars:
            raise AgentError("budget_too_small", "Impact grouping exceeds max_chars")
        return result

    def _batch(self, w: str, opts: QueryOptions, assets: list[str], direction: str="upstream") -> dict[str, Any]:
        """Query multiple asset lineages under shared item and response budgets.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            assets: Asset IDs or names.
            direction: Lineage traversal direction.

        Returns:
            The operation response data for the requested use case.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        if not 1 <= len(assets) <= 20 or opts.cursor:
            raise AgentError("invalid_argument", "Batch accepts 1–20 assets and no cursor; paginate individual results")
        results = []
        remaining_items = opts.max_items
        for asset in assets:
            child = opts.model_copy(update={"max_items": max(1, remaining_items),
                                           "limit": min(opts.limit, max(1, remaining_items))})
            try:
                result = self._lineage(w, child, asset, direction)
            except AgentError as exc:
                result = {"asset": asset, **exc.response()}
            candidate = {"workspace_id": w, "results": [*results, result],
                         "processed": len(results) + 1, "requested": len(assets), "complete": False}
            if remaining_items <= 0 or len(compact(candidate)) > opts.max_chars:
                break
            results.append(result)
            remaining_items -= result.get("count", 0)
        complete = len(results) == len(assets) and all(r.get("complete", False) for r in results)
        return {"workspace_id": w, "results": results, "processed": len(results), "requested": len(assets),
                "complete": complete, "remaining_assets": assets[len(results):]}

    def _columns(self, w: str, opts: QueryOptions, asset: str, column_query: str='', usage_type: str='', file_id: str='', group_by: str='none') -> dict[str, Any]:
        """List direct source-column usage with optional filtering and grouping.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            asset: Asset ID or name.
            column_query: Column-name filter.
            usage_type: Usage-context filter.
            file_id: Source file identifier.
            group_by: Grouping mode for direct usage results.

        Returns:
            The operation response data for the requested use case.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        from dataforge.services import column_report
        if group_by not in {'none', 'file', 'usage_type'} or any(len(value) > 1024 for value in (column_query, usage_type, file_id)):
            raise AgentError('validation_failed', 'Invalid direct-column filter/grouping')
        selected = self._asset(w, asset)
        rows = column_report(self.store, w, selected["asset_id"])
        rows = [r for r in rows if column_query.casefold() in r['column_name'].casefold()
                and (not usage_type or usage_type.casefold() in r['context'].casefold())
                and (not file_id or r['file_id'] == file_id)]
        fields = ("column_name", "context", "status", "statement_id", "file_id")
        if opts.detail_level != "summary":
            fields += ("relative_path", "start_line", "end_line", "operation_id", "source_hash")
        if opts.detail_level == "detailed":
            fields += ("code", "expression")
        items = [{k: r[k] for k in fields} for r in rows]
        if group_by != 'none':
            for item, row in zip(items, rows):
                item['group'] = row['relative_path'] if group_by == 'file' else row['context']
            items.sort(key=lambda item: (item['group'], item['column_name']))
        return self._page(w, opts, ["columns", selected["asset_id"], column_query, usage_type, file_id, group_by], items,
                          asset_id=selected["asset_id"], unique_columns=len({r['column_name'] for r in rows}),
                          group_by=group_by, analysis_current=self._current(w))

    def _column_catalog(self, w: str, opts: QueryOptions, asset: str) -> dict[str, Any]:
        """Return a bounded catalog of stored column transformations.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            asset: Asset ID or name.

        Returns:
            The operation response data for the requested use case."""
        from dataforge.transformations import column_catalog
        selected = self._asset(w, asset)
        rows = column_catalog(self.store, w, selected["asset_id"], limit=min(opts.max_items + 1, 20000))
        boundaries = ["items"] if len(rows) > opts.max_items or len(rows) == 20000 else []
        return self._page(w, opts, ["column_catalog", selected["asset_id"]], rows[:opts.max_items],
                          asset_id=selected["asset_id"], boundaries=boundaries,
                          analysis_current=self._current(w))

    def _column_lineage(self, w: str, opts: QueryOptions, asset: str, column: str, direction: str="upstream", status: str="all") -> dict[str, Any]:
        """Trace a column through stored derivations and coverage boundaries.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            asset: Asset ID or name.
            column: Column name to trace.
            direction: Lineage traversal direction.
            status: Derivation status filter.

        Returns:
            The operation response data for the requested use case.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        from dataforge.transformations import trace_columns
        if (direction not in {"upstream", "downstream"} or
                status not in {"all", "verified", "inferred", "unresolved"} or
                not isinstance(column, str) or not column or len(column) > 1024):
            raise AgentError("invalid_argument", "Specify a column, upstream/downstream direction and all/verified/inferred/unresolved status")
        selected = self._asset(w, asset)
        source_allowed = AgentSettings.from_store(self.store, w).allow_source
        trace = trace_columns(self.store, w, selected["asset_id"], column,
                              direction=direction, depth=opts.max_depth, limit=opts.max_items,
                              status=status, include_source=opts.detail_level == "detailed" and source_allowed)
        paths_by_derivation = {}
        for path in trace["paths"]:
            paths_by_derivation.setdefault(path["derivation_id"], []).append(path)
        items = []
        for derivation in trace["derivations"]:
            row = dict(derivation)
            row["evidence"] = dict(row.get("evidence") or {})
            if opts.detail_level == "summary" or not source_allowed:
                row.pop("expression", None)
            if opts.detail_level != "detailed" or not source_allowed:
                row["evidence"].pop("code", None)
            row["paths"] = paths_by_derivation.get(row["derivation_id"], [])
            items.append(row)
        boundaries = []
        if trace.get("truncated"):
            boundaries.append("traversal_limit")
        if not trace.get("complete", False):
            boundaries.append("coverage")
        return self._page(w, opts, ["column_lineage", selected["asset_id"], column, direction, status], items,
                          asset_id=selected["asset_id"], column=trace["column"], direction=direction,
                          depth=opts.max_depth, status=status, state=trace["state"],
                          coverage=trace["coverage"], truncated=trace["truncated"],
                          trace_complete=trace["complete"], run_id=trace.get("run_id"),
                          boundaries=boundaries, analysis_current=self._current(w))

    def _statement(self, w: str, statement_id: str) -> dict[str, Any]:
        """Retrieve original statement evidence and whether its source hash is current.

        Args:
            w: Workspace identifier.
            statement_id: Statement identifier.

        Returns:
            The operation response data for the requested use case.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        rows = self.store.rows("""SELECT s.statement_id,s.file_id,s.start_line,s.end_line,s.code,
            s.content_hash AS source_hash,f.relative_path FROM statements s
            JOIN source_files f ON s.file_id=f.file_id AND s.workspace_id=f.workspace_id
            WHERE s.workspace_id=? AND s.statement_id=?""", [w, statement_id])
        if not rows:
            raise AgentError("not_found", "Statement does not exist in this workspace")
        row = rows[0]
        source = self.store.rows("SELECT content_hash FROM source_files WHERE file_id=? AND workspace_id=?", [row["file_id"], w])[0]
        return {**row, "source_current": source["content_hash"] == row["source_hash"]}

    def _source(self, w: str, opts: QueryOptions, file_id: str | None=None, statement_id: str | None=None, operation_id: str | None=None,
                start_line: int | None=None, end_line: int | None=None, full: bool=False) -> dict[str, Any]:
        """Return bounded original source lines for one file, statement, or operation.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            file_id: Source file identifier.
            statement_id: Statement identifier.
            operation_id: Operation identifier.
            start_line: First source line number.
            end_line: Last source line number.
            full: Whether full source is requested.

        Returns:
            The operation response data for the requested use case.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        if sum(bool(x) for x in (file_id, statement_id, operation_id)) != 1:
            raise AgentError("invalid_argument", "Specify exactly one file_id, statement_id or operation_id")
        if operation_id:
            rows = self.store.rows("SELECT statement_id FROM operations WHERE workspace_id=? AND operation_id=?", [w, operation_id])
            if not rows:
                raise AgentError("not_found", "Operation does not exist in this workspace")
            statement_id = rows[0]["statement_id"]
        if statement_id:
            return self._page(w, opts, ["statement", statement_id], [self._statement(w, statement_id)])
        rows = self.store.rows("SELECT file_id FROM source_files WHERE workspace_id=? AND file_id=?", [w, file_id])
        if not rows:
            raise AgentError("not_found", "File does not exist in this workspace")
        if not full and (start_line is None or end_line is None):
            raise AgentError("invalid_argument", "Specify start_line/end_line or explicitly request full source")
        source = self.store.file(file_id)
        lines = source["raw_content"].splitlines(keepends=True)
        start, end = (1, len(lines)) if full else (start_line, end_line)
        if type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines):
            raise AgentError("invalid_argument", "Line range is outside the source")
        items = [{"file_id": file_id, "source_hash": source["content_hash"], "relative_path": source["relative_path"],
                  "start_line": i + 1, "end_line": min(i + 20, end), "code": "".join(lines[i:min(i + 20, end)])}
                 for i in range(start - 1, end, 20)]
        return self._page(w, opts, ["source", file_id, start, end], items)

    def _search_code(self, w: str, opts: QueryOptions, query: str, include_matches: bool=False) -> dict[str, Any]:
        """Search source metadata or literal code matches when requested.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            query: Literal search text.
            include_matches: Whether to return literal source-code matches.

        Returns:
            The operation response data for the requested use case.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        if include_matches:
            from dataforge.reporting import code_matches
            self._workspace(w, source=True)
            matches = code_matches(self.store, w, query, opts.max_items + 1)
            return self._page(w, opts, ['code_matches', query], matches[:opts.max_items],
                boundaries=['items'] if len(matches) > opts.max_items else [], analysis_current=self._current(w))
        if not query or len(query) > 256:
            raise AgentError("invalid_argument", "Code search requires 1–256 literal characters")
        rows = self.store.rows("""SELECT file_id,relative_path,content_hash,line_count FROM source_files
            WHERE workspace_id=? AND contains(lower(raw_content),lower(?)) ORDER BY relative_path""", [w, query])
        return self._page(w, opts, ["search_code", query], rows)

    def run_operation(self, w: str, operation: str, arguments: dict[str, Any], progress: Callable[[float, str], None] | None=None) -> dict[str, Any]:
        """Execute a queued ingest or analysis operation and record its outcome.

        Args:
            w: Workspace identifier.
            operation: Queued operation name.
            arguments: Operation-specific input values.
            progress: Optional callback receiving a progress fraction and message.

        Returns:
            The operation response data for the requested use case.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        self._workspace(w, write=True)
        if operation == "analyze":
            from dataforge.services import analyze
            ids = arguments.get("file_ids")
            if ids is not None:
                known = {f["file_id"] for f in self.store.files(w)}
                if not ids or not set(ids) <= known or len(ids) > 100000:
                    raise AgentError("invalid_argument", "Selected files must belong to the workspace")
            result = analyze(self.store, w, ids, arguments.get("force", False), progress=progress)
        elif operation == "ingest":
            path = self.policy.import_path(arguments["path"])
            extensions = {"." + e.lstrip(".").lower() for e in arguments["extensions"]}
            limits = Limits(max_files=min(100000, max(1, int(self.store.setting(w, "max_files", 10000)))),
                            max_file_bytes=min(100, int(self.store.setting(w, "max_file_mb", 20))) * 1024 * 1024)
            importer = Importer(self.store, w, self.policy.import_roots, limits)
            report_progress = (lambda report: progress(min(.99, report.discovered / limits.max_files), "Importing")) if progress else None
            with self.store.analysis_lock:
                if path.is_dir():
                    report = importer.directory(path, extensions, progress=report_progress)
                elif path.suffix.lower() == ".zip" and path.stat().st_size <= limits.max_archive_bytes:
                    report = importer.zip(path.read_bytes(), extensions, progress=report_progress)
                else:
                    raise AgentError("invalid_path", "Import an allowed directory or bounded ZIP archive")
            result = asdict(report)
        else:
            raise AgentError("invalid_argument", "Unsupported job operation")
        self.audit(w, operation, "completed")
        return result

    def _ingest(self, w: str, opts: QueryOptions, path: str, extensions: list[str]) -> dict[str, Any]:
        """Validate import inputs and enqueue a background ingestion job.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            path: Allowed import path.
            extensions: Source extensions to include.

        Returns:
            The operation response data for the requested use case.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        self.policy.import_path(path)
        if not extensions or not {e.lstrip(".").lower() for e in extensions} <= {"sql", "sas", "csv"}:
            raise AgentError("invalid_argument", "Select sql, sas and/or csv extensions")
        return self.jobs.start(w, "ingest", lambda p: self.run_operation(w, "ingest", {
            "path": path, "extensions": extensions}, p), AgentSettings.from_store(self.store, w).model_dump())

    def _analyze(self, w: str, opts: QueryOptions, file_ids: list[str] | None=None, force: bool=False) -> dict[str, Any]:
        """Enqueue a background analysis job for selected or all workspace files.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            file_ids: Optional source file identifiers.
            force: Whether to force analysis.

        Returns:
            The operation response data for the requested use case."""
        return self.jobs.start(w, "analyze", lambda p: self.run_operation(w, "analyze", {
            "file_ids": file_ids, "force": force}, p), AgentSettings.from_store(self.store, w).model_dump())

    def _job(self, w: str, opts: QueryOptions, job_id: str) -> dict[str, Any]:
        """Return the status and bounded result for a job identifier.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            job_id: Job identifier.

        Returns:
            The operation response data for the requested use case."""
        return self.job_status(w, job_id, opts.model_dump())

    def job_status(self, w: str, job_id: str, options: dict[str, Any] | None=None) -> dict[str, Any]:
        """Authorize workspace access and return a sanitized, bounded job status.

        Args:
            w: Workspace identifier.
            job_id: Job identifier.
            options: Validated query options.

        Returns:
            The operation response data for the requested use case.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        if not self.policy.permits(w):
            raise AgentError("forbidden", "Workspace is not authorized")
        record = self.jobs.read(job_id, w, private=True)
        # Importer's atomic transaction may own the Store lock for minutes. Its journal
        # and UI-published revocation snapshot remain independently readable.
        if self.store.lock.acquire(blocking=False):
            try:
                settings = self._workspace(w)
            finally:
                self.store.lock.release()
        else:
            settings = job_settings(self.store.home, w, record)
        if not settings.enabled:
            raise AgentError("forbidden", "Agent access is disabled for this workspace")
        values = {"detail_level": settings.default_detail, **(options or {})}
        values["max_chars"] = min(values.get("max_chars", settings.max_chars), settings.max_chars)
        return status_result(record, QueryOptions.model_validate(values))

    def _export(self, w: str, opts: QueryOptions, asset: str, direction: str="upstream", format: str="json") -> dict[str, Any]:
        """Save a bounded lineage report locally and return its artifact metadata.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            asset: Asset ID or name.
            direction: Lineage traversal direction.
            format: Requested export format.

        Returns:
            The operation response data for the requested use case.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        from dataforge.exports import report_csv, report_html
        if format not in {"json", "csv", "html"}:
            raise AgentError("invalid_argument", "Use json, csv or html export")
        result = self._lineage(w, opts, asset, direction)
        content = compact(result) if format == "json" else (
            report_csv(result["items"]) if format == "csv" else report_html(result["items"]))
        result_id = uuid.uuid4().hex
        directory = self.store.home / "agent" / "results" / w
        directory.mkdir(parents=True, exist_ok=True)
        if len(list(directory.iterdir())) >= 1000:
            raise AgentError("resource_limit", "Export limit reached; archive old local result files")
        target = directory / (result_id + "." + format)
        target.write_text(content, encoding="utf-8")
        return {"result_id": result_id, "path": target.relative_to(self.store.home).as_posix(),
                "format": format, "bytes": target.stat().st_size, "complete": result["complete"],
                "next_cursor": result["next_cursor"]}

    def _result(self, w: str, opts: QueryOptions, result_id: str, format: str="json") -> dict[str, Any]:
        """Read an existing local export after validating its ID, format, and response size.

        Args:
            w: Workspace identifier.
            opts: Bounded query and response options.
            result_id: Export result identifier.
            format: Requested export format.

        Returns:
            The operation response data for the requested use case.

        Raises:
            AgentError: If the operation is invalid, unauthorized, or unavailable."""
        import re
        if not re.fullmatch("[a-f0-9]{32}", result_id) or format not in {"json", "csv", "html"}:
            raise AgentError("not_found", "Result does not exist")
        target = self.store.home / "agent" / "results" / w / (result_id + "." + format)
        if not target.is_file() or target.is_symlink():
            raise AgentError("not_found", "Result does not exist in this workspace")
        if target.stat().st_size > opts.max_chars:
            raise AgentError("budget_too_small", "Export exceeds response budget; read its local artifact")
        return {"result_id": result_id, "format": format, "content": target.read_text(encoding="utf-8")}
