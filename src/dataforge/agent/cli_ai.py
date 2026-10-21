"""Explicit provider and AI CLI commands. Credentials use hidden per-call input only."""
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer

from dataforge.agent.contracts import AgentError
from dataforge.settings_service import read_json_file

Workspace = Annotated[str, typer.Option('--workspace', '-w')]


def register(app: typer.Typer, invoke: Callable[..., Any], fail: Callable[..., Any]) -> None:
    """Register AI, review, result, provider, and routing CLI commands.

    Args:
        app: Root Typer application receiving the command groups.
        invoke: Dispatcher for agent operations.
        fail: Sanitized CLI error handler.
    """
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
    def chunks(ctx: typer.Context, file_id: str, workspace: Workspace, first: int = typer.Option(...), last: int = typer.Option(...), task: str = typer.Option(...)) -> None:
        """Preview selected statement chunks without contacting a provider.

        Args:
            ctx: Typer command context.
            file_id: Source file identifier.
            workspace: Workspace identifier.
            first: First chunk number in the requested range.
            last: Last chunk number in the requested range.
            task: AI task type used to calculate the preview budget.
        """
        invoke(ctx, 'ai_chunks', workspace, file_id=file_id, first=first, last=last, task=task)

    @ai.command('request')
    def request(ctx: typer.Context, file_id: str, workspace: Workspace, first: int = typer.Option(...), last: int = typer.Option(...), task: str = typer.Option(...),
                expected_hash: str = typer.Option(...), expected_job: str = 'workspace', credential_prompt: bool = False) -> None:
        """Request AI assistance for a hash- and job-pinned source range.

        Args:
            ctx: Typer command context.
            file_id: Source file identifier.
            workspace: Workspace identifier.
            first: First chunk number in the requested range.
            last: Last chunk number in the requested range.
            task: AI task type.
            expected_hash: Expected source content hash.
            expected_job: Expected analysis job identifier.
            credential_prompt: Whether to request hidden credentials for this call.
        """
        invoke(ctx, 'ai_request', workspace, file_id=file_id, first=first, last=last, task=task,
               expected_hash=expected_hash, expected_job=expected_job, credential_prompt=credential_prompt)

    @review.command('list')
    def review_list(ctx: typer.Context, workspace: Workspace) -> None:
        """List current unresolved diagnostic review candidates.

        Args:
            ctx: Typer command context.
            workspace: Workspace identifier.
        """
        invoke(ctx, 'review_list', workspace)

    @review.command('preview')
    def review_preview(ctx: typer.Context, diagnostic_id: str, workspace: Workspace,
                       first: int = typer.Option(None), last: int = typer.Option(None)) -> None:
        """Preview bounded source context for one diagnostic.

        Args:
            ctx: Typer command context.
            diagnostic_id: Identifier of the diagnostic to inspect.
            workspace: Workspace identifier.
            first: Optional first source line to include.
            last: Optional last source line to include.
        """
        invoke(ctx, 'review_preview', workspace, diagnostic_id=diagnostic_id, first=first, last=last)

    @review.command('request')
    def review_request(ctx: typer.Context, diagnostic_id: str, workspace: Workspace, expected_hash: str = typer.Option(...),
                       first: int = typer.Option(...), last: int = typer.Option(...), expected_job: str = 'workspace') -> None:
        """Request AI review for the explicitly selected diagnostic context.

        Args:
            ctx: Typer command context.
            diagnostic_id: Identifier of the diagnostic to review.
            workspace: Workspace identifier.
            expected_hash: Expected source content hash.
            first: First source line in the selected range.
            last: Last source line in the selected range.
            expected_job: Expected analysis job identifier.
        """
        invoke(ctx, 'review_request', workspace, diagnostic_id=diagnostic_id, expected_hash=expected_hash,
               first=first, last=last, expected_job=expected_job)

    @results.command('list')
    def results_list(ctx: typer.Context, workspace: Workspace) -> None:
        """List saved AI result summaries for a workspace.

        Args:
            ctx: Typer command context.
            workspace: Workspace identifier.
        """
        invoke(ctx, 'ai_results', workspace)

    @results.command('get')
    def result_get(ctx: typer.Context, record_id: str, workspace: Workspace) -> None:
        """Retrieve one saved AI result by record identifier.

        Args:
            ctx: Typer command context.
            record_id: Saved AI result identifier.
            workspace: Workspace identifier.
        """
        invoke(ctx, 'ai_result', workspace, record_id=record_id)

    @results.command('export')
    def export_result(ctx: typer.Context, record_id: str, workspace: Workspace) -> None:
        """Create a JSON artifact for a saved AI result.

        Args:
            ctx: Typer command context.
            record_id: Saved AI result identifier.
            workspace: Workspace identifier.
        """
        invoke(ctx, 'artifact_create', workspace, kind='ai-result', format='json', selection={'record_id': record_id})

    @ai.command('activity')
    def activity(ctx: typer.Context, workspace: Workspace) -> None:
        """Show AI request usage and activity summaries.

        Args:
            ctx: Typer command context.
            workspace: Workspace identifier.
        """
        invoke(ctx, 'ai_activity', workspace)

    @ai.command('merge')
    def merge(ctx: typer.Context, record_id: str, workspace: Workspace, refresh: bool = True) -> None:
        """Merge validated lineage claims from a saved AI result.

        Args:
            ctx: Typer command context.
            record_id: Saved result identifier.
            workspace: Workspace identifier.
            refresh: Whether to refresh the graph after a successful merge.
        """
        invoke(ctx, 'ai_merge', workspace, record_id=record_id, refresh=refresh)

    @providers.command('list')
    def list_profiles(ctx: typer.Context, workspace: Workspace) -> None:
        """List configured provider profiles without secret values.

        Args:
            ctx: Typer command context.
            workspace: Workspace identifier.
        """
        invoke(ctx, 'providers_list', workspace)

    @providers.command('get')
    def get_profile(ctx: typer.Context, profile_id: str, workspace: Workspace) -> None:
        """Show a provider profile by identifier.

        Args:
            ctx: Typer command context.
            profile_id: Provider profile identifier.
            workspace: Workspace identifier.
        """
        invoke(ctx, 'provider_get', workspace, profile_id=profile_id)

    @providers.command('save')
    def save(ctx: typer.Context, file: Path, workspace: Workspace, expected_revision: str = typer.Option(...), profile_id: str = '') -> None:
        """Save bounded provider profile JSON using optimistic revision checking.

        Args:
            ctx: Typer command context.
            file: Path to the profile JSON document.
            workspace: Workspace identifier.
            expected_revision: Current profile revision required for the update.
            profile_id: Optional profile identifier for editing an existing profile.
        """
        try:
            profile = read_json_file(file)
        except (ValueError, OSError, AgentError):
            return fail(ctx, AgentError('validation_failed', 'Expected bounded profile JSON without secret values'))
        invoke(ctx, 'provider_save', workspace, profile=profile, expected_revision=expected_revision, profile_id=profile_id)

    @providers.command('remove')
    def remove(ctx: typer.Context, profile_id: str, workspace: Workspace, expected_revision: str = typer.Option(...)) -> None:
        """Remove a provider profile after checking its current revision.

        Args:
            ctx: Typer command context.
            profile_id: Provider profile identifier.
            workspace: Workspace identifier.
            expected_revision: Current revision required for the update.
        """
        invoke(ctx, 'provider_remove', workspace, profile_id=profile_id, expected_revision=expected_revision)

    @credentials.command('status')
    def status(ctx: typer.Context, profile_id: str, workspace: Workspace) -> None:
        """Show runtime credential-reference status for a provider profile.

        Args:
            ctx: Typer command context.
            profile_id: Provider profile identifier.
            workspace: Workspace identifier.
        """
        invoke(ctx, 'runtime_status', workspace, profile_id=profile_id)

    @providers.command('models')
    def models(ctx: typer.Context, profile_id: str, workspace: Workspace, credential_prompt: bool = False) -> None:
        """Discover available models for a provider profile.

        Args:
            ctx: Typer command context.
            profile_id: Provider profile identifier.
            workspace: Workspace identifier.
            credential_prompt: Whether to request hidden credentials for this call.
        """
        invoke(ctx, 'provider_models', workspace, profile_id=profile_id, credential_prompt=credential_prompt)

    @providers.command('test')
    def test(ctx: typer.Context, profile_id: str, workspace: Workspace, credential_prompt: bool = False) -> None:
        """Test an outbound provider connection using the selected profile.

        Args:
            ctx: Typer command context.
            profile_id: Provider profile identifier.
            workspace: Workspace identifier.
            credential_prompt: Whether to request hidden credentials for this operation.
        """
        invoke(ctx, 'provider_test', workspace, profile_id=profile_id, credential_prompt=credential_prompt)

    @routing.command('get')
    def get_routing(ctx: typer.Context, workspace: Workspace) -> None:
        """Show default and task-specific model routes.

        Args:
            ctx: Typer command context.
            workspace: Workspace identifier.
        """
        invoke(ctx, 'routing_get', workspace)

    @routing.command('update')
    def update_routing(ctx: typer.Context, file: Path, workspace: Workspace, expected_revision: str = typer.Option(...)) -> None:
        """Update model routing from bounded JSON with revision checking.

        Args:
            ctx: Typer command context.
            file: Path to the routing JSON document.
            workspace: Workspace identifier.
            expected_revision: Current routing revision required for the update.
        """
        try:
            values = read_json_file(file)
        except (ValueError, OSError, AgentError):
            return fail(ctx, AgentError('validation_failed', 'Expected bounded routing JSON'))
        invoke(ctx, 'routing_update', workspace, values=values, expected_revision=expected_revision)
