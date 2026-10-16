"""Explicit provider and AI CLI commands. Credentials use hidden per-call input only."""
from pathlib import Path
from typing import Annotated

import typer

from dataforge.agent.contracts import AgentError
from dataforge.settings_service import read_json_file

Workspace = Annotated[str, typer.Option('--workspace', '-w')]


def register(app, invoke, fail):
    ai = typer.Typer(help='Explicit hash/job-pinned grounded assistance; preview operations are offline.')
    review = typer.Typer(help='Current diagnostic review candidates and bounded source previews.')
    results = typer.Typer(help='Durable results; detailed reads need source permission.')
    app.add_typer(ai, name='ai')
    ai.add_typer(review, name='review')
    ai.add_typer(results, name='results')
    providers = typer.Typer(help='Profiles, approved runtime references and explicit outbound tests.')
    routing = typer.Typer(help='Default, five task routes and ordered fallbacks.')
    credentials = typer.Typer(help='Status only; use --credential-prompt on a single operation for hidden input.')
    app.add_typer(providers, name='providers')
    providers.add_typer(routing, name='routing')
    providers.add_typer(credentials, name='credentials')

    @ai.command('chunks')
    def chunks(ctx: typer.Context, file_id: str, workspace: Workspace, first: int = typer.Option(...), last: int = typer.Option(...), task: str = typer.Option(...)):
        invoke(ctx, 'ai_chunks', workspace, file_id=file_id, first=first, last=last, task=task)

    @ai.command('request')
    def request(ctx: typer.Context, file_id: str, workspace: Workspace, first: int = typer.Option(...), last: int = typer.Option(...), task: str = typer.Option(...),
                expected_hash: str = typer.Option(...), expected_job: str = 'workspace', credential_prompt: bool = False):
        invoke(ctx, 'ai_request', workspace, file_id=file_id, first=first, last=last, task=task,
               expected_hash=expected_hash, expected_job=expected_job, credential_prompt=credential_prompt)

    @review.command('list')
    def review_list(ctx: typer.Context, workspace: Workspace):
        invoke(ctx, 'review_list', workspace)

    @review.command('preview')
    def review_preview(ctx: typer.Context, diagnostic_id: str, workspace: Workspace,
                       first: int = typer.Option(None), last: int = typer.Option(None)):
        invoke(ctx, 'review_preview', workspace, diagnostic_id=diagnostic_id, first=first, last=last)

    @review.command('request')
    def review_request(ctx: typer.Context, diagnostic_id: str, workspace: Workspace, expected_hash: str = typer.Option(...),
                       first: int = typer.Option(...), last: int = typer.Option(...), expected_job: str = 'workspace'):
        invoke(ctx, 'review_request', workspace, diagnostic_id=diagnostic_id, expected_hash=expected_hash,
               first=first, last=last, expected_job=expected_job)

    @results.command('list')
    def results_list(ctx: typer.Context, workspace: Workspace):
        invoke(ctx, 'ai_results', workspace)

    @results.command('get')
    def result_get(ctx: typer.Context, record_id: str, workspace: Workspace):
        invoke(ctx, 'ai_result', workspace, record_id=record_id)

    @ai.command('activity')
    def activity(ctx: typer.Context, workspace: Workspace):
        invoke(ctx, 'ai_activity', workspace)

    @ai.command('merge')
    def merge(ctx: typer.Context, record_id: str, workspace: Workspace, refresh: bool = True):
        invoke(ctx, 'ai_merge', workspace, record_id=record_id, refresh=refresh)

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
