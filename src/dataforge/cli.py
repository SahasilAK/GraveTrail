"""GraveTrail automation CLI; does not import or start Streamlit."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

import duckdb
import typer

from dataforge.agent.cli_ai import register as register_ai
from dataforge.agent.cli_dbt import register as register_dbt
from dataforge.agent.cli_reports import register as register_reports
from dataforge.agent.cli_reports import register_maintenance
from dataforge.agent.cli_settings import register as register_settings
from dataforge.agent.cli_settings import register_application
from dataforge.agent.contracts import (
    AccessPolicy,
    AgentError,
    AgentSettings,
    QueryOptions,
    compact,
    job_settings,
)
from dataforge.agent.jobs import TERMINAL, Jobs, status_result
from dataforge.agent.service import AgentService
from dataforge.launcher import application_root, default_home
from dataforge.store import Store

app = typer.Typer(no_args_is_help=True, help="Local evidence-backed SQL/SAS analysis and agent access.")
workspace_app = typer.Typer(help="List, create and summarize workspaces.")
lineage_app = typer.Typer(help="Build and query stored lineage.")
columns_app = typer.Typer(help="Direct source-column usage and transformation tracing.")
source_app = typer.Typer(help="Source inventory, literal search and explicit evidence retrieval.")
assets_app = typer.Typer(help="Resolve asset names to stable IDs.")
impact_app = typer.Typer(help="Stored downstream change impact.")
jobs_app = typer.Typer(help="Persisted job status and results.")
exports_app = typer.Typer(help="Bounded lineage exports.")
batch_app = typer.Typer(help="Aggregate-budget lineage queries.")
cleanup_app = typer.Typer(help="Preview and explicitly confirm workspace cleanup.")
maintenance_app = typer.Typer(help="Local database inspection, backup, checkpoint and safe restore.")
for name, group in [("workspace", workspace_app), ("lineage", lineage_app), ("columns", columns_app),
                    ("source", source_app), ("assets", assets_app), ("impact", impact_app),
                    ("jobs", jobs_app), ("export", exports_app), ("batch", batch_app),
                    ('cleanup', cleanup_app), ('maintenance', maintenance_app)]:
    app.add_typer(group, name=name)

Workspace = Annotated[str, typer.Option("--workspace", "-w", help="Exact workspace ID.")]


@app.callback()
def configure(ctx: typer.Context,
              home: Path = typer.Option(None, help="Runtime home; defaults to DATAFORGE_HOME or .dataforge."),
              json_output: bool = typer.Option(False, "--json", help="Compact structured JSON output."),
              quiet: bool = typer.Option(False, "--quiet", "-q"),
              allow_write: bool = typer.Option(False, help="Explicitly authorize mutations for this launch."),
              allow_config_write: bool = typer.Option(False),
              allow_llm: bool = typer.Option(False),
              allowed_llm_origin: list[str] = typer.Option(None),
              allowed_credential_ref: list[str] = typer.Option(None),
              allow_application_config: bool = typer.Option(False),
              allow_admin: bool = typer.Option(False, help="Local CLI administration only; cannot be used by MCP."),
              allowed_workspace: list[str] = typer.Option(None, help="Restrict to these workspace IDs; repeatable."),
              allowed_root: list[Path] = typer.Option(None, help="Authorized import root; repeatable."),
              limit: int = typer.Option(50, min=1, max=500), cursor: str = typer.Option(None),
              max_depth: int = typer.Option(15, min=1, max=30),
              max_items: int = typer.Option(2000, min=1, max=20000),
              max_chars: int = typer.Option(12000, min=512, max=100000),
              detail: str = typer.Option("summary", help="summary, standard or detailed."),
              collapse_temporary: bool = typer.Option(None, "--collapse-temporary/--keep-temporary"),
              output: Path = typer.Option(None, help="Write JSON to a new local file, without overwriting.")) -> None:
    """Build the runtime context from command-line options.

    Args:
        ctx: Typer context receiving the resolved runtime configuration.
        home: Optional runtime home directory.
        json_output: Whether to emit structured JSON.
        quiet: Whether to suppress successful output.
        allow_write: Whether to authorize mutations.
        allow_config_write: Whether to authorize configuration changes.
        allow_llm: Whether to authorize language model calls.
        allowed_llm_origin: Allowed language model origins.
        allowed_credential_ref: Allowed credential references.
        allow_application_config: Whether to allow application configuration changes.
        allow_admin: Whether to allow local administrative operations.
        allowed_workspace: Optional workspace allowlist.
        allowed_root: Authorized import roots.
        limit: Default result page size.
        cursor: Optional initial pagination cursor.
        max_depth: Maximum lineage depth.
        max_items: Maximum result item count.
        max_chars: Maximum result text size.
        detail: Default response detail level.
        collapse_temporary: Whether temporary assets are collapsed.
        output: Optional new file for JSON output."""
    roots = allowed_root or [Path(p) for p in os.environ.get("DATAFORGE_ALLOWED_ROOTS", "").split(os.pathsep) if p]
    ctx.obj = {"home": (home or default_home(source=application_root().name != '_app' and not getattr(sys, 'frozen', False))).resolve(),
               "json": json_output, "quiet": quiet, "output": output,
               "policy": AccessPolicy(allow_write, tuple(allowed_workspace) if allowed_workspace else None,
                                      tuple(str(p.resolve()) for p in roots),
                                      allow_config_write, allow_llm, tuple(allowed_llm_origin or ()),
                                      tuple(allowed_credential_ref or ()), allow_application_config, allow_admin),
               "options": {"limit": limit, "cursor": cursor, "max_depth": max_depth,
                           "max_items": max_items, "max_chars": max_chars, "detail_level": detail,
                           "collapse_temporary": collapse_temporary}}


def emit(ctx: typer.Context, result: dict[str, Any]) -> None:
    """Render a result according to the configured output options.

    Args:
        ctx: Typer context containing output preferences.
        result: Structured service result to display or save.

    Raises:
        AgentError: If the operation is invalid, unauthorized, or unavailable."""
    config = ctx.obj
    text = compact(result)
    if config["output"]:
        try:
            with config["output"].open("x", encoding="utf-8") as stream:
                stream.write(text + "\n")
        except OSError:
            raise AgentError("io_error", "Output file already exists or cannot be created") from None
    if config["quiet"] and "error" not in result:
        return
    if config["json"] or "error" in result:
        typer.echo(text)
    elif "items" in result:
        for item in result["items"]:
            typer.echo("  ".join(f"{k}: {v}" for k, v in item.items()))
        typer.echo(f"{result['count']} of {result['total']} records; complete={result['complete']}")
        if result.get("next_cursor"):
            typer.echo("Next cursor: " + result["next_cursor"])
    else:
        for key, value in result.items():
            typer.echo(f"{key}: {compact(value) if isinstance(value, (dict, list)) else value}")


@app.command()
def capabilities(ctx: typer.Context, workspace: str = typer.Option('')) -> None:
    """Discover permitted operations and explicit policy restrictions; follow next_cursor.

    Args:
        ctx: Typer command context.
        workspace: Workspace targeted by the command."""
    invoke(ctx, 'capabilities', workspace)


def fail(ctx: typer.Context, exc: AgentError) -> None:
    # Errors never write an output artifact or include exception internals such as SQL/paths.
    """Display a sanitized agent error and exit with its CLI status code.

    Args:
        ctx: Typer command context.
        exc: Agent error to report.

    Raises:
        typer.Exit: To exit with the mapped command status."""
    typer.echo(compact(exc.response()))
    code = {"forbidden": 3, "not_found": 4, "ambiguous_asset": 4, "busy": 5,
            "storage_busy": 5, "io_error": 6}.get(exc.code, 2)
    raise typer.Exit(code)


def invoke(ctx: typer.Context, action: str, workspace_id: str="", background: bool=False, **arguments: Any) -> None:
    """Run an agent operation, manage resources, and render its result.

    Args:
        ctx: Typer context containing policy, home, and query options.
        action: Agent service action name.
        workspace_id: Workspace targeted by the action, when applicable.
        background: Whether to queue the action as a detached job.
        **arguments: Action-specific arguments passed to the service.

    Raises:
        AgentError: If the operation is invalid, unauthorized, or unavailable.
        typer.Exit: To exit with the mapped command status."""
    store = service = None
    try:
        config = ctx.obj
        download_to = arguments.pop('download_to', None)
        if download_to is not None and (download_to.exists() or download_to.is_symlink() or not download_to.parent.is_dir()):
            raise AgentError('invalid_path', 'Output must be a new file in an existing directory')
        if action in {"job", 'job_cancel'}:
            if not config["policy"].permits(workspace_id):
                raise AgentError("forbidden", "Workspace is not authorized")
            jobs = Jobs(config["home"])
            try:
                job_id = arguments["job_id"]
                deadline = time.monotonic() + 300
                while True:
                    record = jobs.read(job_id, workspace_id, private=True)
                    result = cli_job_status(config, workspace_id, record)
                    if action == 'job_cancel':
                        settings = job_settings(config['home'], workspace_id, record)
                        if not config['policy'].allow_write or not settings.allow_write:
                            raise AgentError('forbidden', 'Cancellation requires explicit workspace write access')
                        if record['operation'] not in {'analyze', 'ai_analysis'}:
                            raise AgentError('invalid_argument', 'This job does not support cancellation')
                        result = jobs.cancel(job_id, workspace_id)
                        break
                    if not arguments.get("wait") or result["status"] in TERMINAL:
                        break
                    if time.monotonic() >= deadline:
                        raise AgentError("busy", "Job is still running; poll job_id", job_id=job_id)
                    time.sleep(.1)
            finally:
                jobs.close()
        else:
            store = Store(config["home"])
            from dataforge.ai_analysis_store import recover_interrupted_runs
            recover_interrupted_runs(store)
            service = AgentService(store, config["policy"])
            if arguments.pop('credential_prompt', False):
                from dataforge.connections import RuntimeConnections
                from dataforge.provider_service import authorize_provider, get_profile
                profile_id = arguments.get('profile_id', '')
                if action == 'ai_request':
                    profile_id = store.setting(workspace_id, 'task_models', {}).get(arguments['task']) or store.setting(workspace_id, 'default_profile', '')
                profile = get_profile(store, workspace_id, profile_id)
                service._workspace(workspace_id, write=True)
                authorize_provider(store, service.policy, workspace_id, profile)
                manager = RuntimeConnections()
                manager.register('DATAFORGE_RUNTIME_CREDENTIAL', typer.prompt('Runtime credential (this invocation only)', hide_input=True))
                service.runtime_connections[(workspace_id, profile_id)] = manager
                service.runtime_profiles[(workspace_id, profile_id)] = profile.model_dump_json()
            if background:
                service._workspace(workspace_id, write=True)
                if action == 'analyze' and arguments.get('mode', 'parser') != 'parser':
                    service._workspace(workspace_id, write=True, source=True)
                    service.policy.require('network')
                QueryOptions.model_validate(config["options"])
                if action == "ingest":
                    config["policy"].import_path(arguments["path"])
                record = service.jobs.create(workspace_id, action,
                    AgentSettings.from_store(store, workspace_id).model_dump())
                # A detached worker opens DuckDB only after this CLI releases its connection.
                record["request"] = {"arguments": arguments, "policy": asdict(config['policy'])}
                service.jobs.write(record)
                service.audit(workspace_id, action, "queued")
                service.close()
                store.close()
                service = store = None
                flags = (subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS) if os.name == "nt" else 0
                worker_command = [sys.executable, '--worker'] if getattr(sys, 'frozen', False) else [sys.executable, '-m', 'dataforge.agent.worker']
                subprocess.Popen([*worker_command, str(config["home"]), record["job_id"]], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, creationflags=flags, start_new_session=os.name != "nt")
                result = {"job_id": record["job_id"], "status": "queued"}
            else:
                result = service.call(action, workspace_id, options=config["options"], **arguments)
                if download_to is not None:
                    import base64
                    import hashlib
                    artifact_id = result['artifact_id']
                    digest = hashlib.sha256()
                    offset = 0
                    with download_to.open('xb') as stream:
                        while True:
                            chunk = service.call('artifact_read', workspace_id, options=config['options'], artifact_id=artifact_id, offset=offset)
                            data = base64.b64decode(chunk['data'])
                            stream.write(data)
                            digest.update(data)
                            offset = chunk['next_offset']
                            if chunk['complete']:
                                break
                    if offset != chunk['bytes'] or digest.hexdigest() != chunk['sha256']:
                        raise AgentError('conflict', 'Downloaded artifact checksum failed')
                    result = {'artifact_id': artifact_id, 'destination': str(download_to), 'bytes': offset,
                              'sha256': digest.hexdigest(), 'complete': chunk['artifact_complete']}
                if action in {"ingest", "analyze"}:
                    service.jobs.wait(result["job_id"], workspace_id)
                    result = service.job_status(workspace_id, result["job_id"], config["options"])
        emit(ctx, result)
        if result.get("status") in {"failed", "interrupted"}:
            raise typer.Exit(6)
    except AgentError as exc:
        fail(ctx, exc)
    except duckdb.Error:
        fail(ctx, AgentError("storage_busy", "Cannot open storage. DuckDB needs one owning process per home; stop the other owner or use --home."))
    except (ValueError, TypeError):
        fail(ctx, AgentError("invalid_argument", "Invalid arguments; check command help"))
    except OSError:
        fail(ctx, AgentError("io_error", "Local operation failed; check file access"))
    finally:
        if service:
            service.close()
        if store:
            store.close()


def cli_job_status(config: dict[str, Any], workspace: str, record: dict[str, Any]) -> dict[str, Any]:
    """Build a job status response using stored or job-snapshot settings.

    Args:
        config: CLI runtime configuration.
        workspace: Workspace owning the job.
        record: Persisted job record.

    Returns:
        Bounded status result for the job.

    Raises:
        AgentError: If the operation is invalid, unauthorized, or unavailable."""
    try:
        store = Store(config["home"])
    except duckdb.Error:
        settings = job_settings(config["home"], workspace, record)
    else:
        try:
            if not store.rows("SELECT 1 FROM workspaces WHERE workspace_id=?", [workspace]):
                raise AgentError("not_found", "Workspace does not exist")
            settings = AgentSettings.from_store(store, workspace)
        finally:
            store.close()
    if not settings.enabled:
        raise AgentError("forbidden", "Agent access is disabled for this workspace")
    values = dict(config["options"])
    values["max_chars"] = min(values["max_chars"], settings.max_chars)
    return status_result(record, QueryOptions.model_validate(values))


@workspace_app.command("list")
def workspaces(ctx: typer.Context, query: str = "") -> None:
    """List workspaces matching an optional query.

    Args:
        ctx: Typer command context.
        query: Search query or filter."""
    invoke(ctx, "workspaces", query=query)


@workspace_app.command("create")
def create_workspace(ctx: typer.Context, name: str, description: str = "") -> None:
    """Create a workspace with the supplied name and description.

    Args:
        ctx: Typer command context.
        name: Name.
        description: Description."""
    invoke(ctx, "create_workspace", name=name, description=description)


@workspace_app.command("summary")
def workspace_summary(ctx: typer.Context, workspace: Workspace) -> None:
    """Show a summary of the selected workspace.

    Args:
        ctx: Typer command context.
        workspace: Workspace targeted by the command."""
    invoke(ctx, "summary", workspace)


@app.command("ingest")
def ingest(ctx: typer.Context, path: Path, workspace: Workspace, extensions: str = "sql,sas,csv", background: bool = False,
           source_kind: str = 'files', dbt_mode: str = 'source', artifact_path: list[str] = typer.Option(None),
           include_packages: bool = False) -> None:
    """Import supported source files from a directory.

    Args:
        ctx: Typer command context.
        path: Source directory to import.
        workspace: Workspace targeted by the command.
        extensions: Comma-separated file extensions to include.
        background: Whether to queue work as a background job."""
    invoke(ctx, "ingest", workspace, background, path=str(path.resolve()), extensions=extensions.split(","),
        source_kind=source_kind, dbt_options={'mode': dbt_mode, 'artifact_paths': artifact_path or [],
                                            'include_packages': include_packages} if source_kind == 'dbt' else None)


@lineage_app.command("build")
def build(ctx: typer.Context, workspace: Workspace, force: bool = False,
          file_id: list[str] = typer.Option(None), background: bool = False, mode: str = 'parser',
          additional_ai_review: bool = False, refresh_ai: bool = False,
          max_provider_attempts: int | None = None, max_output_tokens_total: int | None = None, max_seconds: int | None = None, resume_run_id: str = '', retry_unknown: bool = False,
          max_files_per_request: int | None = None, max_parallel_requests: int | None = None, max_context_chars: int | None = None,
          auto_continue: bool = True, project_max_provider_attempts: int | None = None,
          project_max_output_tokens_total: int | None = None, project_max_seconds: int | None = None) -> None:
    """Build lineage for a workspace or selected source files.

    Args:
        ctx: Typer command context.
        workspace: Workspace targeted by the command.
        force: Whether to force a fresh analysis.
        file_id: Optional source file identifier.
        background: Whether to queue work as a background job."""
    invoke(ctx, "analyze", workspace, background, force=force, file_ids=file_id, mode=mode,
           additional_ai_review=additional_ai_review, refresh_ai=refresh_ai,
           max_provider_attempts=max_provider_attempts, max_output_tokens_total=max_output_tokens_total,
           max_seconds=max_seconds, resume_run_id=resume_run_id, retry_unknown=retry_unknown,
           max_files_per_request=max_files_per_request, max_parallel_requests=max_parallel_requests, max_context_chars=max_context_chars,
           auto_continue=auto_continue, project_max_provider_attempts=project_max_provider_attempts,
           project_max_output_tokens_total=project_max_output_tokens_total, project_max_seconds=project_max_seconds)


@lineage_app.command('preview')
def preview_build(ctx: typer.Context, workspace: Workspace, mode: str = 'ai',
                  file_id: list[str] = typer.Option(None), additional_ai_review: bool = False,
                  max_provider_attempts: int | None = None, max_output_tokens_total: int | None = None, max_seconds: int | None = None, resume_run_id: str = '', retry_unknown: bool = False,
          max_files_per_request: int | None = None, max_parallel_requests: int | None = None, max_context_chars: int | None = None,
          auto_continue: bool = True, project_max_provider_attempts: int | None = None,
          project_max_output_tokens_total: int | None = None, project_max_seconds: int | None = None) -> None:
    """Preview analysis inputs, disclosure, and provider budgets without running analysis.

    Args:
        ctx: Typer command context.
        workspace: Workspace targeted by the command.
        mode: Parser-only or hybrid analysis mode.
        file_id: Optional source file identifiers to include.
        additional_ai_review: Whether to include diagnostic review capacity.
        max_provider_attempts: Optional provider call ceiling.
        max_output_tokens_total: Optional reserved output token ceiling.
        max_seconds: Optional execution time ceiling.
        resume_run_id: Optional interrupted run to resume.
        retry_unknown: Whether to retry unresolved units.
    """
    invoke(ctx, 'analysis_preview', workspace, mode=mode, file_ids=file_id,
           additional_ai_review=additional_ai_review, max_provider_attempts=max_provider_attempts,
           max_output_tokens_total=max_output_tokens_total, max_seconds=max_seconds, resume_run_id=resume_run_id, retry_unknown=retry_unknown,
           max_files_per_request=max_files_per_request, max_parallel_requests=max_parallel_requests, max_context_chars=max_context_chars,
           auto_continue=auto_continue, project_max_provider_attempts=project_max_provider_attempts,
           project_max_output_tokens_total=project_max_output_tokens_total, project_max_seconds=project_max_seconds)


@lineage_app.command('analysis-report')
def project_report(ctx: typer.Context, workspace: Workspace, run_id: str | None = None) -> None:
    """Display the saved project analysis report for a workspace.

    Args:
        ctx: Typer command context.
        workspace: Workspace targeted by the command.
        run_id: Optional saved analysis run identifier.
    """
    invoke(ctx, 'analysis_report', workspace, run_id=run_id)


@jobs_app.command('cancel')
def cancel_analysis_job(ctx: typer.Context, workspace: Workspace, job_id: str) -> None:
    """Request cancellation of an active analysis job.

    Args:
        ctx: Typer command context.
        workspace: Workspace targeted by the command.
        job_id: Identifier of the queued or running job.
    """
    invoke(ctx, 'job_cancel', workspace, job_id=job_id)


@lineage_app.command("upstream")
def upstream(ctx: typer.Context, asset: str, workspace: Workspace) -> None:
    """Query upstream lineage for an asset.

    Args:
        ctx: Typer command context.
        asset: Asset name or identifier.
        workspace: Workspace targeted by the command."""
    invoke(ctx, "lineage", workspace, asset=asset, direction="upstream")


@lineage_app.command("downstream")
def downstream(ctx: typer.Context, asset: str, workspace: Workspace) -> None:
    """Query downstream lineage for an asset.

    Args:
        ctx: Typer command context.
        asset: Asset name or identifier.
        workspace: Workspace targeted by the command."""
    invoke(ctx, "lineage", workspace, asset=asset, direction="downstream")


@assets_app.command("search")
def search_assets(ctx: typer.Context, workspace: Workspace, query: str = "") -> None:
    """Search workspace assets by name or identifier.

    Args:
        ctx: Typer command context.
        workspace: Workspace targeted by the command.
        query: Search query or filter."""
    invoke(ctx, "assets", workspace, query=query)


@columns_app.command("usage")
def columns(ctx: typer.Context, asset: str, workspace: Workspace, column_query: str = '',
            usage_type: str = '', file_id: str = '', group_by: str = 'none') -> None:
    """Query source-column usage for an asset.

    Args:
        ctx: Typer command context.
        asset: Asset name or identifier.
        workspace: Workspace targeted by the command.
        column_query: Optional column name filter.
        usage_type: Optional usage category filter.
        file_id: Optional source file identifier.
        group_by: Grouping mode for usage results."""
    invoke(ctx, "columns", workspace, asset=asset, column_query=column_query,
           usage_type=usage_type, file_id=file_id, group_by=group_by)


@columns_app.command("catalog")
def transformation_columns(ctx: typer.Context, asset: str, workspace: Workspace) -> None:
    """List exact column identities available for transformation tracing.

    Args:
        ctx: Typer command context.
        asset: Asset name or identifier.
        workspace: Workspace targeted by the command."""
    invoke(ctx, "column_catalog", workspace, asset=asset)


@columns_app.command("lineage")
def column_lineage(ctx: typer.Context, asset: str, column: str, workspace: Workspace,
                   direction: str = "upstream", status: str = "all") -> None:
    """Trace stored transformations; use global depth, item and paging limits.

    Args:
        ctx: Typer command context.
        asset: Asset name or identifier.
        column: Column name to trace.
        workspace: Workspace targeted by the command.
        direction: Lineage direction to query.
        status: Transformation status filter."""
    invoke(ctx, "column_lineage", workspace, asset=asset, column=column,
           direction=direction, status=status)


@source_app.command("list")
def files(ctx: typer.Context, workspace: Workspace, query: str = "") -> None:
    """List source files matching an optional query.

    Args:
        ctx: Typer command context.
        workspace: Workspace targeted by the command.
        query: Search query or filter."""
    invoke(ctx, "files", workspace, query=query)


@source_app.command("show")
def source(ctx: typer.Context, workspace: Workspace, file_id: str = None, statement_id: str = None,
           operation_id: str = None, start_line: int = None, end_line: int = None, full: bool = False) -> None:
    """Retrieve source evidence by file, statement, or operation.

    Args:
        ctx: Typer command context.
        workspace: Workspace targeted by the command.
        file_id: Optional source file identifier.
        statement_id: Optional statement identifier.
        operation_id: Optional operation identifier.
        start_line: Optional first source line.
        end_line: Optional last source line.
        full: Whether to request the full source content."""
    invoke(ctx, "source", workspace, file_id=file_id, statement_id=statement_id, operation_id=operation_id,
           start_line=start_line, end_line=end_line, full=full)


@source_app.command("search")
def search_source(ctx: typer.Context, query: str, workspace: Workspace, include_matches: bool = False) -> None:
    """Search imported source text for a literal query.

    Args:
        ctx: Typer command context.
        query: Search query or filter.
        workspace: Workspace targeted by the command.
        include_matches: Whether to include matching excerpts."""
    invoke(ctx, "search_code", workspace, query=query, include_matches=include_matches)


@app.command("issues")
def issues(ctx: typer.Context, workspace: Workspace, severity: str = "all") -> None:
    """List analysis issues filtered by severity.

    Args:
        ctx: Typer command context.
        workspace: Workspace targeted by the command.
        severity: Issue severity filter."""
    invoke(ctx, "issues", workspace, severity=severity)


@impact_app.command("analyze")
def impact(ctx: typer.Context, asset: str, workspace: Workspace) -> None:
    """Analyze downstream change impact for an asset.

    Args:
        ctx: Typer command context.
        asset: Asset name or identifier.
        workspace: Workspace targeted by the command."""
    invoke(ctx, "impact", workspace, asset=asset)


@jobs_app.command("status")
def job_status(ctx: typer.Context, job_id: str, workspace: Workspace, wait: bool = False) -> None:
    """Read a job status, optionally waiting for completion.

    Args:
        ctx: Typer command context.
        job_id: Persisted job identifier.
        workspace: Workspace targeted by the command.
        wait: Whether to wait for job completion."""
    invoke(ctx, "job", workspace, job_id=job_id, wait=wait)


@exports_app.command("lineage")
def export(ctx: typer.Context, asset: str, workspace: Workspace, format: str = "json", direction: str = "upstream") -> None:
    """Export bounded lineage for an asset.

    Args:
        ctx: Typer command context.
        asset: Asset name or identifier.
        workspace: Workspace targeted by the command.
        format: Requested output format.
        direction: Lineage direction to query."""
    invoke(ctx, "export", workspace, asset=asset, format=format, direction=direction)


@exports_app.command("read")
def result(ctx: typer.Context, result_id: str, workspace: Workspace, format: str = "json",
           binary: bool = False, offset: int = 0, length: int = 16384) -> None:
    """Read a stored result or a bounded binary artifact segment.

    Args:
        ctx: Typer command context.
        result_id: Stored result identifier.
        workspace: Workspace targeted by the command.
        format: Requested output format.
        binary: Whether to read the artifact as binary data.
        offset: Byte offset within the artifact.
        length: Maximum number of bytes to read."""
    if binary:
        invoke(ctx, 'artifact_read', workspace, artifact_id=result_id, offset=offset, length=length)
    else:
        invoke(ctx, "result", workspace, result_id=result_id, format=format)


@batch_app.command("lineage")
def batch(ctx: typer.Context, assets: list[str], workspace: Workspace, direction: str = "upstream") -> None:
    """Query lineage for multiple assets under a shared budget.

    Args:
        ctx: Typer command context.
        assets: Asset names or identifiers to query.
        workspace: Workspace targeted by the command.
        direction: Lineage direction to query."""
    invoke(ctx, "batch", workspace, assets=assets, direction=direction)


@app.command("mcp")
def mcp(ctx: typer.Context, transport: str = "stdio", host: str = "127.0.0.1", port: int = 8765,
        public_url: str = None) -> None:
    """Run the independent MCP server (stdio or authenticated streamable-http).

    Args:
        ctx: Typer command context.
        transport: MCP transport to use.
        host: HTTP bind host.
        port: HTTP bind port.
        public_url: Optional public server URL."""
    from dataforge.agent.mcp_server import serve
    try:
        serve(ctx.obj["home"], ctx.obj["policy"], transport, host, port, public_url)
    except AgentError as exc:
        fail(ctx, exc)
    except duckdb.Error:
        fail(ctx, AgentError("storage_busy", "Storage has another owner; stop it or choose a separate --home"))


@cleanup_app.command('inspect')
def cleanup_inspect(ctx: typer.Context, workspace: Workspace) -> None:
    """Inspect cleanup eligibility for a workspace.

    Args:
        ctx: Typer command context.
        workspace: Workspace targeted by the command."""
    invoke(ctx, 'cleanup_inspect', workspace)


def _cleanup_command(category: str) -> Any:
    """Create a cleanup command bound to one cleanup category.

    Args:
        category: Cleanup category handled by the returned command.

    Returns:
        Typer command callback for previewing or applying that category."""
    def command(ctx: typer.Context, workspace: Workspace, dry_run: bool = True,
                preview: Path = None, confirm: str = '', backup: bool = True,
                file_id: list[str] = typer.Option(None), run_id: str = None) -> None:
        """Defaults to dry-run. Apply with --no-dry-run --preview FILE --confirm WORKSPACE_NAME.

        Args:
            ctx: Typer command context.
            workspace: Workspace targeted by the command.
            dry_run: Dry run.
            preview: Preview.
            confirm: Explicit restore confirmation phrase.
            backup: Backup.
            file_id: Optional source file identifier.
            run_id: Run id.

        Raises:
            ValueError: If the supplied value violates the operation constraints."""
        if dry_run:
            invoke(ctx, 'cleanup_preview', workspace, category=category, file_ids=file_id, run_id=run_id)
        else:
            import json
            try:
                if preview is None or preview.stat().st_size > 8 * 1024 * 1024:
                    raise ValueError('A bounded saved preview is required')
                plan = json.loads(preview.read_text(encoding='utf-8'))
                if plan.get('category') != category:
                    raise ValueError('Preview category does not match')
            except (OSError, ValueError):
                fail(ctx, AgentError('invalid_argument', 'Provide a saved cleanup preview for this category'))
                return
            invoke(ctx, 'cleanup_apply', workspace, preview=plan, confirmation=confirm, backup_first=backup)
    return command


for _category in ('sources', 'lineage', 'columns', 'ai', 'history', 'jobs', 'reset', 'workspace'):
    cleanup_app.command(_category)(_cleanup_command(_category))
workspace_app.command('reset')(_cleanup_command('reset'))


@maintenance_app.command('inspect')
def maintenance_inspect(ctx: typer.Context) -> None:
    """Inspect database integrity and managed file counts.

    Args:
        ctx: Typer command context."""
    _maintenance(ctx, 'inspect')


@maintenance_app.command('backup')
def maintenance_backup(ctx: typer.Context) -> None:
    """Create a consistent local database backup.

    Args:
        ctx: Typer command context."""
    _maintenance(ctx, 'backup')


@maintenance_app.command('checkpoint')
def maintenance_checkpoint(ctx: typer.Context) -> None:
    """Checkpoint the local database write-ahead log.

    Args:
        ctx: Typer command context."""
    _maintenance(ctx, 'checkpoint')


def _maintenance(ctx: typer.Context, operation: str) -> None:
    """Run an authorized whole-home maintenance operation.

    Args:
        ctx: Typer context containing the home and access policy.
        operation: Maintenance action name."""
    from dataforge.database_maintenance import backup, checkpoint, inspect_database
    if ctx.obj['policy'].workspaces is not None or (operation != 'inspect' and not ctx.obj['policy'].allow_write):
        fail(ctx, AgentError('forbidden', 'Whole-home maintenance requires unrestricted local access and --allow-write for writes'))
        return
    store = None
    try:
        store = Store(ctx.obj['home'])
        result = {'backup': str(backup(store))} if operation == 'backup' else checkpoint(store) if operation == 'checkpoint' else inspect_database(store)
        emit(ctx, result)
    except (OSError, ValueError, duckdb.Error):
        fail(ctx, AgentError('maintenance_failed', 'Maintenance failed; check active jobs, database ownership and filesystem access'))
    finally:
        if store:
            store.close()


@maintenance_app.command('restore')
def maintenance_restore(ctx: typer.Context, archive: Path, destination: Path, confirm: str = '') -> None:
    """Restore a backup into a new runtime home after explicit confirmation.

    Args:
        ctx: Typer command context.
        archive: Backup archive to restore.
        destination: New destination home directory.
        confirm: Explicit restore confirmation phrase."""
    from dataforge.database_maintenance import restore_backup
    if (not ctx.obj['policy'].allow_write or ctx.obj['policy'].workspaces is not None
            or confirm not in {'RESTORE GRAVETRAIL', 'RESTORE DATAFORGE'}):
        fail(ctx, AgentError('forbidden', 'Restore requires unrestricted --allow-write and --confirm "RESTORE GRAVETRAIL"'))
        return
    try:
        emit(ctx, {'restored_home': str(restore_backup(archive, destination))})
    except (OSError, ValueError, duckdb.Error):
        fail(ctx, AgentError('maintenance_failed', 'Backup invalid or destination is not a new directory'))


@app.command('ui', context_settings={'allow_extra_args': True, 'ignore_unknown_options': True})
def ui(ctx: typer.Context) -> None:
    """Launch the packaged Streamlit UI; extra arguments go to the launcher.

    Args:
        ctx: Typer command context."""
    from dataforge.launcher import main
    main(['--home', str(ctx.obj['home']), *ctx.args])



register_settings(app, workspace_app, invoke, fail)
register_application(app, invoke)
register_ai(app, invoke, fail)
register_reports(app, workspace_app, assets_app, lineage_app, source_app, exports_app, invoke)
register_dbt(app, invoke)
register_maintenance(app, maintenance_app, invoke, fail)

if __name__ == "__main__":
    app()
