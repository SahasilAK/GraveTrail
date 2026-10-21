"""Thin CLI adapters for stored inventory, engineering and history reports."""
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer

from dataforge.settings_service import read_json_file

Workspace = Annotated[str, typer.Option('--workspace', '-w')]


def register(app: typer.Typer, workspace_app: typer.Typer, assets_app: typer.Typer,
             lineage_app: typer.Typer, source_app: typer.Typer, exports_app: typer.Typer,
             invoke: Callable[..., Any]) -> None:
    """Register CLI commands for stored runs, lineage, inventory, and exports.

    Args:
        app: Root Typer application.
        workspace_app: Workspace command group.
        assets_app: Asset command group.
        lineage_app: Lineage command group.
        source_app: Source command group.
        exports_app: Export command group.
        invoke: Dispatcher for agent operations.
    """
    runs = typer.Typer(help='Stored analysis runs and comparisons.')
    ingestions = typer.Typer(help='Stored import reports and diagnostics.')
    dictionary = typer.Typer(help='Declared, sampled and explicitly unknown column types.')
    app.add_typer(runs, name='runs')
    app.add_typer(ingestions, name='ingestions')
    app.add_typer(dictionary, name='dictionary')

    @runs.command('list')
    def run_list(ctx: typer.Context, workspace: Workspace) -> None:
        """List stored analysis runs for a workspace.

        Args:
            ctx: Typer command context.
            workspace: Workspace identifier.
        """
        invoke(ctx, 'runs_list', workspace)

    @runs.command('get')
    def run_get(ctx: typer.Context, run_id: str, workspace: Workspace) -> None:
        """Show one stored analysis run.

        Args:
            ctx: Typer command context.
            run_id: Run id value.
            workspace: Workspace identifier.
        """
        invoke(ctx, 'run_get', workspace, run_id=run_id)

    @runs.command('compare')
    def compare(ctx: typer.Context, before: str, after: str, workspace: Workspace) -> None:
        """Compare two stored analysis runs.

        Args:
            ctx: Typer command context.
            before: Identifier of the earlier run.
            after: Identifier of the later run.
            workspace: Workspace identifier.
        """
        invoke(ctx, 'runs_compare', workspace, before=before, after=after)

    @ingestions.command('list')
    def ingestion_list(ctx: typer.Context, workspace: Workspace) -> None:
        """List stored ingestion runs for a workspace.

        Args:
            ctx: Typer command context.
            workspace: Workspace identifier.
        """
        invoke(ctx, 'ingestions_list', workspace)

    @ingestions.command('get')
    def ingestion_get(ctx: typer.Context, ingestion_id: str, workspace: Workspace) -> None:
        """Show one stored ingestion report.

        Args:
            ctx: Typer command context.
            ingestion_id: Ingestion report identifier.
            workspace: Workspace identifier.
        """
        invoke(ctx, 'ingestion_get', workspace, ingestion_id=ingestion_id)

    @dictionary.command('list')
    def dictionary_list(ctx: typer.Context, workspace: Workspace, query: str = '') -> None:
        """List dictionary entries optionally filtered by a query string.

        Args:
            ctx: Typer command context.
            workspace: Workspace identifier.
            query: Optional literal search filter.
        """
        invoke(ctx, 'dictionary', workspace, query=query)

    @workspace_app.command('health')
    def health(ctx: typer.Context, workspace: Workspace) -> None:
        """Show workspace health and parsing-status summaries.

        Args:
            ctx: Typer command context.
            workspace: Workspace identifier.
        """
        invoke(ctx, 'health', workspace)

    @assets_app.command('schema')
    def schema(ctx: typer.Context, asset: str, workspace: Workspace) -> None:
        """Show declared schema evidence for an asset.

        Args:
            ctx: Typer command context.
            asset: Asset identifier or name.
            workspace: Workspace identifier.
        """
        invoke(ctx, 'asset_schema', workspace, asset=asset)

    @lineage_app.command('validate')
    def validate(ctx: typer.Context, workspace: Workspace) -> None:
        """Validate stored lineage evidence without analyzing or repairing it.

        Args:
            ctx: Typer command context.
            workspace: Workspace identifier.
        """
        invoke(ctx, 'lineage_validate', workspace)

    @source_app.command('metadata')
    def metadata(ctx: typer.Context, file_id: str, workspace: Workspace) -> None:
        """Show stored metadata and diagnostics for a source file.

        Args:
            ctx: Typer command context.
            file_id: Optional source file identifiers.
            workspace: Workspace identifier.
        """
        invoke(ctx, 'source_metadata', workspace, file_id=file_id)

    @lineage_app.command('paths')
    def paths(ctx: typer.Context, asset: str, workspace: Workspace, direction: str = 'upstream', max_paths: int = 50) -> None:
        """List bounded dependency paths from an asset in the selected direction.

        Args:
            ctx: Typer command context.
            asset: Asset identifier or name.
            workspace: Workspace identifier.
            direction: Lineage traversal direction.
            max_paths: Maximum number of paths to include.
        """
        invoke(ctx, 'paths', workspace, asset=asset, direction=direction, max_paths=max_paths)

    @lineage_app.command('steps')
    def steps(ctx: typer.Context, asset: str, workspace: Workspace, direction: str = 'upstream') -> None:
        """List step-wise lineage rows for an asset.

        Args:
            ctx: Typer command context.
            asset: Asset identifier or name.
            workspace: Workspace identifier.
            direction: Lineage traversal direction.
        """
        invoke(ctx, 'steps', workspace, asset=asset, direction=direction)

    @lineage_app.command('graph')
    def graph_view(ctx: typer.Context, asset: str, workspace: Workspace, direction: str = 'upstream',
                   view: str = 'nodes', node_id: str = '', edge_id: str = '') -> None:
        """Read a bounded lineage graph view or focused graph element.

        Args:
            ctx: Typer command context.
            asset: Asset identifier or name.
            workspace: Workspace identifier.
            direction: Lineage traversal direction.
            view: Graph view mode.
            node_id: Optional graph node identifier.
            edge_id: Optional graph edge identifier.
        """
        invoke(ctx, 'graph_view', workspace, asset=asset, direction=direction, view=view, node_id=node_id, edge_id=edge_id)

    @exports_app.command('graph')
    def graph_export(ctx: typer.Context, asset: str, workspace: Workspace, format: str = 'html', direction: str = 'upstream',
                     scale: int = 1, background: str = 'light', title: str = 'GraveTrail lineage', legend: bool = True,
                     output: Path = typer.Option(None, '--output')) -> None:
        """Export HTML/JSON or fitted SVG/PNG; output paths are created exclusively.

        Args:
            ctx: Typer command context.
            asset: Asset at the root of the graph view.
            workspace: Workspace identifier.
            format: Artifact format to create.
            direction: Traversal direction from the asset.
            scale: Raster or vector export scale.
            background: Export background palette.
            title: Graph title shown in the export.
            legend: Whether to include the legend.
            output: Optional new local output path.
        """
        invoke(ctx, 'artifact_create', workspace, kind='graph', format=format, selection={'asset': asset,
            'direction': direction, 'scale': scale, 'background': background, 'title': title, 'legend': legend},
            download_to=output)

    @exports_app.command('paths')
    def path_export(ctx: typer.Context, asset: str, workspace: Workspace, format: str = 'json', direction: str = 'upstream', max_paths: int = 50,
                    include_evidence: bool = False, include_source_text: bool = False) -> None:
        """Export bounded paths; evidence and source options apply to XLSX.

        Args:
            ctx: Typer command context.
            asset: Asset at the root of the path query.
            workspace: Workspace identifier.
            format: Artifact format to create.
            direction: Traversal direction from the asset.
            max_paths: Maximum number of paths to include.
            include_evidence: Whether to include path evidence in XLSX output.
            include_source_text: Whether to include source text in XLSX output.
        """
        invoke(ctx, 'artifact_create', workspace, kind='paths', format=format, selection={'asset': asset,
            'direction': direction, 'max_paths': max_paths, 'include_evidence': include_evidence,
            'include_source_text': include_source_text})

    @exports_app.command('sources')
    def source_export(ctx: typer.Context, workspace: Workspace, asset: str = '', file_id: list[str] = typer.Option(None), direction: str = 'upstream') -> None:
        """Create a ZIP bundle of source files relevant to the selected asset or files.

        Args:
            ctx: Typer command context.
            workspace: Workspace identifier.
            asset: Asset identifier or name.
            file_id: Optional source file identifiers.
            direction: Lineage traversal direction.
        """
        invoke(ctx, 'artifact_create', workspace, kind='source-bundle', format='zip', selection={'asset': asset, 'file_ids': file_id or [], 'direction': direction})

    @source_app.command('download')
    def source_download(ctx: typer.Context, file_id: str, destination: Path, workspace: Workspace, content_hash: str = '') -> None:
        """Create an artifact containing a selected original source version.

        Args:
            ctx: Typer command context.
            file_id: Optional source file identifiers.
            destination: New destination path.
            workspace: Workspace identifier.
            content_hash: Optional expected source content hash.
        """
        invoke(ctx, 'artifact_create', workspace, kind='original-source', format='raw', selection={'file_id': file_id, 'content_hash': content_hash}, download_to=destination)

    @exports_app.command('download')
    def download(ctx: typer.Context, artifact_id: str, destination: Path, workspace: Workspace) -> None:
        """Write an existing artifact to a new local destination path.

        Args:
            ctx: Typer command context.
            artifact_id: Artifact id value.
            destination: New destination path.
            workspace: Workspace identifier.
        """
        invoke(ctx, 'artifact_read', workspace, artifact_id=artifact_id, download_to=destination)

    @exports_app.command('report')
    def report(ctx: typer.Context, workspace: Workspace, kind: str = typer.Option(...), format: str = 'json', asset: str = '',
               query: str = '', before: str = '', after: str = '', record_id: str = '') -> None:
        """Create a bounded report artifact from the selected report inputs.

        Args:
            ctx: Typer command context.
            workspace: Workspace identifier.
            kind: Report kind.
            format: Requested artifact format.
            asset: Asset identifier or name.
            query: Optional literal search filter.
            before: Identifier of the earlier run.
            after: Identifier of the later run.
            record_id: Saved AI result identifier.
        """
        invoke(ctx, 'artifact_create', workspace, kind=kind, format=format,
            selection={'asset': asset, 'query': query, 'before': before, 'after': after, 'record_id': record_id})


def register_maintenance(app: typer.Typer, maintenance_app: typer.Typer,
                         invoke: Callable[..., Any], fail: Callable[..., Any]) -> None:
    """Register local history, staging, and backup maintenance commands.

    Args:
        app: Root Typer application.
        maintenance_app: Application maintenance command group.
        invoke: Dispatcher for agent operations.
        fail: Sanitized CLI error handler.
    """
    def load_preview(ctx: typer.Context, path: Path) -> Any:
        """Load a bounded maintenance preview JSON file or report a CLI error.

        Args:
            ctx: Typer command context.
            path: Saved preview file path.

        Returns:
            Parsed preview data.
        """
        from dataforge.agent.contracts import AgentError
        try:
            return read_json_file(path)
        except (OSError, ValueError, AgentError):
            return fail(ctx, AgentError('validation_failed', 'Expected a saved bounded JSON maintenance preview'))
    history = typer.Typer(help='Local guarded history archive/recovery; metadata previews are read-only.')
    staging = typer.Typer(help='Local guarded stale staging cleanup/recovery; never automatic on CLI/MCP reads.')
    app.add_typer(history, name='history')
    app.add_typer(staging, name='staging')

    @history.command('preview')
    def history_preview(ctx: typer.Context, workspace: Workspace, keep_runs: int = 20, keep_imports: int = 20, batch_size: int = 25) -> None:
        """Preview eligible history archives and retention effects.

        Args:
            ctx: Typer command context.
            workspace: Workspace identifier.
            keep_runs: Number of analysis runs to retain.
            keep_imports: Number of ingestion reports to retain.
            batch_size: Records handled per maintenance batch.
        """
        invoke(ctx, 'history_preview', workspace, keep_runs=keep_runs, keep_imports=keep_imports, batch_size=batch_size)

    @history.command('archives')
    def archives(ctx: typer.Context, workspace: Workspace) -> None:
        """List locally available history archives.

        Args:
            ctx: Typer command context.
            workspace: Workspace identifier.
        """
        invoke(ctx, 'history_archives', workspace)

    @history.command('archive')
    def archive(ctx: typer.Context, preview: Path, workspace: Workspace, confirm: str = '') -> None:
        """Archive history using a saved preview and explicit confirmation.

        Args:
            ctx: Typer command context.
            preview: Saved preview JSON file path.
            workspace: Workspace identifier.
            confirm: Exact confirmation text.
        """
        invoke(ctx, 'history_archive', workspace, preview=load_preview(ctx, preview), confirmation=confirm)

    @history.command('restore')
    def history_restore(ctx: typer.Context, archive_id: str, workspace: Workspace, confirm: str = '') -> None:
        """Restore a history archive after explicit confirmation.

        Args:
            ctx: Typer command context.
            archive_id: History archive identifier.
            workspace: Workspace identifier.
            confirm: Exact confirmation text.
        """
        invoke(ctx, 'history_restore', workspace, archive_id=archive_id, confirmation=confirm)

    @staging.command('preview')
    def staging_preview(ctx: typer.Context, workspace: Workspace, age_hours: int = 24) -> None:
        """Preview stale staging files older than the requested age.

        Args:
            ctx: Typer command context.
            workspace: Workspace identifier.
            age_hours: Minimum age in hours for staging candidates.
        """
        invoke(ctx, 'staging_preview', workspace, age_hours=age_hours)

    @staging.command('clean')
    def clean(ctx: typer.Context, preview: Path, workspace: Workspace, confirm: str = '', name: list[str] = typer.Option(None), expired: bool = False) -> None:
        """Clean selected staging files from a saved preview after confirmation.

        Args:
            ctx: Typer command context.
            preview: Saved preview JSON file path.
            workspace: Workspace identifier.
            confirm: Exact confirmation text.
            name: Workspace or preset name.
            expired: Whether to apply the saved 24-hour expired-file selection.
        """
        # --expired still consumes a saved24h preview and explicit confirmation.
        payload = load_preview(ctx, preview)
        if expired and payload.get('age_hours') != 24:
            from dataforge.agent.contracts import AgentError
            return fail(ctx, AgentError('validation_failed', '--expired requires a24h saved preview'))
        invoke(ctx, 'staging_clean', workspace, preview=payload, confirmation=confirm, names=name)

    @staging.command('recoveries')
    def recoveries(ctx: typer.Context, workspace: Workspace) -> None:
        """List staging cleanup recovery records.

        Args:
            ctx: Typer command context.
            workspace: Workspace identifier.
        """
        invoke(ctx, 'staging_recoveries', workspace)

    @staging.command('restore')
    def staging_restore(ctx: typer.Context, recovery_id: str, workspace: Workspace, confirm: str = '') -> None:
        """Restore files from a staging cleanup recovery record.

        Args:
            ctx: Typer command context.
            recovery_id: Staging recovery identifier.
            workspace: Workspace identifier.
            confirm: Exact confirmation text.
        """
        invoke(ctx, 'staging_restore', workspace, recovery_id=recovery_id, confirmation=confirm)

    @maintenance_app.command('backups')
    def backups(ctx: typer.Context) -> None:
        """List runtime database backups available to the local CLI.

        Args:
            ctx: Typer command context.
        """
        invoke(ctx, 'backups_list')

    @maintenance_app.command('download')
    def backup_download(ctx: typer.Context, backup_id: str, destination: Path) -> None:
        """Copy a validated runtime backup to a new destination and report its hash.

        Args:
            ctx: Typer command context containing launch policy and home.
            backup_id: Identifier of the backup to copy.
            destination: New destination file path.
        """
        import hashlib
        import re
        import shutil

        from dataforge.agent.contracts import AgentError
        from dataforge.cleanup import checked_path
        from dataforge.database_maintenance import MAX_BACKUP_BYTES
        policy = ctx.obj['policy']
        if policy.workspaces is not None or not policy.allow_application_config:
            return fail(ctx, AgentError('requires_local_admin', 'Backup download requires unrestricted --allow-application-config'))
        if not re.fullmatch('[a-f0-9]{32}', backup_id):
            return fail(ctx, AgentError('not_found', 'Unknown backup ID'))
        try:
            source = checked_path(ctx.obj['home'], 'backups/' + backup_id + '.zip')
            if not source.is_file() or source.stat().st_size > MAX_BACKUP_BYTES:
                raise ValueError('Invalid backup')
            with source.open('rb') as stream, destination.open('xb') as output:
                shutil.copyfileobj(stream, output, 65536)
            with destination.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        except (ValueError, OSError):
            return fail(ctx, AgentError('io_error', 'Backup unavailable or destination already exists'))
        from dataforge.agent.contracts import compact
        typer.echo(compact({'backup_id': backup_id, 'bytes': destination.stat().st_size, 'sha256': digest}))
