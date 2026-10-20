# GraveTrail CLI

Install from this checkout with `uv sync --locked --extra dev`. Run `uv run gravetrail
--help` or install the wheel and use `gravetrail`. Analysis and query commands
do not import or launch Streamlit; `gravetrail ui` and `gravetrail-ui` intentionally
launch it. Python 3.11+ is required.

## First workflow

Global options come **before** the subcommand. Substitute the exact workspace ID
returned by creation; names are not workspace identifiers.

```bash
gravetrail --home ./automation-data --allow-write --json workspace create ecommerce
gravetrail --home ./automation-data --allow-write --allowed-root ./tests/sample_data ingest ./tests/sample_data/dataforge_sql_lineage_test_project.zip --extensions sql --workspace WORKSPACE_ID
gravetrail --home ./automation-data --allow-write lineage build --workspace WORKSPACE_ID
gravetrail --home ./automation-data --json --max-depth 30 lineage upstream pub.all_kpis --workspace WORKSPACE_ID
```

Runtime files stay under `--home`, otherwise `DATAFORGE_HOME`. Without either override,
source launchers use `.dataforge/`; installed launchers use the platform user-data directory.
Do not commit runtime databases or journals. DuckDB permits one owning process per
home: stop Streamlit/MCP before a separate CLI opens its home, or choose another
home. CLI reports `storage_busy`, exit 5, rather than bypassing the database lock.
Do not copy an open database. A single MCP process shares its Store and jobs.

## Commands

Verified against the registered interface on 2026-10-19: **103 executable command
routes and 29 command groups**. Prefix every route below with `gravetrail`.
Global options go before the route; command options go after it. An empty
argument cell means no positional arguments, not that the command has no required
options. **required** marks mandatory options; all commands accept `--help`.
Boolean positive/negative forms and short aliases are listed explicitly.
Use `gravetrail ROUTE --help` for value types, choices, bounds and defaults.
The reference is checked against actual registrations by `tests/test_documentation.py`.

<!-- cli-commands:start -->
| Command | Positional arguments | Command options |
| --- | --- | --- |
| `agent client-config` | — | `--workspace`, `-w` **required**; `--client`; `--transport`; `--help` |
| `agent inspect` | — | `--workspace`, `-w` **required**; `--tool-name`; `--help` |
| `agent self-test` | — | `--workspace`, `-w` **required**; `--help` |
| `ai activity` | — | `--workspace`, `-w` **required**; `--help` |
| `ai chunks` | `FILE_ID` | `--workspace`, `-w` **required**; `--first` **required**; `--last` **required**; `--task` **required**; `--help` |
| `ai merge` | `RECORD_ID` | `--workspace`, `-w` **required**; `--refresh`, `--no-refresh`; `--help` |
| `ai request` | `FILE_ID` | `--workspace`, `-w` **required**; `--first` **required**; `--last` **required**; `--task` **required**; `--expected-hash` **required**; `--expected-job`; `--credential-prompt`, `--no-credential-prompt`; `--help` |
| `ai results export` | `RECORD_ID` | `--workspace`, `-w` **required**; `--help` |
| `ai results get` | `RECORD_ID` | `--workspace`, `-w` **required**; `--help` |
| `ai results list` | — | `--workspace`, `-w` **required**; `--help` |
| `ai review list` | — | `--workspace`, `-w` **required**; `--help` |
| `ai review preview` | `DIAGNOSTIC_ID` | `--workspace`, `-w` **required**; `--first`; `--last`; `--help` |
| `ai review request` | `DIAGNOSTIC_ID` | `--workspace`, `-w` **required**; `--expected-hash` **required**; `--first` **required**; `--last` **required**; `--expected-job`; `--help` |
| `application logging get` | — | `--help` |
| `application logging update` | `LEVEL` | `--help` |
| `application theme apply` | `NAME` | `--help` |
| `application theme get` | — | `--help` |
| `application theme list` | — | `--help` |
| `assets schema` | `ASSET` | `--workspace`, `-w` **required**; `--help` |
| `assets search` | — | `--workspace`, `-w` **required**; `--query`; `--help` |
| `batch lineage` | `ASSETS...` | `--workspace`, `-w` **required**; `--direction`; `--help` |
| `capabilities` | — | `--workspace`; `--help` |
| `cleanup ai` | — | `--workspace`, `-w` **required**; `--dry-run`, `--no-dry-run`; `--preview`; `--confirm`; `--backup`, `--no-backup`; `--file-id` (repeatable); `--run-id`; `--help` |
| `cleanup columns` | — | `--workspace`, `-w` **required**; `--dry-run`, `--no-dry-run`; `--preview`; `--confirm`; `--backup`, `--no-backup`; `--file-id` (repeatable); `--run-id`; `--help` |
| `cleanup history` | — | `--workspace`, `-w` **required**; `--dry-run`, `--no-dry-run`; `--preview`; `--confirm`; `--backup`, `--no-backup`; `--file-id` (repeatable); `--run-id`; `--help` |
| `cleanup inspect` | — | `--workspace`, `-w` **required**; `--help` |
| `cleanup jobs` | — | `--workspace`, `-w` **required**; `--dry-run`, `--no-dry-run`; `--preview`; `--confirm`; `--backup`, `--no-backup`; `--file-id` (repeatable); `--run-id`; `--help` |
| `cleanup lineage` | — | `--workspace`, `-w` **required**; `--dry-run`, `--no-dry-run`; `--preview`; `--confirm`; `--backup`, `--no-backup`; `--file-id` (repeatable); `--run-id`; `--help` |
| `cleanup reset` | — | `--workspace`, `-w` **required**; `--dry-run`, `--no-dry-run`; `--preview`; `--confirm`; `--backup`, `--no-backup`; `--file-id` (repeatable); `--run-id`; `--help` |
| `cleanup sources` | — | `--workspace`, `-w` **required**; `--dry-run`, `--no-dry-run`; `--preview`; `--confirm`; `--backup`, `--no-backup`; `--file-id` (repeatable); `--run-id`; `--help` |
| `cleanup workspace` | — | `--workspace`, `-w` **required**; `--dry-run`, `--no-dry-run`; `--preview`; `--confirm`; `--backup`, `--no-backup`; `--file-id` (repeatable); `--run-id`; `--help` |
| `columns catalog` | `ASSET` | `--workspace`, `-w` **required**; `--help` |
| `columns lineage` | `ASSET`, `COLUMN` | `--workspace`, `-w` **required**; `--direction`; `--status`; `--help` |
| `columns usage` | `ASSET` | `--workspace`, `-w` **required**; `--column-query`; `--usage-type`; `--file-id`; `--group-by`; `--help` |
| `dictionary list` | — | `--workspace`, `-w` **required**; `--query`; `--help` |
| `export download` | `ARTIFACT_ID`, `DESTINATION` | `--workspace`, `-w` **required**; `--help` |
| `export graph` | `ASSET` | `--workspace`, `-w` **required**; `--format`; `--direction`; `--scale`; `--background`; `--title`; `--legend`, `--no-legend`; `--output`; `--help` |
| `export lineage` | `ASSET` | `--workspace`, `-w` **required**; `--format`; `--direction`; `--help` |
| `export paths` | `ASSET` | `--workspace`, `-w` **required**; `--format`; `--direction`; `--max-paths`; `--include-evidence`, `--no-include-evidence`; `--include-source-text`, `--no-include-source-text`; `--help` |
| `export read` | `RESULT_ID` | `--workspace`, `-w` **required**; `--format`; `--binary`, `--no-binary`; `--offset`; `--length`; `--help` |
| `export report` | — | `--workspace`, `-w` **required**; `--kind` **required**; `--format`; `--asset`; `--query`; `--before`; `--after`; `--record-id`; `--help` |
| `export sources` | — | `--workspace`, `-w` **required**; `--asset`; `--file-id` (repeatable); `--direction`; `--help` |
| `history archive` | `PREVIEW` | `--workspace`, `-w` **required**; `--confirm`; `--help` |
| `history archives` | — | `--workspace`, `-w` **required**; `--help` |
| `history preview` | — | `--workspace`, `-w` **required**; `--keep-runs`; `--keep-imports`; `--batch-size`; `--help` |
| `history restore` | `ARCHIVE_ID` | `--workspace`, `-w` **required**; `--confirm`; `--help` |
| `impact analyze` | `ASSET` | `--workspace`, `-w` **required**; `--help` |
| `ingest` | `PATH` | `--workspace`, `-w` **required**; `--extensions`; `--background`, `--no-background`; `--help` |
| `ingestions get` | `INGESTION_ID` | `--workspace`, `-w` **required**; `--help` |
| `ingestions list` | — | `--workspace`, `-w` **required**; `--help` |
| `issues` | — | `--workspace`, `-w` **required**; `--severity`; `--help` |
| `jobs cancel` | `JOB_ID` | `--workspace`, `-w` **required**; `--help` |
| `jobs status` | `JOB_ID` | `--workspace`, `-w` **required**; `--wait`, `--no-wait`; `--help` |
| `lineage analysis-report` | — | `--workspace`, `-w` **required**; `--run-id`; `--help` |
| `lineage build` | — | `--workspace`, `-w` **required**; `--force`, `--no-force`; `--file-id` (repeatable); `--background`, `--no-background`; `--mode`; `--additional-ai-review`, `--no-additional-ai-review`; `--refresh-ai`, `--no-refresh-ai`; `--max-provider-attempts`; `--max-output-tokens-total`; `--max-seconds`; `--resume-run-id`; `--retry-unknown`, `--no-retry-unknown`; `--help` |
| `lineage downstream` | `ASSET` | `--workspace`, `-w` **required**; `--help` |
| `lineage graph` | `ASSET` | `--workspace`, `-w` **required**; `--direction`; `--view`; `--node-id`; `--edge-id`; `--help` |
| `lineage paths` | `ASSET` | `--workspace`, `-w` **required**; `--direction`; `--max-paths`; `--help` |
| `lineage preview` | — | `--workspace`, `-w` **required**; `--mode`; `--file-id` (repeatable); `--additional-ai-review`, `--no-additional-ai-review`; `--max-provider-attempts`; `--max-output-tokens-total`; `--max-seconds`; `--resume-run-id`; `--retry-unknown`, `--no-retry-unknown`; `--help` |
| `lineage steps` | `ASSET` | `--workspace`, `-w` **required**; `--direction`; `--help` |
| `lineage upstream` | `ASSET` | `--workspace`, `-w` **required**; `--help` |
| `lineage validate` | — | `--workspace`, `-w` **required**; `--help` |
| `maintenance backup` | — | `--help` |
| `maintenance backups` | — | `--help` |
| `maintenance checkpoint` | — | `--help` |
| `maintenance download` | `BACKUP_ID`, `DESTINATION` | `--help` |
| `maintenance inspect` | — | `--help` |
| `maintenance restore` | `ARCHIVE`, `DESTINATION` | `--confirm`; `--help` |
| `mcp` | — | `--transport`; `--host`; `--port`; `--public-url`; `--help` |
| `providers credentials status` | `PROFILE_ID` | `--workspace`, `-w` **required**; `--help` |
| `providers get` | `PROFILE_ID` | `--workspace`, `-w` **required**; `--help` |
| `providers list` | — | `--workspace`, `-w` **required**; `--help` |
| `providers models` | `PROFILE_ID` | `--workspace`, `-w` **required**; `--credential-prompt`, `--no-credential-prompt`; `--help` |
| `providers remove` | `PROFILE_ID` | `--workspace`, `-w` **required**; `--expected-revision` **required**; `--help` |
| `providers routing get` | — | `--workspace`, `-w` **required**; `--help` |
| `providers routing update` | `FILE` | `--workspace`, `-w` **required**; `--expected-revision` **required**; `--help` |
| `providers save` | `FILE` | `--workspace`, `-w` **required**; `--expected-revision` **required**; `--profile-id`; `--help` |
| `providers test` | `PROFILE_ID` | `--workspace`, `-w` **required**; `--credential-prompt`, `--no-credential-prompt`; `--help` |
| `runs compare` | `BEFORE`, `AFTER` | `--workspace`, `-w` **required**; `--help` |
| `runs get` | `RUN_ID` | `--workspace`, `-w` **required**; `--help` |
| `runs list` | — | `--workspace`, `-w` **required**; `--help` |
| `runtime info` | — | `--workspace`; `--help` |
| `settings get` | `SECTION` | `--workspace`, `-w` **required**; `--help` |
| `settings schema` | — | `--workspace`, `-w` **required**; `--section`; `--help` |
| `settings update` | `SECTION`, `FILE` | `--workspace`, `-w` **required**; `--expected-revision` **required**; `--help` |
| `source download` | `FILE_ID`, `DESTINATION` | `--workspace`, `-w` **required**; `--content-hash`; `--help` |
| `source list` | — | `--workspace`, `-w` **required**; `--query`; `--help` |
| `source metadata` | `FILE_ID` | `--workspace`, `-w` **required**; `--help` |
| `source search` | `QUERY` | `--workspace`, `-w` **required**; `--include-matches`, `--no-include-matches`; `--help` |
| `source show` | — | `--workspace`, `-w` **required**; `--file-id`; `--statement-id`; `--operation-id`; `--start-line`; `--end-line`; `--full`, `--no-full`; `--help` |
| `staging clean` | `PREVIEW` | `--workspace`, `-w` **required**; `--confirm`; `--name` (repeatable); `--expired`, `--no-expired`; `--help` |
| `staging preview` | — | `--workspace`, `-w` **required**; `--age-hours`; `--help` |
| `staging recoveries` | — | `--workspace`, `-w` **required**; `--help` |
| `staging restore` | `RECOVERY_ID` | `--workspace`, `-w` **required**; `--confirm`; `--help` |
| `ui` | — | `--help` |
| `workspace config export` | — | `--workspace`, `-w` **required**; `--help` |
| `workspace config import` | `FILE` | `--help` |
| `workspace create` | `NAME` | `--description`; `--help` |
| `workspace health` | — | `--workspace`, `-w` **required**; `--help` |
| `workspace list` | — | `--query`; `--help` |
| `workspace reset` | — | `--workspace`, `-w` **required**; `--dry-run`, `--no-dry-run`; `--preview`; `--confirm`; `--backup`, `--no-backup`; `--file-id` (repeatable); `--run-id`; `--help` |
| `workspace summary` | — | `--workspace`, `-w` **required**; `--help` |
| `workspace update` | `NAME` | `--workspace`, `-w` **required**; `--description`; `--expected-revision`; `--help` |
<!-- cli-commands:end -->

### Command groups

Groups organize commands; use `gravetrail GROUP --help` to list their children.

<!-- cli-groups:start -->
| Group | Purpose |
| --- | --- |
| `agent` | Actual schemas, credential-free client examples and local MCP handler self-test. |
| `ai` | Explicit hash/job-pinned grounded assistance; preview operations are offline. |
| `ai results` | Durable results; detailed reads need source permission. |
| `ai review` | Current diagnostic review candidates and bounded source previews. |
| `application` | Application scope; mutation requires unrestricted write/config/application grants. |
| `application logging` | Home-wide persisted log level; no log-content access. |
| `application theme` | Eighteen presets; loaded UI state is unavailable to this process. |
| `assets` | Resolve asset names to stable IDs. |
| `batch` | Aggregate-budget lineage queries. |
| `cleanup` | Preview and explicitly confirm workspace cleanup. |
| `columns` | Direct source-column usage and transformation tracing. |
| `dictionary` | Declared, sampled and explicitly unknown column types. |
| `export` | Bounded lineage exports. |
| `history` | Local guarded history archive/recovery; metadata previews are read-only. |
| `impact` | Stored downstream change impact. |
| `ingestions` | Stored import reports and diagnostics. |
| `jobs` | Persisted job status and results. |
| `lineage` | Build and query stored lineage. |
| `maintenance` | Local database inspection, backup, checkpoint and safe restore. |
| `providers` | Profiles, approved runtime references and explicit outbound tests. |
| `providers credentials` | Status only; use --credential-prompt on a single operation for hidden input. |
| `providers routing` | Default, five task routes and ordered fallbacks. |
| `runs` | Stored analysis runs and comparisons. |
| `runtime` | Runtime owner/home context; switching requires a new invocation. |
| `settings` | Typed atomic workspace settings; widening requires local --allow-admin. |
| `source` | Source inventory, literal search and explicit evidence retrieval. |
| `staging` | Local guarded stale staging cleanup/recovery; never automatic on CLI/MCP reads. |
| `workspace` | List, create and summarize workspaces. |
| `workspace config` | Safe configuration transfers into a new workspace. |
<!-- cli-groups:end -->

### Global options

These apply to `gravetrail`, before any command. Query-specific limits may be further
restricted by workspace settings. The generated help/completion options do not open a
workspace or grant application permissions.

<!-- cli-options:start -->
| Option | Aliases / opposite form | Type / default | Purpose |
| --- | --- | --- | --- |
| `--home` | — | path; default `unset` | Runtime home: explicit path, otherwise DATAFORGE_HOME; without either override use checkout .dataforge/ or the installed platform user-data directory. |
| `--json` | — | flag; default `False` | Compact structured JSON output. |
| `--quiet` | `-q` | flag; default `False` | — |
| `--allow-write` | `--no-allow-write` | flag; default `False` | Explicitly authorize mutations for this launch. |
| `--allow-config-write` | `--no-allow-config-write` | flag; default `False` | — |
| `--allow-llm` | `--no-allow-llm` | flag; default `False` | — |
| `--allowed-llm-origin` | — | str; default `unset`; repeatable | — |
| `--allowed-credential-ref` | — | str; default `unset`; repeatable | — |
| `--allow-application-config` | `--no-allow-application-config` | flag; default `False` | — |
| `--allow-admin` | `--no-allow-admin` | flag; default `False` | Local CLI administration only; cannot be used by MCP. |
| `--allowed-workspace` | — | str; default `unset`; repeatable | Restrict to these workspace IDs; repeatable. |
| `--allowed-root` | — | path; default `unset`; repeatable | Authorized import root; repeatable. |
| `--limit` | — | int range; default `50` | — |
| `--cursor` | — | str; default `unset` | — |
| `--max-depth` | — | int range; default `15` | — |
| `--max-items` | — | int range; default `2000` | — |
| `--max-chars` | — | int range; default `12000` | — |
| `--detail` | — | str; default `summary` | summary, standard or detailed. |
| `--collapse-temporary` | `--keep-temporary` | flag; default `unset` | — |
| `--output` | — | path; default `unset` | Write JSON to a new local file, without overwriting. |
| `--install-completion` | — | flag; default `unset` | Install completion for the current shell. |
| `--show-completion` | — | flag; default `unset` | Show completion for the current shell, to copy it or customize the installation. |
| `--help` | — | flag; default `unset` | Show this message and exit. |
<!-- cli-options:end -->

### UI and build entry points

`gravetrail ui` forwards trailing arguments to the UI launcher, for example
`gravetrail --home ./automation-data ui --port 8502 --no-browser`.
The separate `gravetrail-ui` launcher accepts `--home`, `--port`, `--address`,
`--no-browser`, and `--help`; additional arguments are forwarded to Streamlit.
The separate `gravetrail-build` utility accepts `--target python|docker|executable|all`,
`--verify`, `--root`, `--output`, and `--help`. See [build and release](BUILD_AND_RELEASE.md).
The legacy `dataforge`, `dataforge-ui`, and `dataforge-build` executables remain aliases.

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

Automation & access controls workspace access, write permission,
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

Parity discovery: `gravetrail capabilities` / `get_capabilities` enumerate all 48 IDs with implemented/policy-restricted status. Follow `next_cursor`. New independent launch flags: `--allow-config-write`, `--allow-llm`, repeatable `--allowed-llm-origin`, `--allowed-credential-ref`, `--allow-application-config`; `--allow-admin` is local CLI only and rejected by MCP. None is implied by `--allow-write`.

Workspace preferences: `settings schema -w ID [--section parsing]`, `settings get parsing -w ID`, `settings update parsing patch.json -w ID --expected-revision REV`. Use the returned settings_revision; stale patches fail with conflict. `workspace update -w ID --name NAME --description TEXT --expected-revision REV`; `workspace config export -w ID` returns a configuration object; `workspace config import config.json` accepts that object (v1/v2). Mutations require write+config; imports require unrestricted scope. Privacy/access widening requires local --allow-admin. No analysis is triggered.

Providers: `providers list|get|save|remove`, `providers routing get|update`, `providers credentials status`, `providers models|test PROFILE -w ID [--credential-prompt]`. Save/update take bounded JSON files and --expected-revision; remove refuses routed profiles. All outbound calls need --allow-write --allow-llm, an exact --allowed-llm-origin (scheme/host/port), approved --allowed-credential-ref and workspace privacy approval for remote recipients. Hidden input exists only during that invocation. Never pass key values in arguments/files.

AI: `ai chunks FILE -w ID --first N --last N --task sql_lineage` is offline. `ai request` takes the same bounds plus --expected-hash HASH, --expected-job JOB (default workspace), optionally --credential-prompt. Each request sends only that explicit selection; retries/fallback may bill more than once after an ambiguous disconnect. `ai review list|preview|request`, `ai results list|get`, `ai activity`, `ai merge RECORD -w ID` reuse stored evidence and contracts. Five tasks are sql_lineage, sas_lineage, lineage_validation, column_usage, code_explanation. Advisory/quarantined results cannot merge; merged lineage remains inferred. Detailed saved-result reads require source permission.

Reports: `runs list|get|compare BEFORE AFTER -w ID`, `ingestions list|get -w ID`, `dictionary list -w ID`, `assets schema ASSET -w ID`, `workspace health -w ID`, `lineage validate -w ID`, `source metadata FILE -w ID`. Source inventory adds encoding/file_size. `source search TEXT -w ID --include-matches` explicitly returns exact code lines with source permission; default remains matching file metadata. CSV values are excluded from line search. Schema evidence code requires --detail detailed; sampled types and unknowns retain provenance. Evidence validation reads original versions, does not reparse or repair.

Artifacts: `export graph ASSET --format html|json|svg|png`, `export paths ASSET --format csv|json|xlsx`, `export sources --asset ASSET` or repeated --file-id; `source download FILE DESTINATION [--content-hash HASH]`; `export report --kind KIND --format FORMAT` with --asset/--query/--before/--after; `ai results export RECORD`. All take -w ID. `export read ID --binary --offset N --length N` returns base64; `export download ID DESTINATION` reassembles/checks checksum and refuses existing destinations. Source-related creation and every read require source permission; backups are excluded.64MB/artifact,16KiB/chunk before encoding, further response-budget caps.

Format allowlist: graph HTML/JSON/SVG/PNG; paths CSV/JSON/XLSX; source-bundle ZIP; original-source raw bytes; inventory/code-search CSV/JSON; dictionary/columns/impact CSV/JSON/HTML; run-comparison/ai-result JSON. Unsupported combinations fail. `lineage paths|steps|graph ASSET -w ID` returns bounded logical dependency data with depth/limit/cycle boundaries; graph --view nodes|edges|tree supports --node-id/--edge-id. `columns usage` supports --column-query/--usage-type/--file-id/--group-by none|file|usage_type. No runtime execution ordering claim.

Column transformation traces use the same scoped stored facts as the UI:

```bash
gravetrail --home ./automation-data --json columns catalog mart.order_totals -w WORKSPACE_ID
gravetrail --home ./automation-data --json --max-depth 5 --max-items 200 --detail standard columns lineage mart.order_totals gross_amount -w WORKSPACE_ID
gravetrail --home ./automation-data --json columns lineage raw.orders quantity --direction downstream --status all -w WORKSPACE_ID
```

Use an exact asset ID for ambiguous or temporary assets. `COLUMN` accepts a column
name within that asset or an exact ID from `columns catalog`. Status choices are
`all`, `verified`, `inferred` and `unresolved`. Global `--limit`, `--cursor`,
`--max-depth`, `--max-items` and `--max-chars` apply. Derivations appear in `items`
with input roles and their uncollapsed `paths`; follow `next_cursor` for later pages.
Retain `state`, `coverage`, `truncated`, `trace_complete`, `analysis_current` and
`boundaries` when saving output with global `--output`. Summary excludes expressions
and code; standard expressions require source permission, and detailed original code
requires source permission. Zero-input constants, unresolved columns, not analyzed
assets and no known dependencies remain distinct. `columns usage` still reports
direct references independently. The Transformation lineage UI exports bounded
CSV/JSON with evidence and coverage markers.

For Excel: `gravetrail --allow-write export paths ASSET -w ID --format xlsx
--include-evidence` creates an artifact; `export download ARTIFACT_ID lineage.xlsx -w ID`
retrieves it without overwriting an existing file. Add `--include-source-text` only
with `--include-evidence` to export raw analyzed SQL/SAS. Source permission is required
at creation and every read, including when evidence is excluded. Global `--max-depth`,
`--max-items` and `--collapse-temporary` bound the same shared scope used by Explorer.
The response includes revision, counts, warnings, safe filename, MIME type and artifact
ID, not workbook bytes. See [Excel workflow and limits](USER_GUIDE.md) for continuation,
coverage and size/time behavior.

Maintenance parity: `history preview --keep-runs N --keep-imports N --batch-size N -w ID`, `history archives -w ID`, `history archive PREVIEW.json -w ID --confirm NAME`, `history restore ARCHIVE_ID -w ID --confirm NAME`. `staging preview --age-hours 24 -w ID`, `staging clean PREVIEW.json -w ID --confirm NAME [--name UUID.tmp] [--expired]`, `staging recoveries|restore`. Save previews using global --output NEW_FILE; apply consumes that exact preview. Local mutations need --allow-write and unrestricted ownership; archive/clean create a recoverable whole-home backup before removal. General cleanup defaults to backup and refuses --no-backup. Specialized recovery journals remain separate from general undo. `maintenance backups` and `maintenance download BACKUP_ID NEW_DEST` require unrestricted --allow-application-config; backup/restore/checkpoint existing local guards remain. Shared cache/orphan/application apply remains UI-only.

Application/runtime: `application theme list|get|apply NAME`, `application logging get|update LEVEL`, `runtime info`, `agent inspect -w ID [--tool-name NAME]`, `agent client-config -w ID --client codex|claude --transport stdio|streamable-http`, `agent self-test -w ID`. Application mutations need --allow-write --allow-config-write --allow-application-config with unrestricted workspace scope. Theme path is startup-selected DATAFORGE_THEME_CONFIG or source-checkout .streamlit/config.toml; installed UI selects its home copy. Theme reads report configured/detected state, loaded=null, reload_required=true; never restart another owner. Logging is persisted per home. Self-test runs the actual in-process handler; external transport/client tests remain separate.

See the [complete UI capability matrix](CLI_MCP_CAPABILITIES.md) for every coverage ID, exact command/tool names and policy restrictions.

Graph images use the same filtered scene as Explorer. For example:
```bash
gravetrail --home ./automation-data --json --allow-write --max-depth 5 --max-items 150 export graph mart.sales -w WORKSPACE_ID --format svg --output lineage.svg
gravetrail --home ./automation-data --json --allow-write export graph mart.sales -w WORKSPACE_ID --format png --scale 2 --background light --title "Design review" --output lineage.png
```
`export graph --output` writes the image to a new file and stdout describes its
artifact/destination. The global `--output` before the subcommand still writes
response JSON. Existing destinations are refused before image creation. Omit
local `--output` to create a managed artifact for later `export download`.
Image options: `--scale 1|2`, `--background light|dark|transparent`, `--title TEXT`
(empty omits it), and `--legend/--no-legend`. Global traversal bounds, temporary
collapse and workspace confidence/inferred filters apply. Responses contain MIME,
filename, revision, graph revision, counts and explicit coverage/truncation.
See the [user guide](USER_GUIDE.md) for image bounds and metadata privacy.

## Explicit AI project builds

`lineage build` defaults to local parser mode. `--mode hybrid` explicitly requests parser comparison plus validated AI extraction; `--mode ai` selects experimental AI-generated extraction. `lineage preview` is offline and reports disclosure, complete-unit/context failures, routes and worst-case attempt/output reservations. `lineage analysis-report` reads a saved report; `jobs cancel` requests cooperative cancellation. Use each route's `--help` for selected file IDs, refresh/review and bounded run options.

Billable builds require the existing independent write/source/network grants: `--allow-write`, `--allow-llm`, exact `--allowed-llm-origin` and approved `--allowed-credential-ref`, plus workspace privacy. Complete-file disclosure across remote chunks requires complete-source permission. Do not put credential values in command arguments. A failed/cancelled/stale run keeps the old graph; requests already sent may have incurred usage. Preview, parser defaults and report reads send zero provider requests. See [AI project analysis](AI_ANALYSIS.md) for modes, semantic limits, deadlines and the full prompt/schema context budget.

## Automatic project budgets and continuation

For `lineage build` and `lineage preview`, omitted `--max-provider-attempts`, `--max-output-tokens-total` and `--max-seconds` calculate a bounded execution automatically. Explicit numeric values are ceilings. Use `--resume-run-id RUN_ID` to continue a paused AI build; its source selection/mode/options remain pinned. `--retry-unknown` explicitly permits retrying a lost in-flight request and may incur duplicate usage. Inspect `lineage analysis-report` first. Offline preview makes no network requests.

AI preview also reports semantic projection tasks and whether review sizing is provisional. Source partitions and completed review batches are preserved by the shared Continue implementation; these behaviors require no additional CLI options. See [oversized operations](AI_ANALYSIS.md#oversized-operations-and-large-review-sets).
