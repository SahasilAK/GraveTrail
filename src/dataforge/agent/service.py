"""Shared deterministic automation use cases over the existing application services."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections import Counter
from dataclasses import asdict

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
from dataforge.configuration import ParsingSettings
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


class AgentService(ProviderOperations, AIOperations, ReportOperations, ArtifactOperations):
    def __init__(self, store, policy: AccessPolicy | None = None):
        self.store, self.policy = store, policy or AccessPolicy()
        self.jobs = Jobs(store.home)
        self.runtime_connections = {}
        self.provider_transport = None
        import os
        from pathlib import Path

        from dataforge.launcher import application_root
        self.theme_config_path = Path(os.environ.get('DATAFORGE_THEME_CONFIG', str(application_root() / '.streamlit/config.toml')))
        self.configured_storage = os.environ.get('DATAFORGE_STORAGE_LOCATIONS', '')

    def close(self):
        for manager in self.runtime_connections.values():
            manager.clear()
        self.runtime_connections.clear()
        self.jobs.close()

    def _workspace(self, workspace, write=False, source=False):
        if not self.policy.permits(workspace):
            raise AgentError("forbidden", "Workspace access is not authorized")
        matches = self.store.rows("SELECT workspace_id,name FROM workspaces WHERE workspace_id=?", [workspace])
        if not matches:
            raise AgentError("not_found", "Workspace does not exist; use its exact workspace_id")
        settings = AgentSettings.from_store(self.store, workspace)
        if not settings.enabled or (write and (not self.policy.allow_write or not settings.allow_write)):
            raise AgentError("forbidden", "Agent access or mutation is disabled for this launch/workspace")
        if source and not settings.allow_source:
            raise AgentError("forbidden", "Source retrieval is disabled for this workspace")
        return settings

    def audit(self, workspace, action, outcome):
        directory = self.store.home / "agent"
        directory.mkdir(exist_ok=True)
        path = directory / "audit.jsonl"
        if path.exists() and path.stat().st_size > 1024 * 1024:
            path.replace(directory / "audit.previous.jsonl")
        with path.open("a", encoding="utf-8") as stream:
            stream.write(compact({"at": time.time(), "workspace_id": workspace,
                                  "action": action, "outcome": outcome}) + "\n")

    def call(self, action: str, workspace_id: str = "", options=None, **arguments):
        """Transport-neutral request boundary. No queries parse files or contact an LLM."""
        if action not in {"workspaces", "create_workspace", "summary", "assets", "files", "issues",
                          "lineage", "impact", "batch", "columns", "source", "search_code",
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
            with self.store.lock:
                if action in {"workspaces", "create_workspace", 'config_import', 'database_inspect', 'backups_list'} or action in APPLICATION_ACTIONS or (action == 'capabilities' and not workspace_id):
                    settings = AgentSettings()
                    if action == 'runtime_info' and workspace_id:
                        settings = self._workspace(workspace_id)
                    if write and (not self.policy.allow_write or self.policy.workspaces is not None):
                        raise AgentError("forbidden", "Workspace creation requires unrestricted explicit write access")
                else:
                    settings = self._workspace(workspace_id, write=write,
                        source=action in {"source", "result"} or (options or {}).get("detail_level") == "detailed")
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

    def _theme_list(self, w, opts):
        from dataforge.theme_configuration import PRESETS
        return self._page('', opts, 'themes', [{'name': name, 'base': p['base']} for name, p in PRESETS.items()])

    def _theme_get(self, w, opts):
        from dataforge.theme_configuration import current_preset
        if w or self.policy.workspaces is not None:
            raise AgentError('requires_local_admin', 'Application theme requires unrestricted launch without a workspace argument')
        configured = current_preset(self.theme_config_path) if self.theme_config_path.is_file() else None
        return {'configured': configured, 'detected': configured, 'loaded': None,
                'reload_required': True, 'note': 'Loaded UI appearance is unavailable to a separate CLI/MCP process'}

    def _theme_apply(self, w, opts, name):
        from dataforge.theme_configuration import apply_preset
        self.policy.require('application')
        if w:
            raise AgentError('validation_failed', 'Application operations do not accept workspace IDs')
        apply_preset(self.theme_config_path, name)
        return self._theme_get(w, opts)

    def _logging_get(self, w, opts):
        if w or self.policy.workspaces is not None:
            raise AgentError('requires_local_admin', 'Application logging requires unrestricted launch without a workspace argument')
        return {'level': self.store.setting('__application__', 'log_level', 'INFO'), 'scope': 'application'}

    def _logging_update(self, w, opts, level):
        from dataforge.logging_config import save_application_logging
        self.policy.require('application')
        self._logging_get(w, opts)
        save_application_logging(self.store, level)
        return {**self._logging_get(w, opts), 'reload_required': True}

    def _runtime_info(self, w, opts):
        from dataforge.storage_locations import allowed_homes
        result = {'ownership': 'One DuckDB owning process per home', 'live_switch': False,
                  'switch': 'Relaunch CLI/MCP with an authorized --home; UI changes only its browser session'}
        if self.policy.workspaces is None:
            result.update(home=str(self.store.home), allowed_homes=allowed_homes(self.store.home, self.configured_storage))
        return result

    def _agent_setup(self, w, opts, client='codex', transport='stdio', tool_name=''):
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
                  'codex_toml': '[mcp_servers.dataforge]\ncommand = ' + json.dumps(sys.executable) + '\nargs = ' + json.dumps(args),
                  'claude': {'mcpServers': {'dataforge': stdio}},
                  'http': {'url': 'http://127.0.0.1:8765/mcp', 'bearer_reference': 'DATAFORGE_MCP_TOKEN',
                           'authentication': 'pre-provisioned bearer; external TLS reverse proxy required'},
                  'tools': [t.name for t in tools], 'ownership': 'Stop any other owner before launching an external client'}
        if tool_name:
            matches = [t for t in tools if t.name == tool_name]
            if not matches:
                raise AgentError('not_found', 'Unknown tool schema')
            result = {'tool': matches[0].model_dump(mode='json')}
        return result

    def _agent_self_test(self, w, opts):
        import asyncio

        from dataforge.agent.mcp_server import create_server
        result = asyncio.run(create_server(self).call_tool('get_workspace_summary', {'workspace_id': w}))
        if result.isError:
            raise AgentError(result.structuredContent['error']['code'], 'Local MCP handler check failed')
        return {'passed': True, 'method': 'in_process_mcp_handler', 'summary': result.structuredContent,
                'note': 'External stdio/HTTP connectivity is a separate client test'}

    def _capabilities(self, w, opts):
        from dataforge.agent.capabilities import capability_catalog
        return self._page(w, opts, 'capabilities', capability_catalog(self, w), schema_version=1)

    def _settings_schema(self, w, opts, section=None):
        from dataforge.settings_service import settings_schema
        return settings_schema(section)

    def _settings_get(self, w, opts, section):
        from dataforge.settings_service import read_settings
        return read_settings(self.store, w, section)

    def _settings_update(self, w, opts, section, values, expected_revision):
        from dataforge.settings_service import update_settings
        return update_settings(self.store, self.policy, w, section, values, expected_revision)

    def _workspace_update(self, w, opts, name, description, expected_revision):
        from dataforge.settings_service import check_revision, revision
        self.policy.require('config')
        check_revision(self.store, w, expected_revision)
        self.store.update_workspace(w, name, description)
        return {'workspace_id': w, 'settings_revision': revision(self.store, w)}

    def _config_export(self, w, opts):
        from dataforge.configuration import export_workspace_configuration
        return {'configuration': json.loads(export_workspace_configuration(self.store, w))}

    def _config_import(self, w, opts, configuration):
        from dataforge.configuration import import_workspace_configuration
        self.policy.require('config')
        if self.policy.workspaces is not None:
            raise AgentError('forbidden', 'Configuration import creates a new workspace; unrestricted launch required')
        return {'workspace_id': import_workspace_configuration(self.store, compact(configuration))}

    def _revision(self, w):
        files = self.store.rows("SELECT file_id,content_hash,parsing_status FROM source_files WHERE workspace_id=? ORDER BY file_id", [w])
        runs = self.store.rows("SELECT run_id FROM analysis_runs WHERE workspace_id=? AND status='completed' ORDER BY created_at DESC LIMIT 1", [w])
        return [files, runs]

    def _cleanup_inspect(self, w, opts):
        from dataforge.cleanup import cleanup_plan
        plans = {category: cleanup_plan(self.store, w, category) for category in
                 ('sources', 'lineage', 'columns', 'ai', 'history', 'jobs', 'reset', 'workspace')}
        return {'workspace_id': w, 'categories': {key: {'records': p['records'],
                'logical_bytes_estimate': p['logical_bytes_estimate'], 'file_bytes': p['file_bytes']}
                for key, p in plans.items()}, 'notes': next(iter(plans.values()))['notes'],
                'restricted_categories': {'cache': 'requires_local_ui', 'orphans': 'requires_local_ui',
                                          'application': 'requires_local_ui'}}

    def _cleanup_preview(self, w, opts, category='lineage', file_ids=None, run_id=None):
        from dataforge.cleanup import cleanup_plan
        if category in {'application', 'cache', 'orphans'}:
            if self.policy.workspaces is not None or not self.policy.allow_application_config:
                raise AgentError('requires_local_ui', 'Shared cleanup inspection requires an unrestricted application-authorized launch; apply in Settings UI')
            plan = cleanup_plan(self.store, '', category)
            return {'category': category, 'records': plan['records'], 'logical_bytes_estimate': plan['logical_bytes_estimate'],
                    'file_bytes': plan['file_bytes'], 'restriction': 'requires_local_ui', 'notes': plan['notes']}
        return cleanup_plan(self.store, w, category, file_ids, run_id)

    def _cleanup_apply(self, w, opts, preview, confirmation='', backup_first=False):
        from dataforge.cleanup import apply_cleanup
        if backup_first and self.policy.workspaces is not None:
            raise AgentError('forbidden', 'Whole-home backup requires unrestricted local access')
        if preview.get('workspace_id') != w or preview.get('category') in {'application', 'cache', 'orphans'}:
            raise AgentError('forbidden', 'Cleanup preview is outside the permitted workspace')
        if not backup_first:
            raise AgentError('validation_failed', 'General cleanup requires a full-home backup; pass the explicit backup option')
        return apply_cleanup(self.store, preview, confirmation, backup_first)

    def _history_preview(self, w, opts, keep_runs=20, keep_imports=20, batch_size=25):
        from dataforge.cleanup import checked_path
        from dataforge.maintenance import history_plan
        checked_path(self.store.home, 'history-recovery/' + w)
        plan = {'workspace_id': w, 'keep_runs': keep_runs, 'keep_imports': keep_imports, 'batch_size': batch_size,
                **history_plan(self.store, w, keep_runs, keep_imports, batch_size)}
        plan['token'] = hashlib.sha256(compact(plan).encode()).hexdigest()
        return plan

    def _maintenance_confirmation(self, w, confirmation):
        name = self.store.rows('SELECT name FROM workspaces WHERE workspace_id=?', [w])[0]['name']
        if name != confirmation:
            raise AgentError('validation_failed', 'Type the exact current workspace name to confirm local maintenance')
        if self.policy.workspaces is not None:
            raise AgentError('forbidden', 'Recoverable full-home backup requires an unrestricted local launch')

    def _history_archive(self, w, opts, preview, confirmation):
        from dataforge.database_maintenance import backup
        from dataforge.maintenance import archive_history
        self._maintenance_confirmation(w, confirmation)
        current = self._history_preview(w, opts, preview['keep_runs'], preview['keep_imports'], preview['batch_size'])
        if current != preview:
            raise AgentError('conflict', 'History eligibility changed; refresh preview')
        backup_id = backup(self.store).stem
        result = archive_history(self.store, w, preview['keep_runs'], preview['keep_imports'], preview['batch_size'])
        return {**result, 'backup_id': backup_id}

    def _history_archives(self, w, opts):
        from dataforge.cleanup import checked_path
        from dataforge.maintenance import list_archives
        checked_path(self.store.home, 'history-recovery/' + w)
        return self._page(w, opts, 'history_archives', list_archives(self.store, w))

    def _history_restore(self, w, opts, archive_id, confirmation):
        from dataforge.cleanup import checked_path
        from dataforge.maintenance import restore_history
        self._maintenance_confirmation(w, confirmation)
        checked_path(self.store.home, 'history-recovery/' + w)
        return restore_history(self.store, w, archive_id)

    def _staging_preview(self, w, opts, age_hours=24):
        from dataforge.temporary_cleanup import temporary_plan
        plan = {'workspace_id': w, 'age_hours': age_hours, **temporary_plan(self.store, w, age_hours)}
        plan['token'] = hashlib.sha256(compact(plan).encode()).hexdigest()
        return plan

    def _staging_clean(self, w, opts, preview, confirmation, names=None):
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

    def _staging_recoveries(self, w, opts):
        from dataforge.temporary_cleanup import temporary_recoveries
        return self._page(w, opts, 'staging_recoveries', temporary_recoveries(self.store, w))

    def _staging_restore(self, w, opts, recovery_id, confirmation):
        from dataforge.temporary_cleanup import restore_temporary
        self._maintenance_confirmation(w, confirmation)
        return restore_temporary(self.store, w, recovery_id)

    def _global_metadata(self, w):
        if w or self.policy.workspaces is not None or not self.policy.allow_application_config:
            raise AgentError('requires_local_admin', 'Whole-home metadata requires unrestricted --allow-application-config; no workspace argument')

    def _database_inspect(self, w, opts):
        from dataforge.database_maintenance import inspect_database
        self._global_metadata(w)
        return inspect_database(self.store)

    def _backups_list(self, w, opts):
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

    def _current(self, w):
        files = self.store.files(w)
        runs = self.store.rows("SELECT snapshot,configuration FROM analysis_runs WHERE workspace_id=? AND status='completed' ORDER BY created_at DESC LIMIT 1", [w])
        config = ParsingSettings.model_validate({key: self.store.setting(w, key, default)
            for key, default in ParsingSettings().model_dump().items()}).model_dump()
        return bool(runs) and all(f["parsing_status"] != "pending" for f in files) and (
            json.loads(runs[0]["snapshot"])["files"] == {f["relative_path"]: f["content_hash"] for f in files}
            and json.loads(runs[0]["configuration"]) == config)

    def _page(self, w, opts, action, items, **metadata):
        key = [w, action, self._revision(w), opts.model_dump(exclude={"cursor", "limit", "max_chars"}),
               hashlib.sha256(compact(items).encode()).hexdigest()]
        return page(items, opts, key, workspace_id=w, **metadata)

    def _workspaces(self, w, opts, query=""):
        items = [{k: row[k] for k in ("workspace_id", "name", "description")}
                 for row in self.store.workspaces() if self.policy.permits(row["workspace_id"])
                 and AgentSettings.from_store(self.store, row["workspace_id"]).enabled
                 and query.casefold() in row["name"].casefold()]
        return self._page(w, opts, ["workspaces", query], items)

    def _create_workspace(self, w, opts, name, description=""):
        return {"workspace_id": self.store.create_workspace(name, description), "name": name}

    def _summary(self, w, opts):
        counts = {}
        for table in ("source_files", "assets", "edges", "diagnostics"):
            counts[table] = self.store.rows(f"SELECT count(*) AS n FROM {table} WHERE workspace_id=?", [w])[0]["n"]
        return {"workspace_id": w, **counts, "analysis_current": self._current(w)}

    def _asset(self, w, value):
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
    def _asset_summary(a):
        return {"asset_id": a["asset_id"], "name": asset_label(a), "kind": a["kind"],
                "temporary": a["temporary"]}

    def _assets(self, w, opts, query=""):
        if len(query) > 1024:
            raise AgentError("invalid_argument", "Search query is too long")
        items = [self._asset_summary(a) for a in self.store.assets(w) if query.casefold() in a["name"].casefold()]
        return self._page(w, opts, ["assets", query], items, analysis_current=self._current(w))

    def _files(self, w, opts, query=""):
        fields = ("file_id", "relative_path", "extension", "parsing_status", "line_count", "content_hash", "file_size", "encoding")
        return self._page(w, opts, ["files", query], [{k: f[k] for k in fields}
            for f in self.store.files(w) if query.casefold() in f["relative_path"].casefold()])

    def _issues(self, w, opts, severity="all"):
        if severity not in {"all", "info", "warning", "error"}:
            raise AgentError("invalid_argument", "Use all, info, warning or error severity")
        items = self.store.diagnostics(w)
        if severity != "all":
            items = [r for r in items if r["severity"] == severity]
        return self._page(w, opts, ["issues", severity], items, analysis_current=self._current(w))

    def _graph(self, w, opts, keep):
        assets = self.store.rows("SELECT * FROM assets WHERE workspace_id=? ORDER BY asset_id LIMIT 20001", [w])
        edges = self.store.rows("SELECT * FROM edges WHERE workspace_id=? ORDER BY edge_id LIMIT 100001", [w])
        if len(assets) > 20000 or len(edges) > 100000:
            raise AgentError("resource_limit", "Graph exceeds 20,000 assets or 100,000 evidence edges")
        graph = LineageGraph(assets, edges, self.store.setting(w, "min_lineage_confidence", 0.),
                             self.store.setting(w, "include_inferred", True))
        collapse = opts.collapse_temporary
        if collapse is None:
            collapse = self.store.setting(w, "collapse_temporary", False)
        return graph.simplified(keep=[keep]) if collapse else graph

    def _lineage(self, w, opts, asset, direction="upstream"):
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

    def _impact(self, w, opts, asset):
        result = self._lineage(w, opts, asset, "downstream")
        result["groups"] = dict(Counter(i["kind"] for i in result["items"]))
        if len(compact(result)) > opts.max_chars:
            raise AgentError("budget_too_small", "Impact grouping exceeds max_chars")
        return result

    def _batch(self, w, opts, assets, direction="upstream"):
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

    def _columns(self, w, opts, asset, column_query='', usage_type='', file_id='', group_by='none'):
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

    def _statement(self, w, statement_id):
        rows = self.store.rows("""SELECT s.statement_id,s.file_id,s.start_line,s.end_line,s.code,
            s.content_hash AS source_hash,f.relative_path FROM statements s
            JOIN source_files f ON s.file_id=f.file_id AND s.workspace_id=f.workspace_id
            WHERE s.workspace_id=? AND s.statement_id=?""", [w, statement_id])
        if not rows:
            raise AgentError("not_found", "Statement does not exist in this workspace")
        row = rows[0]
        source = self.store.rows("SELECT content_hash FROM source_files WHERE file_id=? AND workspace_id=?", [row["file_id"], w])[0]
        return {**row, "source_current": source["content_hash"] == row["source_hash"]}

    def _source(self, w, opts, file_id=None, statement_id=None, operation_id=None,
                start_line=None, end_line=None, full=False):
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

    def _search_code(self, w, opts, query, include_matches=False):
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

    def run_operation(self, w, operation, arguments, progress=None):
        self._workspace(w, write=True)
        if operation == "analyze":
            from dataforge.services import analyze
            ids = arguments.get("file_ids")
            if ids is not None:
                known = {f["file_id"] for f in self.store.files(w)}
                if not ids or not set(ids) <= known or len(ids) > 10000:
                    raise AgentError("invalid_argument", "Selected files must belong to the workspace")
            result = analyze(self.store, w, ids, arguments.get("force", False), progress=progress)
        elif operation == "ingest":
            path = self.policy.import_path(arguments["path"])
            extensions = {"." + e.lstrip(".").lower() for e in arguments["extensions"]}
            limits = Limits(max_files=min(10000, int(self.store.setting(w, "max_files", 10000))),
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

    def _ingest(self, w, opts, path, extensions):
        self.policy.import_path(path)
        if not extensions or not {e.lstrip(".").lower() for e in extensions} <= {"sql", "sas", "csv"}:
            raise AgentError("invalid_argument", "Select sql, sas and/or csv extensions")
        return self.jobs.start(w, "ingest", lambda p: self.run_operation(w, "ingest", {
            "path": path, "extensions": extensions}, p), AgentSettings.from_store(self.store, w).model_dump())

    def _analyze(self, w, opts, file_ids=None, force=False):
        return self.jobs.start(w, "analyze", lambda p: self.run_operation(w, "analyze", {
            "file_ids": file_ids, "force": force}, p), AgentSettings.from_store(self.store, w).model_dump())

    def _job(self, w, opts, job_id):
        return self.job_status(w, job_id, opts.model_dump())

    def job_status(self, w, job_id, options=None):
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

    def _export(self, w, opts, asset, direction="upstream", format="json"):
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

    def _result(self, w, opts, result_id, format="json"):
        import re
        if not re.fullmatch("[a-f0-9]{32}", result_id) or format not in {"json", "csv", "html"}:
            raise AgentError("not_found", "Result does not exist")
        target = self.store.home / "agent" / "results" / w / (result_id + "." + format)
        if not target.is_file() or target.is_symlink():
            raise AgentError("not_found", "Result does not exist in this workspace")
        if target.stat().st_size > opts.max_chars:
            raise AgentError("budget_too_small", "Export exceeds response budget; read its local artifact")
        return {"result_id": result_id, "format": format, "content": target.read_text(encoding="utf-8")}
