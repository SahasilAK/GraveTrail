# MCP integration

GraveTrail uses the official `mcp` Python SDK (locked 1.30.0). CLI, MCP and the UI
reuse Store, Importer, the analysis service, LineageGraph and exports. The adapters
contain no parser implementation. Normal queries use persisted facts and never
invoke an LLM or execute imported source.

## Recommended: local stdio

```bash
gravetrail --home ./automation-data --allowed-workspace WORKSPACE_ID mcp
```

Launch from the installed environment, or use an absolute Python executable and
`-m dataforge.cli`. Stdio writes MCP JSON-RPC only to stdout; OS/process permissions
are its security boundary. Do not open the same home in another Streamlit/CLI/MCP
process. Automation & access supplies ready-to-copy configurations using actual absolute paths.

Codex `config.toml` example (replace paths and ID):

```toml
[mcp_servers.gravetrail]
command = "D:/GraveTrail/.venv/Scripts/python.exe"
args = ["-m", "dataforge.cli", "--home", "D:/GraveTrail/automation-data", "--allowed-workspace", "WORKSPACE_ID", "mcp"]
```

Claude Code project `.mcp.json`:

```json
{
  "mcpServers": {
    "gravetrail": {
      "command": "D:/GraveTrail/.venv/Scripts/python.exe",
      "args": ["-m", "dataforge.cli", "--home", "D:/GraveTrail/automation-data", "--allowed-workspace", "WORKSPACE_ID", "mcp"]
    }
  }
}
```

Alternatively register an installed CLI:
`claude mcp add --transport stdio gravetrail -- gravetrail --home ./automation-data mcp`.
Formats were checked against the [official Codex MCP guide](https://developers.openai.com/codex/mcp)
and [official Claude Code MCP guide](https://code.claude.com/docs/en/mcp) on 2026-10-16.
These are examples only; GraveTrail does not modify client configuration.

Add `--allow-write` **before** `mcp` only for an authorized automation workflow;
configure `DATAFORGE_ALLOWED_ROOTS` before launching to enable bounded imports.
Workspace settings can disable access, writes or source retrieval. The UI test
executes a real MCP handler against the current Store in-process, not a network
probe. After connecting externally, call `list_workspaces` then
`get_workspace_summary` to verify actual client connectivity.

## Streamable HTTP

Set `DATAFORGE_MCP_TOKEN` to a private value of at least 32 characters through your
environment/secret manager. Never put its value in project configuration or logs.

```bash
gravetrail --home ./automation-data --allowed-workspace WORKSPACE_ID mcp --transport streamable-http --host 127.0.0.1 --port 8765
```

Endpoint: `http://127.0.0.1:8765/mcp`. Every request requires an Authorization
bearer header, including GET/POST/DELETE. Explicit workspace IDs are mandatory;
unauthenticated network startup is refused. For Codex HTTP configuration:

```toml
[mcp_servers.gravetrail]
url = "http://127.0.0.1:8765/mcp"
bearer_token_env_var = "DATAFORGE_MCP_TOKEN"
```

This supports privately pre-provisioned bearer credentials. It does **not** provide
OAuth login, token issuance or dynamic authorization-server discovery. Rotate the
environment credential and restart the server to rotate access. Run separate
restricted server processes/homes for separate trust groups; one token represents
one launch policy, not multiple independently authorized users.

For an external binding, also supply `--public-url https://your-host/mcp` and use
a trusted TLS reverse proxy and network rules that prevent direct access to the
unencrypted backend. GraveTrail does not terminate TLS itself. DNS rebinding/Origin
checks remain enabled; external hostname comes from the declared public URL.
Request bodies cap at 64 KB, admitted HTTP requests at eight, and jobs at two.
SDK protocol/validation errors are bounded by the SDK; application errors omit
exception internals. HTTP access logging is disabled to keep source/credentials out.

## Discovery and tools

The complete registered interface has **83 tools**, verified on 2026-10-19.
The table lists every tool and every top-level input. `options` is the shared bounded
query object described below. Required inputs are separate from optional inputs;
optional defaults and enum values are available through MCP tool discovery or
`gravetrail agent inspect -w ID --tool-name TOOL_NAME`.
Read/mutation/network annotations are descriptive hints; startup grants, workspace
policy, source permission and exact origin/reference checks enforce authorization.
A listed tool may be unavailable to the current launch. This reference is checked
against actual SDK registrations by `tests/test_documentation.py`.

<!-- mcp-tools:start -->
| Tool | Required inputs | Optional inputs |
| --- | --- | --- |
| `analyze_impact` | `asset`, `workspace_id` | `options` |
| `apply_application_theme` | `name` | `options` |
| `cancel_job` | `job_id`, `workspace_id` | — |
| `clear_runtime_connection` | `profile_id`, `workspace_id` | `options` |
| `compare_analysis_runs` | `after`, `before`, `workspace_id` | `options` |
| `connect_runtime_reference` | `profile_id`, `workspace_id` | `options` |
| `create_workspace` | `name` | `description` |
| `discover_provider_models` | `profile_id`, `workspace_id` | `options` |
| `export_ai_result` | `record_id`, `workspace_id` | `options` |
| `export_dependency_paths` | `asset`, `workspace_id` | `direction`, `format`, `include_evidence`, `include_source_text`, `max_paths`, `options` |
| `export_graph` | `asset`, `workspace_id` | `background`, `direction`, `format`, `legend`, `options`, `scale`, `title` |
| `export_original_source` | `file_id`, `workspace_id` | `content_hash`, `options` |
| `export_report` | `format`, `kind`, `selection`, `workspace_id` | `options` |
| `export_results` | `asset`, `workspace_id` | `direction`, `format`, `options` |
| `export_source_bundle` | `selection`, `workspace_id` | `options` |
| `export_workspace_configuration` | `workspace_id` | — |
| `get_agent_setup` | `workspace_id` | `client`, `options`, `tool_name`, `transport` |
| `get_ai_activity` | `workspace_id` | `options` |
| `get_ai_result` | `record_id`, `workspace_id` | `options` |
| `get_analysis_issues` | `workspace_id` | `options`, `severity` |
| `get_analysis_run` | `run_id`, `workspace_id` | `options` |
| `get_application_logging` | — | `options` |
| `get_application_theme` | — | `options` |
| `get_asset_schema` | `asset`, `workspace_id` | `options` |
| `get_capabilities` | — | `options`, `workspace_id` |
| `get_column_lineage` | `asset`, `column`, `workspace_id` | `direction`, `options`, `status` |
| `get_column_usage` | `asset`, `workspace_id` | `column_query`, `file_id`, `group_by`, `options`, `usage_type` |
| `get_data_dictionary` | `workspace_id` | `options`, `query` |
| `get_dependency_paths` | `asset`, `workspace_id` | `direction`, `max_paths`, `options` |
| `get_export` | `workspace_id` | `artifact_id`, `format`, `length`, `offset`, `options`, `result_id` |
| `get_graph_data` | `asset`, `workspace_id` | `direction`, `edge_id`, `node_id`, `options`, `view` |
| `get_ingestion_run` | `ingestion_id`, `workspace_id` | `options` |
| `get_job_status` | `job_id`, `workspace_id` | `options` |
| `get_lineage` | `asset`, `workspace_id` | `direction`, `options` |
| `get_lineage_batch` | `assets`, `workspace_id` | `direction`, `options` |
| `get_lineage_steps` | `asset`, `workspace_id` | `direction`, `options` |
| `get_model_routing` | `workspace_id` | `options` |
| `get_project_analysis_report` | `workspace_id` | `options`, `run_id` |
| `get_provider_profile` | `profile_id`, `workspace_id` | `options` |
| `get_runtime_connection_status` | `profile_id`, `workspace_id` | `options` |
| `get_runtime_info` | — | `options`, `workspace_id` |
| `get_settings_schema` | `workspace_id` | `section` |
| `get_source_evidence` | `workspace_id` | `end_line`, `file_id`, `full`, `operation_id`, `options`, `start_line`, `statement_id` |
| `get_source_metadata` | `file_id`, `workspace_id` | `options` |
| `get_transformation_columns` | `asset`, `workspace_id` | `options` |
| `get_workspace_health` | `workspace_id` | `options` |
| `get_workspace_settings` | `section`, `workspace_id` | — |
| `get_workspace_summary` | `workspace_id` | — |
| `import_workspace_configuration` | `configuration` | — |
| `ingest_sources` | `extensions`, `path`, `workspace_id` | — |
| `inspect_cleanup` | `workspace_id` | — |
| `inspect_database_maintenance` | — | `options` |
| `list_ai_results` | `workspace_id` | `options` |
| `list_analysis_runs` | `workspace_id` | `options` |
| `list_history_archives` | `workspace_id` | `options` |
| `list_ingestion_runs` | `workspace_id` | `options` |
| `list_provider_profiles` | `workspace_id` | `options` |
| `list_review_candidates` | `workspace_id` | `options` |
| `list_runtime_backups` | — | `options` |
| `list_staging_recoveries` | `workspace_id` | `options` |
| `list_theme_presets` | — | `options` |
| `list_workspaces` | — | `options`, `query` |
| `merge_ai_claims` | `record_id`, `workspace_id` | `options`, `refresh` |
| `preview_ai_chunks` | `file_id`, `first`, `last`, `task`, `workspace_id` | `options` |
| `preview_cleanup` | `category`, `workspace_id` | `file_ids`, `run_id` |
| `preview_diagnostic_review` | `diagnostic_id`, `workspace_id` | `first`, `last`, `options` |
| `preview_history_archive` | `workspace_id` | `batch_size`, `keep_imports`, `keep_runs`, `options` |
| `preview_project_analysis` | `workspace_id` | `additional_ai_review`, `file_ids`, `max_output_tokens_total`, `max_provider_attempts`, `max_seconds`, `mode`, `resume_run_id`, `retry_unknown` |
| `preview_staging_cleanup` | `workspace_id` | `age_hours`, `options` |
| `remove_provider_profile` | `expected_revision`, `profile_id`, `workspace_id` | `options` |
| `request_ai_assistance` | `expected_hash`, `file_id`, `first`, `last`, `task`, `workspace_id` | `expected_job`, `options` |
| `request_diagnostic_review` | `diagnostic_id`, `expected_hash`, `first`, `last`, `workspace_id` | `expected_job`, `options` |
| `save_provider_profile` | `expected_revision`, `profile`, `workspace_id` | `options`, `profile_id` |
| `search_assets` | `workspace_id` | `options`, `query` |
| `search_source_code` | `workspace_id` | `include_matches`, `options`, `query` |
| `start_lineage_analysis` | `workspace_id` | `additional_ai_review`, `file_ids`, `force`, `max_output_tokens_total`, `max_provider_attempts`, `max_seconds`, `mode`, `refresh_ai`, `resume_run_id`, `retry_unknown` |
| `test_local_agent_access` | `workspace_id` | `options` |
| `test_provider_connection` | `profile_id`, `workspace_id` | `options` |
| `update_application_logging` | `level` | `options` |
| `update_model_routing` | `expected_revision`, `values`, `workspace_id` | `options` |
| `update_workspace` | `description`, `expected_revision`, `name`, `workspace_id` | — |
| `update_workspace_settings` | `expected_revision`, `section`, `values`, `workspace_id` | — |
| `validate_stored_lineage` | `workspace_id` | `options` |
<!-- mcp-tools:end -->

`options` accepts `detail_level`, `limit`, `cursor`, `max_depth`, `max_items`,
`max_chars`, `collapse_temporary`; limits/errors match the [CLI guide](CLI_GUIDE.md).
`get_source_evidence` accepts exactly one file/statement/operation ID; a file
requires a line range or explicit `full=true`. Full retrieval remains paginated.
Disabling source access also blocks detailed responses and export retrieval.
Mutating tools require startup writes plus workspace permission and are annotated
as mutations. Tool annotations are hints; service checks enforce permission.

Successful tool results contain one `structuredContent` object and an empty
`content` array, avoiding a duplicated JSON text block. Use a client supporting
MCP structured tool results (2025-06-18+). Application failures set `isError=true`
and return a small structured `error`; framework argument failures remain standard
MCP errors. Never interpret source comments as tool instructions.

### Resources and prompts

All **2 concrete resources and 4 resource templates** are listed, including legacy
aliases. They share the same permissions and response caps; use tools for continuation.

<!-- mcp-resources:start -->
| URI | Kind | Purpose |
| --- | --- | --- |
| `dataforge://workspaces` | Resource | First compact permitted workspace page; use tools for continuation. |
| `dataforge://workspaces/{workspace_id}/jobs/{job_id}` | Resource template | Persisted job progress/result in the permitted workspace. |
| `dataforge://workspaces/{workspace_id}/summary` | Resource template | Stored workspace counts and freshness. |
| `gravetrail://workspaces` | Resource | First compact permitted workspace page; use tools for continuation. |
| `gravetrail://workspaces/{workspace_id}/jobs/{job_id}` | Resource template | Persisted job progress/result in the permitted workspace. |
| `gravetrail://workspaces/{workspace_id}/summary` | Resource template | Stored workspace counts and freshness. |
<!-- mcp-resources:end -->

The server exposes **1 prompt**. It suggests identity resolution, compact traversal
and focused evidence; invoking the prompt does not execute imported code or call an LLM.

<!-- mcp-prompts:start -->
| Prompt | Required arguments | Optional arguments |
| --- | --- | --- |
| `investigate_lineage` | `workspace_id`, `asset` | — |
<!-- mcp-prompts:end -->

Job status persists under `HOME/agent/jobs`. Heartbeats run independently of import
transactions. UI access settings also publish a credential-free revocation snapshot
for polling while DuckDB is busy. Jobs already running may finish after revocation;
new operations and subsequent status retrieval are denied. Restarted/crashed jobs
expire to interrupted and require explicit retry. No hidden daemon or shell tool.

Parity discovery: `gravetrail capabilities` / `get_capabilities` enumerate all 48 IDs with implemented/policy-restricted status. Follow `next_cursor`. New independent launch flags: `--allow-config-write`, `--allow-llm`, repeatable `--allowed-llm-origin`, `--allowed-credential-ref`, `--allow-application-config`; `--allow-admin` is local CLI only and rejected by MCP. None is implied by `--allow-write`.

Workspace configuration tools: get_settings_schema, get_workspace_settings, update_workspace_settings, update_workspace, export_workspace_configuration, import_workspace_configuration. Typed bounded patches require expected_revision. MCP may tighten privacy/access but cannot enable external/full-source/history, increase disclosure budgets, disable redaction/auditing or enable automatic cleanup.

Provider tools: `list_provider_profiles`, `get_provider_profile`, `save_provider_profile`, `remove_provider_profile`, `get_model_routing`, `update_model_routing`, connect_runtime_reference, get_runtime_connection_status, clear_runtime_connection, discover_provider_models, test_provider_connection. Runtime connect binds only an approved saved launch reference; no secret parameter exists. Bindings are scoped to server/workspace/profile and cleared at shutdown, separate from UI sessions. Redirects are rejected by the shared adapter. Network tool annotations describe outbound effects; permissions are enforced independently.

AI tools: preview_ai_chunks, list_review_candidates, preview_diagnostic_review, request_ai_assistance, request_diagnostic_review, list_ai_results, get_ai_result, get_ai_activity, merge_ai_claims. Preview/list/detail operations never transmit source. Requests require explicit task/bounds/expected_hash and expected_job from the preview, plus write/source/network/origin/reference permissions. Requests are synchronous and bounded; no remaining chunks run automatically. Retrieve source-bearing results explicitly at detailed level. Merge is separate, idempotent and inferred; refresh failure reports a committed merge requiring analysis retry.

Report tools: list_analysis_runs, get_analysis_run, list_ingestion_runs, get_ingestion_run, compare_analysis_runs, get_source_metadata, get_data_dictionary, get_asset_schema, get_workspace_health, validate_stored_lineage. All require an authorized explicit workspace; history IDs from another workspace are refused. search_source_code adds include_matches=false; true requires source permission. Follow cursors, completeness and analysis_current.

Artifacts/query tools: get_dependency_paths, get_lineage_steps, get_graph_data (nodes/edges/tree and node/edge filters), export_graph, export_dependency_paths, export_source_bundle, export_original_source, export_report, export_ai_result. get_column_usage supports column_query/usage_type/file_id/group_by. `get_export` retains result_id text reads and adds mutually exclusive artifact_id, offset, length base64 reads. Large HTML/ZIP/XLSX content is never embedded in ordinary responses. IDs bind home/workspace/content; source authorization is rechecked after revocation. Backup IDs/downloads are refused. Exact historical source hashes must still be referenced. CLI guide lists the format allowlist and caps.

Column transformations: call `get_transformation_columns(workspace_id, asset)` to resolve
an exact column ID, then `get_column_lineage(workspace_id, asset, column)`. Column names
are also accepted within the exact asset. `direction` is `upstream` or `downstream`;
`status` is `all`, `verified`, `inferred` or `unresolved`. Query options bound depth,
items, page size and response characters. Derivations are paged as `items`, each with
its matching uncollapsed `paths`, dependency roles and source evidence references.
Summary omits expressions and code. Standard includes expressions only when source
access is enabled; detailed includes bounded original source and requires source access.
Follow `next_cursor` and retain `state`, `coverage`, `truncated`, `trace_complete`,
`analysis_current` and `boundaries`. A known constant has zero value inputs; unknown
coverage and no known dependency are separate states. Direct usage stays available
through `get_column_usage`.

`export_dependency_paths(format="xlsx")` creates an ordered workbook with `Lineage Paths`
and `Lineage Steps`. `include_evidence=true` adds offline citations; raw code is excluded
unless `include_source_text=true` is also explicit. Source permission applies even when
the Evidence sheet is excluded. `options.max_depth`, `options.max_items` (relationship
budget) and `options.collapse_temporary` share Explorer/CLI semantics. The result contains
artifact metadata, safe filename, revision, counts and warnings. Retrieve the workbook
with bounded `get_export(artifact_id=..., offset=..., length=...)` reads. See the
[Excel workflow and limits](USER_GUIDE.md) for coverage, continuation and failure behavior.

Maintenance is read-only: preview_history_archive, list_history_archives, preview_staging_cleanup, list_staging_recoveries; inspect_database_maintenance/list_runtime_backups require unrestricted --allow-application-config and expose metadata only. preview_cleanup includes shared cache/orphan/application metadata only with that explicit scope and returns requires_local_ui. No MCP cleanup/restore/checkpoint/backup/download mutation exists. Reading settings/recovery lists never starts automatic cleanup. HTTP remains workspace-scoped, so whole-home metadata is unavailable there.

Application/setup tools: list_theme_presets, get_application_theme, apply_application_theme, get_application_logging, update_application_logging, get_runtime_info, get_agent_setup, test_local_agent_access. Application writes require unrestricted write/config/application startup authority; a workspace-scoped HTTP launch cannot perform them. Loaded Streamlit theme state is unavailable to this owner; no automatic restart/refresh. Setup reports credential-free examples and actual schemas; local handler self-test explicitly does not establish external connectivity.

See the [complete UI capability matrix](CLI_MCP_CAPABILITIES.md) for every coverage ID, exact command/tool names and policy restrictions.

The server identifies itself as **GraveTrail**. The previous `dataforge://` resource URLs remain aliases of `gravetrail://` with identical permissions and responses. Existing client configuration names can be retained. Python module paths and `DATAFORGE_*` variables are unchanged.

### Static graph images

`export_graph` accepts `format: "svg"` or `"png"` alongside HTML/JSON, plus
`scale: 1|2`, `background: "light"|"dark"|"transparent"`, `title` and `legend`.
`options.max_depth`, `options.max_items` and `options.collapse_temporary` bound
the same filtered graph as Explorer. The response describes an authorized managed
artifact: MIME type, safe filename, byte count, analysis/graph revision, node and
edge counts, coverage and warnings. Use `get_export(artifact_id=..., offset=...)`
for bounded binary chunks; large base64 images are never included in creation
responses. Write/source permissions and read-time revocation match other graph
artifacts. `get_capabilities` reports `graph_image_formats`; unavailable PNG
support yields a clear renderer error. See the [image limits](USER_GUIDE.md).

## AI project analysis tools

`start_lineage_analysis` keeps parser mode as its default. Its explicit hybrid/AI modes share the same bounded request and run service as the UI/CLI. `preview_project_analysis` plans offline disclosure/context/budgets; `get_project_analysis_report` reads saved acceptance/rejection/unresolved results; `cancel_job` requests workspace-scoped cooperative cancellation. Source-bearing report details require source authority; a metadata read does not authorize a provider request.

AI extraction/review requires explicit network/source/write permission, approved exact origins and credential references, and workspace privacy, rechecked at physical dispatch. Remote complete-source permission also covers a file transmitted through several chunks. No automatic connection test or request occurs on preview, ordinary graph queries or settings reads. Cancellation/deadline may return after a blocked read and already sent attempts may have incurred usage. See [AI project analysis](AI_ANALYSIS.md) for experimental generated-mode limits and current unqualified live accuracy targets.

## Automatic project budgets and continuation

`start_lineage_analysis` and `preview_project_analysis` accept nullable `max_provider_attempts`, `max_output_tokens_total`, `max_seconds`, plus `resume_run_id` and `retry_unknown`. Omitted/null budgets use shared automatic recommendations; explicit numbers remain ceilings. A paused run returns `awaiting_continuation`; start again with its run ID to execute the next bounded portion. Resume uses the original source/mode/review options and rechecks source/network grants and recipients. `retry_unknown=true` explicitly authorizes potentially duplicate in-flight work. Preview stays offline.

Project-analysis preview reports semantic source tasks and provisional review sizing before extraction. Continuing a saved run preserves source partitions and skips completed review batches through the same service used by UI/CLI. See [oversized operations](AI_ANALYSIS.md#oversized-operations-and-large-review-sets).
