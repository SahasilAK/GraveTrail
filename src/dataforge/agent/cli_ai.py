"""Explicit provider and AI CLI commands. Credentials use hidden per-call input only."""
from pathlib import Path
from typing import Annotated

import typer

from dataforge.agent.contracts import AgentError
from dataforge.settings_service import read_json_file

Workspace = Annotated[str, typer.Option('--workspace', '-w')]


def register(app, invoke, fail):
    providers = typer.Typer(help='Profiles, approved runtime references and explicit outbound tests.')
    routing = typer.Typer(help='Default, five task routes and ordered fallbacks.')
    credentials = typer.Typer(help='Status only; use --credential-prompt on a single operation for hidden input.')
    app.add_typer(providers, name='providers')
    providers.add_typer(routing, name='routing')
    providers.add_typer(credentials, name='credentials')

    @providers.command('list')
    def list_profiles(ctx: typer.Context, workspace: Workspace):
        invoke(ctx, 'providers_list', workspace)

    @providers.command('get')
    def get_profile(ctx: typer.Context, profile_id: str, workspace: Workspace):
        invoke(ctx, 'provider_get', workspace, profile_id=profile_id)

    @providers.command('save')
    def save(ctx: typer.Context, file: Path, workspace: Workspace, expected_revision: str = typer.Option(...), profile_id: str = ''):
        try:
            profile = read_json_file(file)
        except (ValueError, OSError, AgentError):
            return fail(ctx, AgentError('validation_failed', 'Expected bounded profile JSON without secret values'))
        invoke(ctx, 'provider_save', workspace, profile=profile, expected_revision=expected_revision, profile_id=profile_id)

    @providers.command('remove')
    def remove(ctx: typer.Context, profile_id: str, workspace: Workspace, expected_revision: str = typer.Option(...)):
        invoke(ctx, 'provider_remove', workspace, profile_id=profile_id, expected_revision=expected_revision)

    @credentials.command('status')
    def status(ctx: typer.Context, profile_id: str, workspace: Workspace):
        invoke(ctx, 'runtime_status', workspace, profile_id=profile_id)

    @providers.command('models')
    def models(ctx: typer.Context, profile_id: str, workspace: Workspace, credential_prompt: bool = False):
        invoke(ctx, 'provider_models', workspace, profile_id=profile_id, credential_prompt=credential_prompt)

    @providers.command('test')
    def test(ctx: typer.Context, profile_id: str, workspace: Workspace, credential_prompt: bool = False):
        invoke(ctx, 'provider_test', workspace, profile_id=profile_id, credential_prompt=credential_prompt)

    @routing.command('get')
    def get_routing(ctx: typer.Context, workspace: Workspace):
        invoke(ctx, 'routing_get', workspace)

    @routing.command('update')
    def update_routing(ctx: typer.Context, file: Path, workspace: Workspace, expected_revision: str = typer.Option(...)):
        try:
            values = read_json_file(file)
        except (ValueError, OSError, AgentError):
            return fail(ctx, AgentError('validation_failed', 'Expected bounded routing JSON'))
        invoke(ctx, 'routing_update', workspace, values=values, expected_revision=expected_revision)
