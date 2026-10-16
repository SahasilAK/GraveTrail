# DataForge CLI

Install from this checkout with `uv sync --locked --extra dev`. Run `uv run dataforge
--help` or install the wheel and use `dataforge`. Streamlit is neither imported nor
launched by the CLI. Python 3.11+ is required.

## First workflow

Global options come **before** the subcommand. Substitute the exact workspace ID
returned by creation; names are not workspace identifiers.

```bash
dataforge --home ./automation-data --allow-write --json workspace create ecommerce
dataforge --home ./automation-data --allow-write --allowed-root ./tests/sample_data ingest ./tests/sample_data/dataforge_sql_lineage_test_project.zip --extensions sql --workspace WORKSPACE_ID
dataforge --home ./automation-data --allow-write lineage build --workspace WORKSPACE_ID
dataforge --home ./automation-data --json --max-depth 30 lineage upstream pub.all_kpis --workspace WORKSPACE_ID
```

Runtime files stay under `--home`, otherwise `DATAFORGE_HOME`, otherwise `.dataforge`.
Do not commit runtime databases or journals. DuckDB permits one owning process per
home: stop Streamlit/MCP before a separate CLI opens its home, or choose another
home. CLI reports `storage_busy`, exit 5, rather than bypassing the database lock.
Do not copy an open database. A single MCP process shares its Store and jobs.

## Commands

| Command | Purpose |
| --- | --- |
| `workspace list [--query TEXT]` | Page permitted workspaces |
| `workspace create NAME [--description TEXT]` | Create workspace with explicit startup writes |
| `workspace summary --workspace ID` | Counts and analysis freshness |
| `ingest PATH --extensions sql,sas,csv --workspace ID` | Allowed directory/ZIP import |
| `lineage build --workspace ID [--force] [--file-id ID]` | Cached analysis or explicit selected refresh |
| `lineage upstream ASSET --workspace ID` | Upstream dependencies |
| `lineage downstream ASSET --workspace ID` | Downstream dependencies |
| `assets search --query TEXT --workspace ID` | Asset IDs and candidate identities |
| `columns usage ASSET --workspace ID` | Direct persisted column usage |
| `source list --workspace ID [--query PATH]` | Metadata-only source inventory |
| `source search TEXT --workspace ID` | Literal code search returning file references |
| `source show --statement-id ID --workspace ID` | Original statement evidence |
| `source show --operation-id ID --workspace ID` | Original operation evidence |
| `source show --file-id ID --start-line N --end-line M --workspace ID` | Explicit original lines |
| `source show --file-id ID --full --workspace ID` | Explicit complete source, still paginated/bounded |
| `impact analyze ASSET --workspace ID` | Downstream page with per-page kind groups |
| `issues --workspace ID [--severity warning]` | Stored analysis diagnostics |
| `batch lineage ASSET1 ASSET2 --workspace ID` | Up to 20 assets with aggregate budgets |
| `jobs status JOB_ID --workspace ID [--wait]` | Persisted progress/result |
| `export lineage ASSET --workspace ID --format json` | Create a JSON/CSV/HTML page artifact |
| `export read RESULT_ID --workspace ID [--format json]` | Retrieve explicit bounded artifact |
| `mcp [--transport stdio]` | Independent MCP server; see MCP guide |

Use each command's `--help` for its full argument list. `--file-id` is repeatable.
Imports and builds wait by default; add command option `--background` to get a job
ID immediately. A detached fixed Python worker executes after the CLI closes its
database. Poll using `jobs status`; polling can read its journal while the worker
owns DuckDB. `--wait` polls up to five minutes, then returns exit 5 and the job ID;
it does not cancel the worker. A foreground timeout waits for safe thread shutdown.
Queued/running jobs with no heartbeat for 30 seconds are reported interrupted;
retry explicitly, never assume success. Completed results survive restarts.

## Output and access controls

Human-readable output is default. `--json` emits compact JSON, `--quiet` suppresses
successful terminal output, and `--output NEW_FILE` writes JSON using exclusive
creation so existing files are not overwritten. JSON errors are emitted even in
quiet mode. `export lineage` writes under `HOME/agent/results/WORKSPACE_ID/` and
returns a `result_id`, relative path, byte size, `complete` and continuation cursor.
An export is one bounded query page; follow its cursor to export subsequent pages.

Read-only is the startup default. `--allow-write` authorizes workspace creation,
import, analysis and artifact creation; workspace settings may revoke it further.
`--allowed-workspace ID` narrows access and is repeatable. A scoped launch cannot
create workspaces. `--allowed-root PATH` is repeatable; alternatively set
`DATAFORGE_ALLOWED_ROOTS` with the OS path separator. No import roots are implicitly
granted by the CLI. There is no arbitrary shell/SQL execution, provider configuration,
secret discovery, destructive workspace deletion or LLM invocation command.

Settings → Agent & Automation Access controls workspace access, write permission,
source retrieval, default detail, response cap and optional read auditing. Mutation
events are always audited in `HOME/agent/audit.jsonl`, rotated at approximately 1 MB
with one previous file retained. Records omit arguments, source and credentials.
These controls govern application interfaces; OS users with filesystem access to a
data home can read its data and are trusted administrators of that home.

## Pagination and failures

`--limit` defaults 50 (maximum 500); `--cursor` continues a stable query. Cursors
are bound to workspace, filters, detail, analysis revision and result contents;
changed results invalidate them. `--max-depth` defaults 15 (maximum 30),
`--max-items` defaults 2,000 (maximum 20,000), `--max-chars` defaults 12,000
(maximum 100,000 and additionally capped by workspace settings).
`--collapse-temporary` / `--keep-temporary` override the saved collapse preference.
`--detail summary|standard|detailed` defaults summary. Standard includes relationship
identifiers, method/status/confidence and positions; detailed explicitly requests
code/expressions. Source retrieval is separately permission checked.

Pages include `count`, `total`, `next_cursor` and `complete`. `complete=false` also
covers stale analysis or graph boundaries; `analysis_current`, `boundaries`,
`unresolved_count` and `statuses` explain limits. A depth/item boundary may require
larger traversal limits rather than another page. Batch results include
`remaining_assets`; continue those individually. An oversized single record causes
`budget_too_small`, never an apparently complete truncated record. Retrieve a
narrow file range when a statement exceeds the server's response cap.

Errors have `{"error":{"code":"...","message":"..."}}`; ambiguous assets include
candidate IDs, never a guessed selection. Exit codes: 0 success, 2 invalid
request/budget, 3 forbidden, 4 missing/ambiguous identity, 5 busy/timeout,
6 I/O or failed/interrupted job. Typer syntax errors also exit 2.

Up to two jobs may run, one per workspace. Graph queries reject more than 20,000
assets or 100,000 evidence edges. Journals and exports cap at 1,000 each (exports
per workspace); archive completed local files when reached. No distributed worker,
job cancellation or automatic job retry is introduced.

Parity discovery: `dataforge capabilities` / `get_capabilities` enumerate all46 IDs with explicit pending/restricted status. Follow `next_cursor`. New independent launch flags: `--allow-config-write`, `--allow-llm`, repeatable `--allowed-llm-origin`, `--allowed-credential-ref`, `--allow-application-config`; `--allow-admin` is local CLI only and rejected by MCP. None is implied by `--allow-write`.
