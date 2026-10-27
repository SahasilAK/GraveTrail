# src/dataforge/agent/

Direct-column responses expose source-free `usage_coverage` completeness/reasons before
display filtering. Column lineage retains multiple effect paths per derivation under
existing detail/source permissions and response limits.

`cli_dbt.py` registers project/resource/detail/dependency commands over DbtOperations.
Capability DBT01, four MCP dbt reads and explicit ingestion options share existing
workspace/source/write/root permissions and cursor budgets.

Shared authorized automation layer. CLI and MCP delegate to the existing services,
Store, Importer, LineageGraph, exports and explicit opt-in grounded AI; imported source is never executed.

## Files
- `__init__.py` — Package marker.
- `contracts.py` — AccessPolicy, QueryOptions, AgentSettings, AgentError and compact JSON;
  credential-free workspace revocation snapshots support polling while DuckDB is busy.
- `service.py` — AgentService routes workspace/import/build/search/lineage/columns/source/
  impact/batch/export/jobs; column_catalog and column_lineage page shared transformation queries with source-gated expressions/code and per-derivation paths. Applies scope, source disclosure, freshness, budgets and audit.
- `paging.py` — Query/revision-bound cursors and whole-record serialized character budgets.
- `jobs.py` — Two-worker local jobs, one per workspace; atomic JSON journals, heartbeat expiry,
  bounded status/results and explicit terminal states; Windows reader/replacement retries.
- `worker.py` — Fixed detached CLI job entry point; rechecks authorization, never shell commands.
- `mcp_server.py` — Official SDK typed async tools, resources, prompt; one structured payload,
  independent stdio and bearer-protected Streamable HTTP with explicit workspace restrictions. Read-only get_transformation_columns/get_column_lineage share CLI/service bounds and disclosure policy.

Runtime artifacts stay under HOME/agent; no schema migration. DuckDB has one process owner.
Read-only is the startup default. Settings may revoke access/source/writes; source code
requires an explicit evidence request or detailed response. Polling avoids long transactions.
# Maintenance integration

AgentService exposes cleanup inspect/preview and policy-gated confirmed apply; restricted
workspace policies cannot create whole-home backups. MCP registers inspect/preview only,
never a destructive cleanup tool. CLI applies fresh saved previews with explicit confirmation and mandatory full-home backup.

- `capabilities.py` — 48-ID UI parity inventory, paginated discovery with implemented equivalents and explicit policy restrictions; launch config/network/application grants are independent.

- `cli_settings.py` — explicit settings/schema and workspace identity/configuration Typer adapters; no arbitrary key execution.

- `cli_ai.py` — Explicit providers/routing/runtime-reference and AI/review/result Typer adapters; hidden credentials are per invocation only.
- `cli_reports.py` — Stored reports, managed artifacts, permitted local history/staging/backup operations; bounded JSON preview loading. export paths --format xlsx offers explicit evidence/source options; MCP export_dependency_paths shares them and retrieves bytes through get_export.

Long provider/request/merge operations avoid holding Store.lock across network or analysis waits;
per-request admission is immediate. Storage APIs retain their own locks; merge locks only checking/commit.
MCP cannot accept local-admin launches or register maintenance mutations. Capability routes are checked
against actual help/schemas by the keyed parity fixture.

MCP identifies as GraveTrail; gravetrail:// and legacy dataforge:// workspace/summary/job resources share handlers and permissions. Setup emits mcp_servers.gravetrail/client names while retaining dataforge.cli module paths.

Managed job thread names use gravetrail-agent; journals, IDs and worker module paths are unchanged.

Graph images: export graph adds SVG/PNG, scale/background/title/legend and local --output; MCP export_graph shares options and get_export chunks/revocation. capabilities reports graph_image_formats based on renderer importability. CLI refuses existing/invalid destinations before artifact creation.

Project analysis delegates preview/build/report to project_analysis.py and analysis_service.py.
MCP start_lineage_analysis accepts parser/hybrid/ai plus explicit budgets/review/refresh;
preview_project_analysis/get_project_analysis_report/cancel_job share policy checks. Jobs
preserve complete launch grants in detached workers, journal source-free stages and use
cooperative cancellation markers without opening DuckDB in polling processes. No automatic
billable resume after owner restart. Exact profile bindings isolate shared credential refs.

Project preview/start accept nullable automatic execution limits, pinned `resume_run_id` and explicit `retry_unknown`. Actual HTTP SDK regression covers bounded start, poll and continuation; resumed parser-default entry routes to the original AI mode with source/network checks.

Job journals add created_at/started_at/stage_started_at/finished_at epoch times. Heartbeats preserve stage timers; terminal completion freezes elapsed time. Legacy journals remain readable; no source/credential timer metadata.
