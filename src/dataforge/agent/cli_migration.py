"""CLI adapters for revision-pinned migration workflows."""
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, get_args

import typer

from dataforge.agent.contracts import AgentError
from dataforge.agent.migration import MigrationChange, MigrationPurpose, MigrationStage, MigrationView
from dataforge.settings_service import read_json_file

Workspace = Annotated[str, typer.Option('--workspace', '-w', help='Exact workspace ID.')]
Revision = Annotated[str, typer.Option('--revision', help='Exact migration revision ID.')]
Pin = Annotated[str, typer.Option('--expected-pin', help='Pin returned by the matching preview.')]
ArgumentsFile = Annotated[Path, typer.Argument(help='UTF-8 JSON object file, up to 1 MB.')]
Profile = Annotated[str, typer.Option('--profile', help='Saved provider profile ID.')]
Models = Annotated[list[str], typer.Option('--model', help='Exact output model ID. Repeat to select multiple.')]


# Typer choices use the same values as the shared service and MCP contracts.
View = StrEnum('View', get_args(MigrationView))
Change = StrEnum('Change', get_args(MigrationChange))
Purpose = StrEnum('Purpose', get_args(MigrationPurpose))
Stage = StrEnum('Stage', get_args(MigrationStage))
ViewOption = Annotated[View, typer.Option('--view', metavar='VIEW', help='Available views are ' + ', '.join(View) + '.')]
ChangeArgument = Annotated[Change, typer.Argument(metavar='OPERATION', show_choices=False,
                                                  help='Available operations are ' + ', '.join(Change) + '.')]


class ArtifactAnchor(StrEnum):
    generated = 'generated'
    source = 'source'
    annotated = 'annotated'


class ImageFormat(StrEnum):
    svg = 'svg'
    png = 'png'


def register(app: typer.Typer, invoke: Callable[..., Any], fail: Callable[..., Any]) -> None:
    """Register migration discovery, conversion, review, and handoff commands."""
    migration = typer.Typer(no_args_is_help=True, help='Convert retained workspace evidence into reviewed dbt projects.')
    app.add_typer(migration, name='migration')

    def load_object(ctx: typer.Context, path: Path) -> dict[str, Any]:
        try:
            if not path.is_file():
                raise OSError
            return read_json_file(path)
        except AgentError as exc:
            return fail(ctx, exc)
        except OSError:
            return fail(ctx, AgentError('invalid_path', 'Provide an existing regular UTF-8 JSON file'))

    @migration.command('targets')
    def targets(ctx: typer.Context, workspace: Workspace) -> None:
        """List supported output formats, warehouse targets and compatibility profiles."""
        invoke(ctx, 'migration_targets', workspace)

    @migration.command('list')
    def projects(ctx: typer.Context, workspace: Workspace) -> None:
        """List migration projects and their current revision IDs."""
        invoke(ctx, 'migration_list', workspace)

    @migration.command('preview')
    def preview(ctx: typer.Context, name: str, setup: ArgumentsFile, workspace: Workspace) -> None:
        """Preview frozen project inputs and get the pin required by create.

        Set analysis_run to latest or builder_revision to current to resolve those inputs during preview.
        """
        invoke(ctx, 'migration_preview', workspace, name=name, setup=load_object(ctx, setup))

    @migration.command('create')
    def create(ctx: typer.Context, name: str, setup: ArgumentsFile, workspace: Workspace, expected_pin: Pin) -> None:
        """Create a project from the exact inputs and name confirmed by a setup preview."""
        invoke(ctx, 'migration_create', workspace, name=name, setup=load_object(ctx, setup),
               expected_pin=expected_pin)

    @migration.command('inspect')
    def inspect(ctx: typer.Context, project_id: str, workspace: Workspace,
                revision: Annotated[str | None, typer.Option(help='Defaults to the current revision.')] = None,
                view: ViewOption = View.summary,
                item: Annotated[str | None, typer.Option(help='Exact item ID or comma-separated pilot models.')] = None,
                anchor: ArtifactAnchor | None = None,
                offset: Annotated[int, typer.Option(min=0, help='Character offset for an artifact excerpt.')] = 0,
                line: Annotated[int | None, typer.Option(min=1, help='Start at this line in the selected anchor.')] = None,
                finding: Annotated[str | None, typer.Option(help='Jump to the selected finding in the artifact.')] = None,
                limit: Annotated[int | None, typer.Option(min=1, max=500, help='Override the global page size.')] = None,
                cursor: Annotated[str | None, typer.Option(help='Resume from next_cursor for this view.')] = None) -> None:
        """Inspect a revision, page through reports, or read an anchored artifact excerpt."""
        if limit is not None:
            ctx.obj['options']['limit'] = limit
        if cursor is not None:
            ctx.obj['options']['cursor'] = cursor
        invoke(ctx, 'migration_inspect', workspace, project_id=project_id, revision_id=revision,
               view=view.value, item=item, anchor=anchor.value if anchor else None, offset=offset,
               line=line, finding=finding)

    @migration.command('convert')
    def convert(ctx: typer.Context, project_id: str, workspace: Workspace,
                expected_revision: Annotated[str, typer.Option('--expected-revision', '--revision',
                                                               help='Current revision ID required for conversion.')],
                reconvert: Annotated[bool, typer.Option(help='Regenerate an already converted project.')] = False,
                plan_only: Annotated[bool, typer.Option(help='Prepare an AI source plan without static drafts.')] = False,
                background: Annotated[bool, typer.Option(help='Return a job ID. Poll with jobs status --wait.')] = False) -> None:
        """Run static conversion against the project's confirmed revision."""
        invoke(ctx, 'migration_convert', workspace, background=background, project_id=project_id,
               expected_revision=expected_revision, reconvert=reconvert, plan_only=plan_only)

    @migration.command('change')
    def change(ctx: typer.Context, project_id: str, operation: ChangeArgument, arguments: ArgumentsFile,
               workspace: Workspace, revision: Revision) -> None:
        """Apply a revision-pinned change, evidence import, or review operation.

        For apply, include expected_pin from edit-preview and provide proposal or proposal_path.
        Import evidence as inline manifest, run_results, csv or schema content, or supply
        manifest_path, results_path or path. File paths must be under an allowed root.
        """
        invoke(ctx, 'migration_change', workspace, project_id=project_id, revision_id=revision,
               operation=operation.value, arguments=load_object(ctx, arguments))

    @migration.command('edit-preview')
    def edit_preview(ctx: typer.Context, project_id: str, arguments: ArgumentsFile,
                     workspace: Workspace, revision: Revision) -> None:
        """Preview manual replacements, SAS ordering, or an existing AI proposal.

        Provide replacements and rationale (optionally scopes), model and order, or proposal
        or proposal_path under an allowed root. Use mapping_csv or mapping_path for a mapping preview.
        """
        invoke(ctx, 'migration_edit_preview', workspace, project_id=project_id, revision_id=revision,
               arguments=load_object(ctx, arguments))

    @migration.command('ai-preview')
    def ai_preview(ctx: typer.Context, project_id: str, workspace: Workspace, revision: Revision,
                   profile: Profile, model: Models, purpose: Annotated[Purpose, typer.Option()],
                   message: str = '', dependencies: bool = False,
                   offset: Annotated[int, typer.Option(min=0, help='Resume exact disclosure from next_offset.')] = 0) -> None:
        """Review exact scoped provider disclosure and get the request pin offline."""
        invoke(ctx, 'migration_ai_preview', workspace, project_id=project_id, revision_id=revision,
               profile_id=profile, models=model, purpose=purpose.value, message=message,
               dependencies=dependencies, offset=offset)

    @migration.command('ai-request')
    def ai_request(ctx: typer.Context, project_id: str, workspace: Workspace, revision: Revision,
                   profile: Profile, model: Models, purpose: Annotated[Purpose, typer.Option()],
                   expected_pin: Pin, message: str = '', dependencies: bool = False) -> None:
        """Send the confirmed AI request using the selected saved provider profile."""
        invoke(ctx, 'migration_ai_request', workspace, project_id=project_id, revision_id=revision,
               profile_id=profile, models=model, purpose=purpose.value, message=message, dependencies=dependencies,
               expected_pin=expected_pin)

    @migration.command('stage-preview')
    def stage_preview(ctx: typer.Context, project_id: str, source_id: str, stage: Stage,
                      workspace: Workspace, revision: Revision, profile: Profile, feedback: str = '',
                      static_reference: bool = False,
                      offset: Annotated[int, typer.Option(min=0, help='Resume disclosure from next_offset.')] = 0) -> None:
        """Preview the next disclosure for a source file and stage."""
        invoke(ctx, 'migration_stage_preview', workspace, project_id=project_id, revision_id=revision, profile_id=profile,
               source_id=source_id, stage=stage.value, feedback=feedback, static_reference=static_reference, offset=offset)

    @migration.command('stage-run')
    def stage_run(ctx: typer.Context, project_id: str, source_id: str, stage: Stage,
                  workspace: Workspace, revision: Revision, profile: Profile, expected_pin: Pin,
                  feedback: str = '', static_reference: bool = False,
                  background: Annotated[bool, typer.Option(help='Queue a cancellable stage job.')] = False) -> None:
        """Run a confirmed file-scoped stage and save its candidate evidence."""
        invoke(ctx, 'migration_stage_request', workspace, background=background, project_id=project_id, revision_id=revision, profile_id=profile,
               source_id=source_id, stage=stage.value, feedback=feedback, static_reference=static_reference,
               expected_pin=expected_pin)

    @migration.command('export')
    def export(ctx: typer.Context, project_id: str, workspace: Workspace, revision: Revision,
               reviewed: Annotated[bool, typer.Option(help='Require reviewed handoff checks.')] = False,
               image_format: ImageFormat | None = None, workbook: bool = False,
               pilot: Annotated[list[str] | None, typer.Option(help='Reviewed pilot model ID. Repeat for multiple.')] = None,
               destination: Annotated[Path | None, typer.Option(help='Download to a new local ZIP file.')] = None,
               include_sources: Annotated[bool, typer.Option(help='Include full retained sources as inert text.')] = False) -> None:
        """Create a revision-pinned draft, reviewed, or pilot dbt bundle."""
        invoke(ctx, 'migration_export', workspace, project_id=project_id, revision_id=revision,
               reviewed=reviewed or bool(pilot), image_format=image_format.value if image_format else None,
               workbook=workbook, pilot=pilot or None, include_sources=include_sources, download_to=destination)
