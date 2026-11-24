"""CLI commands for authoring and exporting revision-bound Builder documents."""
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer

Workspace = Annotated[str, typer.Option('--workspace', '-w', help='Exact workspace ID.')]
Revision = Annotated[int, typer.Option('--revision', help='Expected current Builder revision.', min=0)]
Work = Annotated[str, typer.Option('--work-id', help='Exact ID of a named saved work.')]
Output = Annotated[Path | None, typer.Option('--output', help='New local artifact destination.')]


def register(app: typer.Typer, source: typer.Typer, invoke: Callable[..., Any]) -> None:
    """Register the Builder and source override entry points."""
    builder = typer.Typer(no_args_is_help=True, help='Author, save and export workspace lineage designs.')
    app.add_typer(builder, name='builder')

    @builder.command('inspect')
    def inspect(ctx: typer.Context, workspace: Workspace, view: str = 'tables', work_id: Work = '',
                table_id: str = '') -> None:
        """Page through tables, columns, links, folders or named works."""
        invoke(ctx, 'builder_inspect', workspace, view=view, work_id=work_id, table_id=table_id)

    @builder.command('apply')
    def apply(ctx: typer.Context, document: Path, workspace: Workspace, revision: Revision) -> None:
        """Apply or restore editable Builder JSON from an approved import root at the expected revision."""
        invoke(ctx, 'builder_apply', workspace, expected_revision=revision, path=str(document.resolve()))

    @builder.command('preview-schemas')
    def preview_schemas(ctx: typer.Context, paths: list[Path], workspace: Workspace, dialect: str | None = None) -> None:
        """Preview declared schemas from approved files and return a confirmation pin."""
        invoke(ctx, 'builder_schema_preview', workspace, paths=[str(path.resolve()) for path in paths], dialect=dialect)

    @builder.command('import-schemas')
    def import_schemas(ctx: typer.Context, paths: list[Path], workspace: Workspace, expected_pin: str = typer.Option(...),
                       dialect: str | None = None) -> None:
        """Add a previewed schema batch to the workspace without placing tables on the canvas."""
        invoke(ctx, 'builder_schema_import', workspace, paths=[str(path.resolve()) for path in paths], dialect=dialect,
               expected_pin=expected_pin)

    @builder.command('save-work')
    def save_work(ctx: typer.Context, workspace: Workspace, revision: Revision, name: str = '',
                  work_id: Work = '', clear: bool = False) -> None:
        """Save a named snapshot, optionally updating one by ID or clearing the canvas after saving."""
        invoke(ctx, 'builder_work_save', workspace, expected_revision=revision, name=name, work_id=work_id, clear=clear)

    @builder.command('load-work')
    def load_work(ctx: typer.Context, work_id: str, workspace: Workspace, revision: Revision) -> None:
        """Load a named saved design while retaining the workspace schema catalog."""
        invoke(ctx, 'builder_work_load', workspace, work_id=work_id, expected_revision=revision)

    @builder.command('import-work')
    def import_work(ctx: typer.Context, name: str, document: Path, workspace: Workspace) -> None:
        """Import editable JSON from an approved root as a separate named work."""
        invoke(ctx, 'builder_work_import', workspace, name=name, path=str(document.resolve()))

    @builder.command('export')
    def export(ctx: typer.Context, workspace: Workspace, kind: str = 'document', format: str = 'json',
               work_id: Work = '', table_id: Annotated[list[str] | None, typer.Option('--table-id')] = None,
               role: str | None = None, output: Output = None) -> None:
        """Export an editable document, graph, or selected schemas as a managed artifact."""
        invoke(ctx, 'builder_export', workspace, kind=kind, format=format, work_id=work_id, table_ids=table_id or None,
               role=role, download_to=output)

    @builder.command('preview-delete-tables')
    def preview_delete(ctx: typer.Context, table_ids: list[str], workspace: Workspace) -> None:
        """Preview the specific workspace tables and their affected relationships."""
        invoke(ctx, 'builder_delete_preview', workspace, table_ids=table_ids)

    @builder.command('delete-tables')
    def delete(ctx: typer.Context, table_ids: list[str], workspace: Workspace, revision: Revision,
               confirm: Annotated[str, typer.Option(help='Enter DELETE BUILDER TABLES.')] = '') -> None:
        """Permanently remove selected schemas as a local administrator, retaining named snapshots."""
        invoke(ctx, 'builder_delete', workspace, table_ids=table_ids, expected_revision=revision, confirm=confirm)

    @source.command('dialect')
    def dialect(ctx: typer.Context, file_id: str, workspace: Workspace,
                sql_dialect: Annotated[str | None, typer.Option('--dialect', help='SQLGlot name, empty for Generic SQL.')] = None) -> None:
        """Update an imported SQL file's dialect. Omit --dialect to use workspace settings again."""
        invoke(ctx, 'source_dialect_update', workspace, file_id=file_id, sql_dialect=sql_dialect)
