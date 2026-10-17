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
granted by the CLI. No arbitrary shell/SQL execution or secret discovery is exposed.
Provider configuration, AI requests and local cleanup require the independent grants below.

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

Parity discovery: `dataforge capabilities` / `get_capabilities` enumerate all 46 IDs with implemented/policy-restricted status. Follow `next_cursor`. New independent launch flags: `--allow-config-write`, `--allow-llm`, repeatable `--allowed-llm-origin`, `--allowed-credential-ref`, `--allow-application-config`; `--allow-admin` is local CLI only and rejected by MCP. None is implied by `--allow-write`.

Workspace preferences: `settings schema -w ID [--section parsing]`, `settings get parsing -w ID`, `settings update parsing patch.json -w ID --expected-revision REV`. Use the returned settings_revision; stale patches fail with conflict. `workspace update -w ID --name NAME --description TEXT --expected-revision REV`; `workspace config export -w ID` returns a configuration object; `workspace config import config.json` accepts that object (v1/v2). Mutations require write+config; imports require unrestricted scope. Privacy/access widening requires local --allow-admin. No analysis is triggered.

Providers: `providers list|get|save|remove`, `providers routing get|update`, `providers credentials status`, `providers models|test PROFILE -w ID [--credential-prompt]`. Save/update take bounded JSON files and --expected-revision; remove refuses routed profiles. All outbound calls need --allow-write --allow-llm, an exact --allowed-llm-origin (scheme/host/port), approved --allowed-credential-ref and workspace privacy approval for remote recipients. Hidden input exists only during that invocation. Never pass key values in arguments/files.

AI: `ai chunks FILE -w ID --first N --last N --task sql_lineage` is offline. `ai request` takes the same bounds plus --expected-hash HASH, --expected-job JOB (default workspace), optionally --credential-prompt. Each request sends only that explicit selection; retries/fallback may bill more than once after an ambiguous disconnect. `ai review list|preview|request`, `ai results list|get`, `ai activity`, `ai merge RECORD -w ID` reuse stored evidence and contracts. Five tasks are sql_lineage, sas_lineage, lineage_validation, column_usage, code_explanation. Advisory/quarantined results cannot merge; merged lineage remains inferred. Detailed saved-result reads require source permission.

Reports: `runs list|get|compare BEFORE AFTER -w ID`, `ingestions list|get -w ID`, `dictionary list -w ID`, `assets schema ASSET -w ID`, `workspace health -w ID`, `lineage validate -w ID`, `source metadata FILE -w ID`. Source inventory adds encoding/file_size. `source search TEXT -w ID --include-matches` explicitly returns exact code lines with source permission; default remains matching file metadata. CSV values are excluded from line search. Schema evidence code requires --detail detailed; sampled types and unknowns retain provenance. Evidence validation reads original versions, does not reparse or repair.

Artifacts: `export graph ASSET --format html|json`, `export paths ASSET --format csv|json`, `export sources --asset ASSET` or repeated --file-id; `source download FILE DESTINATION [--content-hash HASH]`; `export report --kind KIND --format FORMAT` with --asset/--query/--before/--after; `ai results export RECORD`. All take -w ID. `export read ID --binary --offset N --length N` returns base64; `export download ID DESTINATION` reassembles/checks checksum and refuses existing destinations. Source-related creation and every read require source permission; backups are excluded.64MB/artifact,16KiB/chunk before encoding, further response-budget caps.

Format allowlist: graph HTML/JSON; paths CSV/JSON; source-bundle ZIP; original-source raw bytes; inventory/code-search CSV/JSON; dictionary/columns/impact CSV/JSON/HTML; run-comparison/ai-result JSON. Unsupported combinations fail. `lineage paths|steps|graph ASSET -w ID` returns bounded logical dependency data with depth/limit/cycle boundaries; graph --view nodes|edges|tree supports --node-id/--edge-id. `columns usage` supports --column-query/--usage-type/--file-id/--group-by none|file|usage_type. No runtime execution ordering claim.

Maintenance parity: `history preview --keep-runs N --keep-imports N --batch-size N -w ID`, `history archives -w ID`, `history archive PREVIEW.json -w ID --confirm NAME`, `history restore ARCHIVE_ID -w ID --confirm NAME`. `staging preview --age-hours 24 -w ID`, `staging clean PREVIEW.json -w ID --confirm NAME [--name UUID.tmp] [--expired]`, `staging recoveries|restore`. Save previews using global --output NEW_FILE; apply consumes that exact preview. Local mutations need --allow-write and unrestricted ownership; archive/clean create a recoverable whole-home backup before removal. General cleanup defaults to backup and refuses --no-backup. Specialized recovery journals remain separate from general undo. `maintenance backups` and `maintenance download BACKUP_ID NEW_DEST` require unrestricted --allow-application-config; backup/restore/checkpoint existing local guards remain. Shared cache/orphan/application apply remains UI-only.

Application/runtime: `application theme list|get|apply NAME`, `application logging get|update LEVEL`, `runtime info`, `agent inspect -w ID [--tool-name NAME]`, `agent client-config -w ID --client codex|claude --transport stdio|streamable-http`, `agent self-test -w ID`. Application mutations need --allow-write --allow-config-write --allow-application-config with unrestricted workspace scope. Theme path is startup-selected DATAFORGE_THEME_CONFIG or source-checkout .streamlit/config.toml; installed UI selects its home copy. Theme reads report configured/detected state, loaded=null, reload_required=true; never restart another owner. Logging is persisted per home. Self-test runs the actual in-process handler; external transport/client tests remain separate.

See the [complete UI capability matrix](CLI_MCP_CAPABILITIES.md) for every coverage ID, exact command/tool names and policy restrictions.
