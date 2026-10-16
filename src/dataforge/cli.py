"""DataForge automation CLI; does not import or start Streamlit."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated

import duckdb
import typer

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
from dataforge.store import Store

app = typer.Typer(no_args_is_help=True, help="Local evidence-backed SQL/SAS analysis and agent access.")
workspace_app = typer.Typer(help="List, create and summarize workspaces.")
lineage_app = typer.Typer(help="Build and query stored lineage.")
columns_app = typer.Typer(help="Direct source-column usage.")
source_app = typer.Typer(help="Source inventory, literal search and explicit evidence retrieval.")
assets_app = typer.Typer(help="Resolve asset names to stable IDs.")
impact_app = typer.Typer(help="Stored downstream change impact.")
jobs_app = typer.Typer(help="Persisted job status and results.")
exports_app = typer.Typer(help="Bounded lineage exports.")
batch_app = typer.Typer(help="Aggregate-budget lineage queries.")
for name, group in [("workspace", workspace_app), ("lineage", lineage_app), ("columns", columns_app),
                    ("source", source_app), ("assets", assets_app), ("impact", impact_app),
                    ("jobs", jobs_app), ("export", exports_app), ("batch", batch_app)]:
    app.add_typer(group, name=name)

Workspace = Annotated[str, typer.Option("--workspace", "-w", help="Exact workspace ID.")]


@app.callback()
def configure(ctx: typer.Context,
              home: Path = typer.Option(None, help="Runtime home; defaults to DATAFORGE_HOME or .dataforge."),
              json_output: bool = typer.Option(False, "--json", help="Compact structured JSON output."),
              quiet: bool = typer.Option(False, "--quiet", "-q"),
              allow_write: bool = typer.Option(False, help="Explicitly authorize mutations for this launch."),
              allowed_workspace: list[str] = typer.Option(None, help="Restrict to these workspace IDs; repeatable."),
              allowed_root: list[Path] = typer.Option(None, help="Authorized import root; repeatable."),
              limit: int = typer.Option(50, min=1, max=500), cursor: str = typer.Option(None),
              max_depth: int = typer.Option(15, min=1, max=30),
              max_items: int = typer.Option(2000, min=1, max=20000),
              max_chars: int = typer.Option(12000, min=512, max=100000),
              detail: str = typer.Option("summary", help="summary, standard or detailed."),
              collapse_temporary: bool = typer.Option(None, "--collapse-temporary/--keep-temporary"),
              output: Path = typer.Option(None, help="Write JSON to a new local file, without overwriting.")):
    roots = allowed_root or [Path(p) for p in os.environ.get("DATAFORGE_ALLOWED_ROOTS", "").split(os.pathsep) if p]
    ctx.obj = {"home": (home or Path(os.environ.get("DATAFORGE_HOME", ".dataforge"))).resolve(),
               "json": json_output, "quiet": quiet, "output": output,
               "policy": AccessPolicy(allow_write, tuple(allowed_workspace) if allowed_workspace else None,
                                      tuple(str(p.resolve()) for p in roots)),
               "options": {"limit": limit, "cursor": cursor, "max_depth": max_depth,
                           "max_items": max_items, "max_chars": max_chars, "detail_level": detail,
                           "collapse_temporary": collapse_temporary}}


def emit(ctx, result):
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


def fail(ctx, exc):
    # Errors never write an output artifact or include exception internals such as SQL/paths.
    typer.echo(compact(exc.response()))
    code = {"forbidden": 3, "not_found": 4, "ambiguous_asset": 4, "busy": 5,
            "storage_busy": 5, "io_error": 6}.get(exc.code, 2)
    raise typer.Exit(code)


def invoke(ctx, action, workspace_id="", background=False, **arguments):
    store = service = None
    try:
        config = ctx.obj
        if action == "job":
            if not config["policy"].permits(workspace_id):
                raise AgentError("forbidden", "Workspace is not authorized")
            jobs = Jobs(config["home"])
            try:
                job_id = arguments["job_id"]
                deadline = time.monotonic() + 300
                while True:
                    record = jobs.read(job_id, workspace_id, private=True)
                    result = cli_job_status(config, workspace_id, record)
                    if not arguments.get("wait") or result["status"] in TERMINAL:
                        break
                    if time.monotonic() >= deadline:
                        raise AgentError("busy", "Job is still running; poll job_id", job_id=job_id)
                    time.sleep(.1)
            finally:
                jobs.close()
        else:
            store = Store(config["home"])
            service = AgentService(store, config["policy"])
            if background:
                service._workspace(workspace_id, write=True)
                QueryOptions.model_validate(config["options"])
                if action == "ingest":
                    config["policy"].import_path(arguments["path"])
                record = service.jobs.create(workspace_id, action,
                    AgentSettings.from_store(store, workspace_id).model_dump())
                # A detached worker opens DuckDB only after this CLI releases its connection.
                record["request"] = {"arguments": arguments, "policy": {
                    "allow_write": config["policy"].allow_write,
                    "workspaces": config["policy"].workspaces,
                    "import_roots": config["policy"].import_roots}}
                service.jobs.write(record)
                service.audit(workspace_id, action, "queued")
                service.close()
                store.close()
                service = store = None
                flags = (subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS) if os.name == "nt" else 0
                subprocess.Popen([sys.executable, "-m", "dataforge.agent.worker", str(config["home"]),
                                  record["job_id"]], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, creationflags=flags, start_new_session=os.name != "nt")
                result = {"job_id": record["job_id"], "status": "queued"}
            else:
                result = service.call(action, workspace_id, options=config["options"], **arguments)
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


def cli_job_status(config, workspace, record):
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
def workspaces(ctx: typer.Context, query: str = ""):
    invoke(ctx, "workspaces", query=query)


@workspace_app.command("create")
def create_workspace(ctx: typer.Context, name: str, description: str = ""):
    invoke(ctx, "create_workspace", name=name, description=description)


@workspace_app.command("summary")
def workspace_summary(ctx: typer.Context, workspace: Workspace):
    invoke(ctx, "summary", workspace)


@app.command("ingest")
def ingest(ctx: typer.Context, path: Path, workspace: Workspace, extensions: str = "sql,sas,csv", background: bool = False):
    invoke(ctx, "ingest", workspace, background, path=str(path.resolve()), extensions=extensions.split(","))


@lineage_app.command("build")
def build(ctx: typer.Context, workspace: Workspace, force: bool = False,
          file_id: list[str] = typer.Option(None), background: bool = False):
    invoke(ctx, "analyze", workspace, background, force=force, file_ids=file_id)


@lineage_app.command("upstream")
def upstream(ctx: typer.Context, asset: str, workspace: Workspace):
    invoke(ctx, "lineage", workspace, asset=asset, direction="upstream")


@lineage_app.command("downstream")
def downstream(ctx: typer.Context, asset: str, workspace: Workspace):
    invoke(ctx, "lineage", workspace, asset=asset, direction="downstream")


@assets_app.command("search")
def search_assets(ctx: typer.Context, workspace: Workspace, query: str = ""):
    invoke(ctx, "assets", workspace, query=query)


@columns_app.command("usage")
def columns(ctx: typer.Context, asset: str, workspace: Workspace):
    invoke(ctx, "columns", workspace, asset=asset)


@source_app.command("list")
def files(ctx: typer.Context, workspace: Workspace, query: str = ""):
    invoke(ctx, "files", workspace, query=query)


@source_app.command("show")
def source(ctx: typer.Context, workspace: Workspace, file_id: str = None, statement_id: str = None,
           operation_id: str = None, start_line: int = None, end_line: int = None, full: bool = False):
    invoke(ctx, "source", workspace, file_id=file_id, statement_id=statement_id, operation_id=operation_id,
           start_line=start_line, end_line=end_line, full=full)


@source_app.command("search")
def search_source(ctx: typer.Context, query: str, workspace: Workspace):
    invoke(ctx, "search_code", workspace, query=query)


@app.command("issues")
def issues(ctx: typer.Context, workspace: Workspace, severity: str = "all"):
    invoke(ctx, "issues", workspace, severity=severity)


@impact_app.command("analyze")
def impact(ctx: typer.Context, asset: str, workspace: Workspace):
    invoke(ctx, "impact", workspace, asset=asset)


@jobs_app.command("status")
def job_status(ctx: typer.Context, job_id: str, workspace: Workspace, wait: bool = False):
    invoke(ctx, "job", workspace, job_id=job_id, wait=wait)


@exports_app.command("lineage")
def export(ctx: typer.Context, asset: str, workspace: Workspace, format: str = "json", direction: str = "upstream"):
    invoke(ctx, "export", workspace, asset=asset, format=format, direction=direction)


@exports_app.command("read")
def result(ctx: typer.Context, result_id: str, workspace: Workspace, format: str = "json"):
    invoke(ctx, "result", workspace, result_id=result_id, format=format)


@batch_app.command("lineage")
def batch(ctx: typer.Context, assets: list[str], workspace: Workspace, direction: str = "upstream"):
    invoke(ctx, "batch", workspace, assets=assets, direction=direction)


@app.command("mcp")
def mcp(ctx: typer.Context, transport: str = "stdio", host: str = "127.0.0.1", port: int = 8765,
        public_url: str = None):
    """Run the independent MCP server (stdio or authenticated streamable-http)."""
    from dataforge.agent.mcp_server import serve
    try:
        serve(ctx.obj["home"], ctx.obj["policy"], transport, host, port, public_url)
    except AgentError as exc:
        fail(ctx, exc)
    except duckdb.Error:
        fail(ctx, AgentError("storage_busy", "Storage has another owner; stop it or choose a separate --home"))


if __name__ == "__main__":
    app()
