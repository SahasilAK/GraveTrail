"""Thin typed CLI adapters for workspace configuration."""
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer

from dataforge.agent.contracts import AgentError
from dataforge.settings_service import read_json_file

Workspace = Annotated[str, typer.Option('--workspace', '-w')]


def register(app: typer.Typer, workspace_app: typer.Typer,
             invoke: Callable[..., Any], fail: Callable[..., Any]) -> None:
    """Register workspace settings and safe configuration transfer commands.

    Args:
        app: Root Typer application.
        workspace_app: Workspace command group.
        invoke: Dispatcher for agent operations.
        fail: Sanitized CLI error handler.
    """
    settings = typer.Typer(help='Typed atomic workspace settings; widening requires local --allow-admin.')
    config = typer.Typer(help='Safe configuration transfers into a new workspace.')
    app.add_typer(settings, name='settings')
    workspace_app.add_typer(config, name='config')

    @settings.command('schema')
    def schema(ctx: typer.Context, workspace: Workspace, section: str = typer.Option(None)) -> None:
        """Show the setting schema, optionally limited to one section.

        Args:
            ctx: Typer command context.
            workspace: Workspace identifier.
            section: Settings section.
        """
        invoke(ctx, 'settings_schema', workspace, section=section)

    @settings.command('get')
    def get(ctx: typer.Context, section: str, workspace: Workspace) -> None:
        """Read a workspace settings section.

        Args:
            ctx: Typer command context.
            section: Settings section.
            workspace: Workspace identifier.
        """
        invoke(ctx, 'settings_get', workspace, section=section)

    @settings.command('update')
    def update(ctx: typer.Context, section: str, file: Path, workspace: Workspace, expected_revision: str = typer.Option(...)) -> None:
        """Update a workspace settings section from bounded JSON.

        Args:
            ctx: Typer command context.
            section: Settings section to update.
            file: Path to the JSON settings object.
            workspace: Workspace identifier.
            expected_revision: Current revision required for the update.
        """
        try:
            values = read_json_file(file)
        except (OSError, ValueError, AgentError):
            return fail(ctx, AgentError('validation_failed', 'Expected a bounded UTF-8 settings JSON object'))
        invoke(ctx, 'settings_update', workspace, section=section, values=values, expected_revision=expected_revision)

    @workspace_app.command('update')
    def workspace_update(ctx: typer.Context, workspace: Workspace, name: str, description: str = '', expected_revision: str = '') -> None:
        """Rename a workspace and update its description.

        Args:
            ctx: Typer command context.
            workspace: Workspace identifier.
            name: Workspace or preset name.
            description: Workspace description.
            expected_revision: Current revision required for the update.
        """
        invoke(ctx, 'workspace_update', workspace, name=name, description=description, expected_revision=expected_revision)

    @config.command('export')
    def export(ctx: typer.Context, workspace: Workspace) -> None:
        """Export the allowed workspace configuration as JSON.

        Args:
            ctx: Typer command context.
            workspace: Workspace identifier.
        """
        invoke(ctx, 'config_export', workspace)

    @config.command('import')
    def import_config(ctx: typer.Context, file: Path) -> None:
        """Create a new workspace from a supported configuration JSON file.

        Args:
            ctx: Typer command context.
            file: Input JSON file path.
        """
        try:
            payload = read_json_file(file)
        except (OSError, ValueError, AgentError):
            return fail(ctx, AgentError('validation_failed', 'Expected a bounded configuration JSON object'))
        invoke(ctx, 'config_import', configuration=payload)


def register_application(app: typer.Typer, invoke: Callable[..., Any]) -> None:
    """Register application-scope, runtime, and agent setup CLI commands.

    Args:
        app: Root Typer application receiving the command groups.
        invoke: Dispatcher for agent operations.
    """
    application = typer.Typer(help='Application scope; mutation requires unrestricted write/config/application grants.')
    theme = typer.Typer(help='Eighteen presets; loaded UI state is unavailable to this process.')
    logging = typer.Typer(help='Home-wide persisted log level; no log-content access.')
    runtime = typer.Typer(help='Runtime owner/home context; switching requires a new invocation.')
    agent = typer.Typer(help='Actual schemas, credential-free client examples and local MCP handler self-test.')
    app.add_typer(application, name='application')
    app.add_typer(runtime, name='runtime')
    app.add_typer(agent, name='agent')
    application.add_typer(theme, name='theme')
    application.add_typer(logging, name='logging')

    @theme.command('list')
    def themes(ctx: typer.Context) -> None:
        """List available application theme presets.

        Args:
            ctx: Typer command context.
        """
        invoke(ctx, 'theme_list')

    @theme.command('get')
    def get_theme(ctx: typer.Context) -> None:
        """Show the configured application theme.

        Args:
            ctx: Typer command context.
        """
        invoke(ctx, 'theme_get')

    @theme.command('apply')
    def apply_theme(ctx: typer.Context, name: str) -> None:
        """Apply the named application theme preset.

        Args:
            ctx: Typer command context.
            name: Workspace or preset name.
        """
        invoke(ctx, 'theme_apply', name=name)

    @logging.command('get')
    def get_logging(ctx: typer.Context) -> None:
        """Read the persisted application log level.

        Args:
            ctx: Typer command context.
        """
        invoke(ctx, 'logging_get')

    @logging.command('update')
    def update_logging(ctx: typer.Context, level: str) -> None:
        """Update the persisted application log level.

        Args:
            ctx: Typer command context.
            level: Application logging level.
        """
        invoke(ctx, 'logging_update', level=level)

    @runtime.command('info')
    def info(ctx: typer.Context, workspace: str = '') -> None:
        """Show runtime owner and home information.

        Args:
            ctx: Typer command context.
            workspace: Workspace identifier.
        """
        invoke(ctx, 'runtime_info', workspace)

    @agent.command('inspect')
    def inspect(ctx: typer.Context, workspace: Workspace, tool_name: str = '') -> None:
        """Show agent setup information, optionally for one tool.

        Args:
            ctx: Typer command context.
            workspace: Workspace identifier.
            tool_name: Optional tool whose schema is requested.
        """
        invoke(ctx, 'agent_setup', workspace, tool_name=tool_name)

    @agent.command('client-config')
    def client_config(ctx: typer.Context, workspace: Workspace, client: str = 'codex', transport: str = 'stdio') -> None:
        """Print client configuration for the selected transport.

        Args:
            ctx: Typer command context.
            workspace: Workspace identifier.
            client: MCP client configuration target.
            transport: MCP transport selection.
        """
        invoke(ctx, 'agent_setup', workspace, client=client, transport=transport)

    @agent.command('self-test')
    def self_test(ctx: typer.Context, workspace: Workspace) -> None:
        """Run a read-only check against local MCP handlers.

        Args:
            ctx: Typer command context.
            workspace: Workspace identifier.
        """
        invoke(ctx, 'agent_self_test', workspace)
