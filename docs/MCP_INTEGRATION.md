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

The complete registered interface has **98 tools**.
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
| `create_migration_project` | `expected_pin`, `name`, `workspace_id` | `setup` |
| `create_workspace` | `name` | `description` |
| `discover_provider_models` | `workspace_id` | `draft_profile`, `options`, `profile_id` |
| `export_ai_result` | `record_id`, `workspace_id` | `options` |
| `export_dependency_paths` | `asset`, `workspace_id` | `direction`, `format`, `include_evidence`, `include_source_text`, `max_paths`, `options` |
| `export_graph` | `workspace_id` | `all_assets`, `asset`, `background`, `direction`, `format`, `legend`, `options`, `scale`, `title` |
| `export_migration_bundle` | `project_id`, `revision_id`, `workspace_id` | `image_format`, `include_sources`, `pilot`, `reviewed`, `workbook` |
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
| `get_column_usage` | `asset`, `workspace_id` | `column_query`, `file_id`, `group_by`, `options`, `usage_type`, `view` |
| `get_data_dictionary` | `workspace_id` | `options`, `query` |
| `get_dependency_paths` | `asset`, `workspace_id` | `direction`, `max_paths`, `options` |
| `get_export` | `workspace_id` | `artifact_id`, `format`, `length`, `offset`, `options`, `result_id` |
| `get_graph_data` | `workspace_id` | `all_assets`, `asset`, `direction`, `edge_id`, `node_id`, `options`, `view` |
| `get_ingestion_run` | `ingestion_id`, `workspace_id` | `options` |
| `get_job_status` | `job_id`, `workspace_id` | `options` |
| `get_lineage` | `asset`, `workspace_id` | `direction`, `options` |
| `get_lineage_batch` | `assets`, `workspace_id` | `direction`, `options` |
| `get_lineage_steps` | `workspace_id` | `all_assets`, `asset`, `direction`, `options` |
| `get_model_routing` | `workspace_id` | `options` |
| `get_project_analysis_report` | `workspace_id` | `options`, `run_id` |
| `get_provider_profile` | `profile_id`, `workspace_id` | `options` |
| `get_runtime_connection_status` | `profile_id`, `workspace_id` | `options` |
| `get_runtime_info` | — | `options`, `workspace_id` |
| `get_settings_schema` | `workspace_id` | `section` |
| `get_source_evidence` | `workspace_id` | `content_hash`, `end_line`, `file_id`, `full`, `operation_id`, `options`, `start_line`, `statement_id` |
| `get_source_metadata` | `file_id`, `workspace_id` | `options` |
| `get_transformation_columns` | `asset`, `workspace_id` | `options` |
| `get_workspace_health` | `workspace_id` | `options` |
| `get_workspace_settings` | `section`, `workspace_id` | — |
| `get_workspace_summary` | `workspace_id` | — |
| `import_workspace_configuration` | `configuration` | — |
| `ingest_sources` | `extensions`, `path`, `workspace_id` | `dbt_options`, `files`, `source_kind`, `sql_dialect` |
| `list_dbt_projects` | `workspace_id` | `options` |
| `list_dbt_resources` | `workspace_id` | `project_id`, `resource_types`, `options` |
| `get_dbt_resource` | `workspace_id`, `resource_id` | `options` |
| `trace_dbt_dependencies` | `workspace_id`, `resource_id` | `direction`, `relationship_kinds`, `max_depth`, `options` |
| `inspect_cleanup` | `workspace_id` | — |
| `inspect_database_maintenance` | — | `options` |
| `inspect_migration_revision` | `project_id`, `workspace_id` | `anchor`, `finding`, `item`, `line`, `offset`, `options`, `revision_id`, `view` |
| `list_ai_results` | `workspace_id` | `options` |
| `list_analysis_runs` | `workspace_id` | `options` |
| `list_history_archives` | `workspace_id` | `options` |
| `list_ingestion_runs` | `workspace_id` | `options` |
| `list_migration_projects` | `workspace_id` | `options` |
| `list_migration_targets` | `workspace_id` | `options` |
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
| `preview_migration_ai` | `models`, `profile_id`, `project_id`, `purpose`, `revision_id`, `workspace_id` | `dependencies`, `message`, `offset`, `options` |
| `preview_migration_stage` | `profile_id`, `project_id`, `revision_id`, `source_id`, `stage`, `workspace_id` | `feedback`, `offset`, `options`, `static_reference` |
| `preview_migration_edit` | `arguments`, `project_id`, `revision_id`, `workspace_id` | `options` |
| `preview_migration_project` | `name`, `workspace_id` | `options`, `setup` |
| `preview_project_analysis` | `workspace_id` | `file_ids`, `max_output_tokens_total`, `mode`, `output_share`, `input_token_limit`, `output_token_limit`, `resume_run_id` | Shared static/AI analysis service |
| `preview_staging_cleanup` | `workspace_id` | `age_hours`, `options` |
| `remove_provider_profile` | `expected_revision`, `profile_id`, `workspace_id` | `options` |
| `request_ai_assistance` | `expected_hash`, `file_id`, `first`, `last`, `task`, `workspace_id` | `expected_job`, `options`; `expected_request` |
| `request_diagnostic_review` | `diagnostic_id`, `expected_hash`, `first`, `last`, `workspace_id` | `expected_job`, `options`; `expected_request` |
| `request_migration_ai` | `expected_pin`, `models`, `profile_id`, `project_id`, `purpose`, `revision_id`, `workspace_id` | `dependencies`, `message`, `options` |
| `run_migration_stage` | `expected_pin`, `profile_id`, `project_id`, `revision_id`, `source_id`, `stage`, `workspace_id` | `background`, `feedback`, `options`, `static_reference` |
| `save_provider_profile` | `expected_revision`, `profile`, `workspace_id` | `options`, `profile_id` |
| `search_assets` | `workspace_id` | `options`, `query` |
| `search_source_code` | `workspace_id` | `include_matches`, `options`, `query` |
| `start_lineage_analysis` | `workspace_id` | `file_ids`, `force`, `max_output_tokens_total`, `mode`, `output_share`, `input_token_limit`, `output_token_limit`, `resume_run_id`, `retry_unknown` | Shared static/AI analysis service |
| `start_migration_conversion` | `expected_revision`, `project_id`, `workspace_id` | `plan_only`, `reconvert` |
| `test_local_agent_access` | `workspace_id` | `options` |
| `test_provider_connection` | `workspace_id` | `draft_profile`, `options`, `profile_id` |
| `update_application_logging` | `level` | `options` |
| `update_migration_revision` | `arguments`, `operation`, `project_id`, `revision_id`, `workspace_id` | — |
| `update_model_routing` | `expected_revision`, `values`, `workspace_id` | `options` |
| `update_workspace` | `description`, `expected_revision`, `name`, `workspace_id` | — |
| `update_workspace_settings` | `expected_revision`, `section`, `values`, `workspace_id` | — |
| `validate_stored_lineage` | `workspace_id` | `options` |
| `apply_builder_document` | `expected_revision`, `workspace_id` | `document`, `path` |
| `export_builder` | `workspace_id` | `format`, `kind`, `role`, `table_ids`, `work_id` |
| `get_project_analysis_attempt_content` | `attempt_id`, `run_id`, `workspace_id` | `kind`, `length`, `offset`, `options` |
| `import_builder_schemas` | `expected_pin`, `paths`, `workspace_id` | `dialect` |
| `import_builder_snapshot` | `name`, `workspace_id` | `document`, `path` |
| `inspect_builder` | `workspace_id` | `options`, `table_id`, `view`, `work_id` |
| `inspect_provider_model` | `workspace_id` | `draft_profile`, `model`, `options`, `profile_id` |
| `list_project_analysis_attempts` | `run_id`, `workspace_id` | `offset`, `options` |
| `list_project_analysis_runs` | `workspace_id` | `options` |
| `list_source_files` | `workspace_id` | `options`, `query` |
| `load_builder_snapshot` | `expected_revision`, `work_id`, `workspace_id` | — |
| `preview_builder_schema_import` | `paths`, `workspace_id` | `dialect`, `options` |
| `preview_builder_table_deletion` | `table_ids`, `workspace_id` | `options` |
| `reset_provider_profile_limits` | `expected_revision`, `profile_id`, `workspace_id` | `options` |
| `save_builder_snapshot` | `expected_revision`, `workspace_id` | `clear`, `name`, `work_id` |
| `start_sql_example` | `workspace_id` | — |
| `update_source_dialect` | `file_id`, `workspace_id` | `sql_dialect` |
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

The history, staging and shared-storage maintenance tools are read-only. `inspect_database_maintenance` and `list_runtime_backups` require unrestricted `--allow-application-config` and return metadata only. `preview_cleanup` returns shared cache, orphan, and application metadata with that explicit scope and marks apply as `requires_local_admin`. Use the guarded local CLI for cleanup, restore, checkpoint, and backup operations. HTTP remains workspace-scoped.

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

`start_lineage_analysis` defaults to `parser`; `ai` uses independent persisted file
extraction. `preview_project_analysis` remains offline and source-authorized.
Both accept the same file selection and optional `max_output_tokens_total` run
ceiling as the UI/CLI. Model token capacity comes from the selected provider
profile. Hybrid, review, character/window/parallel and project-window options are
removed. The schema rejects old options rather than silently reinterpreting them.

`get_project_analysis_report` reads historical and new reports; detailed evidence
requires source authority. `cancel_job` cancels cooperatively. Resume compatible
runs with `resume_run_id`; acknowledge a possibly billed lost response using
`retry_unknown`. Source/configuration/prompt/model changes block continuation.
Historical paused protocols require a new build. See [AI analysis](AI_ANALYSIS.md).

Start/preview also accept optional `output_share` (10–50, default 30 for new runs),
`input_token_limit` and `output_token_limit`, using the same allocator and precedence
as the UI/CLI. Omitted fields preserve resumed choices. A committed partial run
with unresolved required work can resume to retry only those items; completed
checkpoints and cumulative reservations are retained.

Focused AI previews return budget diagnostics and `request_fingerprint`. Pass it as `expected_request` to either request tool to bind dispatch to that exact prepared selection/profile/context. Both request tools share source-backed resource proposals and explicit `merge_ai_claims` acceptance; advisory tasks cannot merge.

## Source, graph and Builder tools

`start_sql_example` loads the bundled SQL example into an empty source inventory and returns
a job ID. Use `get_job_status` to retrieve the starting asset for exploration.
`ingest_sources` accepts one file or a first file plus additional paths in `files`.
Import paths must be under an approved root.

Set `all_assets` on graph and lineage-step tools to inspect a whole workspace.
For a whole-workspace source bundle, set it in the export selection. Use
`export_report` with kind `column-lineage`, an asset, and a column for a trace artifact.
`get_source_evidence` accepts a retained `content_hash` for historical source reads.
Use `get_graph_data` with `view: "columns"` or `view: "column-links"` for the
graph's column overlay. Use `get_column_usage` with `view: "used"` or
`view: "unused"` for coverage-aware name lists.

`list_project_analysis_runs` lists AI analysis runs. `list_project_analysis_attempts`
lists planned and dispatched work. Use `get_project_analysis_attempt_content` to page
through the retained input, output, decoded response, or diagnostics with source access.

`inspect_builder` lists tables, columns, links, folders, or named work. Use the revision
from inspection with `apply_builder_document` to save an edited document or
`load_builder_snapshot` to restore a saved one. Use
`preview_builder_schema_import` and its pin with `import_builder_schemas` for
schema files under an approved import root. `export_builder` creates a managed
document, diagram, or schema artifact. Retrieve it with `get_export`.
Use `update_source_dialect` to update a retained SQL file's parsing override or remove
the override by omitting the dialect.

Tools for inspecting or testing providers accept a saved profile or an unsaved draft.
They apply the same origin and credential-reference checks. Native credential persistence
and destructive shared-storage cleanup use local-admin CLI commands.
`reset_provider_profile_limits` applies recommendations to a saved profile without
contacting the provider.

## Migration tools

The [app walkthrough](user-guide/migration.md#watch-the-workflow) shows the revision, review evidence
and pilot scope that these tools expose.

1. Call `list_migration_targets` for supported profiles and the current Analysis and Lineage Builder
   revisions. Use `list_migration_projects` to find an existing project.
2. Call `preview_migration_project` with a name and `setup`. Set `selection` to ingested file IDs,
   `analysis_run` to a committed run ID or `latest`, or `builder_revision` to a revision ID or
   `current`. Use `selected_outputs` with an analysis run and `builder_tables` with a Builder
   revision to narrow the plan. `dialects` can override an ingested SQL file's dialect by ID.
   Target fields include `format`, `warehouse`, `profile`, `catalog`, `schema`, and `materialization`.
   A setup without an explicit selection or a Builder revision picks supported workspace sources.
   Pass the same name and setup to `create_migration_project` with the returned `pin` as `expected_pin`.
3. Call `start_migration_conversion` with the current `expected_revision` and `plan_only: true`
   for [guided AI migration](#guided-ai-migration). Use `get_job_status` to wait for the published
   revision ID. Omit `plan_only` for offline static conversion. Set `reconvert` to regenerate
   a static draft from the pinned snapshot.
   Use `inspect_migration_revision` to inspect the result, including its scope, findings,
   original and migrated lineage, schemas, reviews, and evidence. Use the `artifact` view with
   an artifact ID in `item` and `anchor` set to `generated`, `source`, or `annotated` to read code.
   Use `view: "pilot"` with comma-separated model IDs in `item` to preview dependency closure.
4. Call `preview_migration_edit` with `arguments` containing `replacements` (model IDs mapped to
   SQL), `rationale`, and optional `scopes`. For an ordered SAS draft, provide `model` and `order`.
   For a large replacement map, use `replacements_path` under an approved import root.
   To review an existing AI proposal, pass `proposal`. Apply through `update_migration_revision`
   with `operation: "apply"` and `arguments` containing the previewed `proposal` and `expected_pin`.
   For a large proposal, save the proposal object as JSON under an approved import root and use
   `proposal_path` for preview and apply.
5. Use `export_migration_bundle` with an explicit revision. Set `reviewed` for a reviewed handoff
   and include `pilot` model IDs for a dependency-closed subset. Set `image_format` and `workbook`
   to add a lineage image and mapping/type details. Fetch the ZIP with `get_export` and its
   `artifact_id`. Follow `next_offset` until all bytes are retrieved and verify the SHA-256.

Use `options.cursor` for list pages. For a text response, pass `next_offset` back as `offset`
to the same revision and view. For `preview_migration_edit`, place `offset` in `arguments`.
If the result has `encoding: "json"`, concatenate the `text` chunks before parsing them.
Setup, conversion, edits, evidence views, and bundle creation and retrieval require the workspace's
source permission. Project lists, revision summaries and revision history are metadata reads.

`preview_migration_ai` prepares an offline disclosure for 1–50 model IDs and the selected
provider profile. Review the full result, following `next_offset` if needed. Dispatch only
with the same inputs and the returned `pin` as `expected_pin` in `request_migration_ai`.
The request requires startup write and network grants, a permitted origin and credential reference,
and current workspace write, source and privacy permissions. AI suggestions go through the
same patch preview and apply flow as manual edits. Set `options.max_chars` within the workspace's
cap if the reply needs more room. With AI history enabled, inspect saved replies with `view: "ai_responses"`.

### Guided AI migration

After preparing with `plan_only: true`, read the source
IDs with `inspect_migration_revision` and `view: "workflow"`. Each file goes through `convert`,
`validate`, and `optimize`. Call `preview_migration_stage` for each disclosure, then pass its
pin to `run_migration_stage`. Use `static_reference` during conversion to include a static draft.
Set `background: true` to get a cancellable job. Preview again after a partial stage result
or an interruption. Completed parts are saved with the project.
Use `view: "lineage_comparison"` for missing and extra edges. The artifact view accepts a
line or finding ID for focused evidence. `preview_migration_edit` also accepts `mapping_csv`.
Use `update_migration_revision` with `skip_optimization` and `source_id` to continue directly to
review. Inspect the workflow with the source ID in `item` to see the staged diff and apply pin.
Use `apply_source_draft` with `source_id` and `expected_pin` to apply it. The export's
`include_sources` option adds the full retained text separately from dbt models.

### Review and external evidence

Run dbt and comparison checks in your controlled environment. Import external evidence through
`update_migration_revision`. Pass inline evidence as UTF-8 text or use an approved path under a
configured import root. Streamable HTTP requests have a 64 KiB body cap. Each evidence import
stays bound to its revision. Runtime observations, reconciliation, and engineer review are recorded
separately. See the [Migration user guide](user-guide/migration.md) for the handoff workflow.

| `operation` | Fields in `arguments` |
| --- | --- |
| `resolve_scope` | `region_id`, `reason`, optional `external` relation with `catalog`, `schema`, `identifier`, `owner`, and `columns` |
| `set_contract` | `model`, `inputs`, `behavior`, `prerequisites`, optional `relations` |
| `apply` | `expected_pin` and either `proposal` or `proposal_path` |
| `apply_source_draft` | `source_id`, `expected_pin` from the workflow inspection |
| `skip_optimization` | `source_id` |
| `revise_schemas` | `settings` containing `types`, `input_types`, or `source_mappings` |
| `bulk_mappings` | `csv` or `path`, using the `source_mappings_template` view |
| `import_schema` | `group` (model or physical source ID) and either `filename` with `content`, or `path`. Optional `types` map supplements the imported columns. |
| `configure_validation` | `model`, `values` with `not_null`, `unique`, `relationship`, or `comparison`, optional `merge_keys` |
| `import_validation` | `manifest` or `manifest_path`, and `run_results` or `results_path` from the same dbt invocation |
| `import_reconciliation` | `csv` or `path`, using the `reconciliation_template` view |
| `record_review` | `model`, `reviewer`, `rationale`, `obligations` |
| `restore` | `prior_revision` |
| `add_comment` | `artifact`, `anchor` (`source`, `generated`, or `section`), `line` (use `null` for `section`), `author`, `message` |
| `resolve_comment` | `comment_id` |
| `save_lesson` | `lesson` with `kind`, `pattern`, `guidance`, `example`, `counterexample`, and `owner`. Optional lesson fields are `scope`, `dialect`, and `required_types`. Pass `evidence_model` and optionally `replaces`. |
| `revoke_lesson` | `lesson_id` |
