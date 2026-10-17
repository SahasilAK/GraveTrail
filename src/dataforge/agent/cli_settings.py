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


def register_application(app, invoke):
    application = typer.Typer(help='Application scope; mutation requires unrestricted write/config/application grants.')
    theme = typer.Typer(help='Fourteen presets; loaded UI state is unavailable to this process.')
    logging = typer.Typer(help='Home-wide persisted log level; no log-content access.')
    runtime = typer.Typer(help='Runtime owner/home context; switching requires a new invocation.')
    agent = typer.Typer(help='Actual schemas, credential-free client examples and local MCP handler self-test.')
    app.add_typer(application, name='application')
    app.add_typer(runtime, name='runtime')
    app.add_typer(agent, name='agent')
    application.add_typer(theme, name='theme')
    application.add_typer(logging, name='logging')

    @theme.command('list')
    def themes(ctx: typer.Context):
        invoke(ctx, 'theme_list')

    @theme.command('get')
    def get_theme(ctx: typer.Context):
        invoke(ctx, 'theme_get')

    @theme.command('apply')
    def apply_theme(ctx: typer.Context, name: str):
        invoke(ctx, 'theme_apply', name=name)

    @logging.command('get')
    def get_logging(ctx: typer.Context):
        invoke(ctx, 'logging_get')

    @logging.command('update')
    def update_logging(ctx: typer.Context, level: str):
        invoke(ctx, 'logging_update', level=level)

    @runtime.command('info')
    def info(ctx: typer.Context, workspace: str = ''):
        invoke(ctx, 'runtime_info', workspace)

    @agent.command('inspect')
    def inspect(ctx: typer.Context, workspace: Workspace, tool_name: str = ''):
        invoke(ctx, 'agent_setup', workspace, tool_name=tool_name)

    @agent.command('client-config')
    def client_config(ctx: typer.Context, workspace: Workspace, client: str = 'codex', transport: str = 'stdio'):
        invoke(ctx, 'agent_setup', workspace, client=client, transport=transport)

    @agent.command('self-test')
    def self_test(ctx: typer.Context, workspace: Workspace):
        invoke(ctx, 'agent_self_test', workspace)
