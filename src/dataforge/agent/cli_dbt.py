"""Thin dbt catalog CLI adapters."""
from typing import Annotated

import typer

Workspace = Annotated[str, typer.Option('--workspace', '-w')]


def register(app, invoke):
    dbt = typer.Typer(help='Inspect stored dbt projects, resources and typed dependencies.')
    app.add_typer(dbt, name='dbt')

    @dbt.command('projects')
    def projects(ctx: typer.Context, workspace: Workspace):
        """List analyzed dbt project contexts and coverage."""
        invoke(ctx, 'dbt_projects', workspace)

    @dbt.command('resources')
    def resources(ctx: typer.Context, workspace: Workspace, project_id: str = '', resource_type: list[str] = typer.Option(None)):
        """List logical dbt resources, including macros and tests."""
        invoke(ctx, 'dbt_resources', workspace, project_id=project_id, resource_types=resource_type)

    @dbt.command('resource')
    def resource(ctx: typer.Context, resource_id: str, workspace: Workspace):
        """Inspect one exact resource ID; detailed output requires source permission."""
        invoke(ctx, 'dbt_resource', workspace, resource_id=resource_id)

    @dbt.command('dependencies')
    def dependencies(ctx: typer.Context, resource_id: str, workspace: Workspace, direction: str = 'downstream',
                     kind: list[str] = typer.Option(None), max_depth: int = 10):
        """Trace resource dependencies or macro consumers."""
        invoke(ctx, 'dbt_dependencies', workspace, resource_id=resource_id, direction=direction,
               relationship_kinds=kind, max_depth=max_depth)
