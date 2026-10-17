"""Thin CLI adapters for stored inventory, engineering and history reports."""
from pathlib import Path
from typing import Annotated

import typer

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
