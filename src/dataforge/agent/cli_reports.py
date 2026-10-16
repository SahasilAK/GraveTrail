"""Thin CLI adapters for stored inventory, engineering and history reports."""
from typing import Annotated

import typer

Workspace = Annotated[str, typer.Option('--workspace', '-w')]


def register(app, workspace_app, assets_app, lineage_app, source_app, invoke):
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
