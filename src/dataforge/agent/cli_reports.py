"""Thin CLI adapters for stored inventory, engineering and history reports."""
from pathlib import Path
from typing import Annotated

import typer

from dataforge.settings_service import read_json_file

Workspace = Annotated[str, typer.Option('--workspace', '-w')]


def register(app, workspace_app, assets_app, lineage_app, source_app, exports_app, invoke):
    runs = typer.Typer(help='Stored analysis runs and comparisons.')
    ingestions = typer.Typer(help='Stored import reports and diagnostics.')
    dictionary = typer.Typer(help='Declared, sampled and explicitly unknown column types.')
    app.add_typer(runs, name='runs')
    app.add_typer(ingestions, name='ingestions')
    app.add_typer(dictionary, name='dictionary')

    @runs.command('list')
    def run_list(ctx: typer.Context, workspace: Workspace):
        invoke(ctx, 'runs_list', workspace)

    @runs.command('get')
    def run_get(ctx: typer.Context, run_id: str, workspace: Workspace):
        invoke(ctx, 'run_get', workspace, run_id=run_id)

    @runs.command('compare')
    def compare(ctx: typer.Context, before: str, after: str, workspace: Workspace):
        invoke(ctx, 'runs_compare', workspace, before=before, after=after)

    @ingestions.command('list')
    def ingestion_list(ctx: typer.Context, workspace: Workspace):
        invoke(ctx, 'ingestions_list', workspace)

    @ingestions.command('get')
    def ingestion_get(ctx: typer.Context, ingestion_id: str, workspace: Workspace):
        invoke(ctx, 'ingestion_get', workspace, ingestion_id=ingestion_id)

    @dictionary.command('list')
    def dictionary_list(ctx: typer.Context, workspace: Workspace, query: str = ''):
        invoke(ctx, 'dictionary', workspace, query=query)

    @workspace_app.command('health')
    def health(ctx: typer.Context, workspace: Workspace):
        invoke(ctx, 'health', workspace)

    @assets_app.command('schema')
    def schema(ctx: typer.Context, asset: str, workspace: Workspace):
        invoke(ctx, 'asset_schema', workspace, asset=asset)

    @lineage_app.command('validate')
    def validate(ctx: typer.Context, workspace: Workspace):
        invoke(ctx, 'lineage_validate', workspace)

    @source_app.command('metadata')
    def metadata(ctx: typer.Context, file_id: str, workspace: Workspace):
        invoke(ctx, 'source_metadata', workspace, file_id=file_id)

    @lineage_app.command('paths')
    def paths(ctx: typer.Context, asset: str, workspace: Workspace, direction: str = 'upstream', max_paths: int = 50):
        invoke(ctx, 'paths', workspace, asset=asset, direction=direction, max_paths=max_paths)

    @lineage_app.command('steps')
    def steps(ctx: typer.Context, asset: str, workspace: Workspace, direction: str = 'upstream'):
        invoke(ctx, 'steps', workspace, asset=asset, direction=direction)

    @lineage_app.command('graph')
    def graph_view(ctx: typer.Context, asset: str, workspace: Workspace, direction: str = 'upstream',
                   view: str = 'nodes', node_id: str = '', edge_id: str = ''):
        invoke(ctx, 'graph_view', workspace, asset=asset, direction=direction, view=view, node_id=node_id, edge_id=edge_id)

    @exports_app.command('graph')
    def graph_export(ctx: typer.Context, asset: str, workspace: Workspace, format: str = 'html', direction: str = 'upstream'):
        invoke(ctx, 'artifact_create', workspace, kind='graph', format=format, selection={'asset': asset, 'direction': direction})

    @exports_app.command('paths')
    def path_export(ctx: typer.Context, asset: str, workspace: Workspace, format: str = 'json', direction: str = 'upstream', max_paths: int = 50):
        invoke(ctx, 'artifact_create', workspace, kind='paths', format=format, selection={'asset': asset, 'direction': direction, 'max_paths': max_paths})

    @exports_app.command('sources')
    def source_export(ctx: typer.Context, workspace: Workspace, asset: str = '', file_id: list[str] = typer.Option(None), direction: str = 'upstream'):
        invoke(ctx, 'artifact_create', workspace, kind='source-bundle', format='zip', selection={'asset': asset, 'file_ids': file_id or [], 'direction': direction})

    @source_app.command('download')
    def source_download(ctx: typer.Context, file_id: str, destination: Path, workspace: Workspace, content_hash: str = ''):
        invoke(ctx, 'artifact_create', workspace, kind='original-source', format='raw', selection={'file_id': file_id, 'content_hash': content_hash}, download_to=destination)

    @exports_app.command('download')
    def download(ctx: typer.Context, artifact_id: str, destination: Path, workspace: Workspace):
        invoke(ctx, 'artifact_read', workspace, artifact_id=artifact_id, download_to=destination)

    @exports_app.command('report')
    def report(ctx: typer.Context, workspace: Workspace, kind: str = typer.Option(...), format: str = 'json', asset: str = '',
               query: str = '', before: str = '', after: str = '', record_id: str = ''):
        invoke(ctx, 'artifact_create', workspace, kind=kind, format=format,
            selection={'asset': asset, 'query': query, 'before': before, 'after': after, 'record_id': record_id})


def register_maintenance(app, maintenance_app, invoke, fail):
    def load_preview(ctx, path):
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
    def history_preview(ctx: typer.Context, workspace: Workspace, keep_runs: int = 20, keep_imports: int = 20, batch_size: int = 25):
        invoke(ctx, 'history_preview', workspace, keep_runs=keep_runs, keep_imports=keep_imports, batch_size=batch_size)

    @history.command('archives')
    def archives(ctx: typer.Context, workspace: Workspace):
        invoke(ctx, 'history_archives', workspace)

    @history.command('archive')
    def archive(ctx: typer.Context, preview: Path, workspace: Workspace, confirm: str = ''):
        invoke(ctx, 'history_archive', workspace, preview=load_preview(ctx, preview), confirmation=confirm)

    @history.command('restore')
    def history_restore(ctx: typer.Context, archive_id: str, workspace: Workspace, confirm: str = ''):
        invoke(ctx, 'history_restore', workspace, archive_id=archive_id, confirmation=confirm)

    @staging.command('preview')
    def staging_preview(ctx: typer.Context, workspace: Workspace, age_hours: int = 24):
        invoke(ctx, 'staging_preview', workspace, age_hours=age_hours)

    @staging.command('clean')
    def clean(ctx: typer.Context, preview: Path, workspace: Workspace, confirm: str = '', name: list[str] = typer.Option(None), expired: bool = False):
        # --expired still consumes a saved24h preview and explicit confirmation.
        payload = load_preview(ctx, preview)
        if expired and payload.get('age_hours') != 24:
            from dataforge.agent.contracts import AgentError
            return fail(ctx, AgentError('validation_failed', '--expired requires a24h saved preview'))
        invoke(ctx, 'staging_clean', workspace, preview=payload, confirmation=confirm, names=name)

    @staging.command('recoveries')
    def recoveries(ctx: typer.Context, workspace: Workspace):
        invoke(ctx, 'staging_recoveries', workspace)

    @staging.command('restore')
    def staging_restore(ctx: typer.Context, recovery_id: str, workspace: Workspace, confirm: str = ''):
        invoke(ctx, 'staging_restore', workspace, recovery_id=recovery_id, confirmation=confirm)

    @maintenance_app.command('backups')
    def backups(ctx: typer.Context):
        invoke(ctx, 'backups_list')

    @maintenance_app.command('download')
    def backup_download(ctx: typer.Context, backup_id: str, destination: Path):
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
