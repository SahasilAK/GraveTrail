"""Thin typed CLI adapters for workspace configuration."""
from pathlib import Path
from typing import Annotated

import typer

from dataforge.agent.contracts import AgentError
from dataforge.settings_service import read_json_file

Workspace = Annotated[str, typer.Option('--workspace', '-w')]


def register(app, workspace_app, invoke, fail):
    settings = typer.Typer(help='Typed atomic workspace settings; widening requires local --allow-admin.')
    config = typer.Typer(help='Safe configuration transfers into a new workspace.')
    app.add_typer(settings, name='settings')
    workspace_app.add_typer(config, name='config')

    @settings.command('schema')
    def schema(ctx: typer.Context, workspace: Workspace, section: str = typer.Option(None)):
        invoke(ctx, 'settings_schema', workspace, section=section)

    @settings.command('get')
    def get(ctx: typer.Context, section: str, workspace: Workspace):
        invoke(ctx, 'settings_get', workspace, section=section)

    @settings.command('update')
    def update(ctx: typer.Context, section: str, file: Path, workspace: Workspace, expected_revision: str = typer.Option(...)):
        try:
            values = read_json_file(file)
        except (OSError, ValueError, AgentError):
            return fail(ctx, AgentError('validation_failed', 'Expected a bounded UTF-8 settings JSON object'))
        invoke(ctx, 'settings_update', workspace, section=section, values=values, expected_revision=expected_revision)

    @workspace_app.command('update')
    def workspace_update(ctx: typer.Context, workspace: Workspace, name: str, description: str = '', expected_revision: str = ''):
        invoke(ctx, 'workspace_update', workspace, name=name, description=description, expected_revision=expected_revision)

    @config.command('export')
    def export(ctx: typer.Context, workspace: Workspace):
        invoke(ctx, 'config_export', workspace)

    @config.command('import')
    def import_config(ctx: typer.Context, file: Path):
        try:
            payload = read_json_file(file)
        except (OSError, ValueError, AgentError):
            return fail(ctx, AgentError('validation_failed', 'Expected a bounded configuration JSON object'))
        invoke(ctx, 'config_import', configuration=payload)
