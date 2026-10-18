# src/dataforge/agent/

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

- `capabilities.py` — 46-ID UI parity inventory, paginated discovery with implemented equivalents and explicit policy restrictions; launch config/network/application grants are independent.

- `cli_settings.py` — explicit settings/schema and workspace identity/configuration Typer adapters; no arbitrary key execution.

- `cli_ai.py` — Explicit providers/routing/runtime-reference and AI/review/result Typer adapters; hidden credentials are per invocation only.
- `cli_reports.py` — Stored reports, managed artifacts, permitted local history/staging/backup operations; bounded JSON preview loading. export paths --format xlsx offers explicit evidence/source options; MCP export_dependency_paths shares them and retrieves bytes through get_export.

Long provider/request/merge operations avoid holding Store.lock across network or analysis waits;
per-request admission is immediate. Storage APIs retain their own locks; merge locks only checking/commit.
MCP cannot accept local-admin launches or register maintenance mutations. Capability routes are checked
against actual help/schemas by the keyed parity fixture.

MCP identifies as GraveTrail; gravetrail:// and legacy dataforge:// workspace/summary/job resources share handlers and permissions. Setup emits mcp_servers.gravetrail/client names while retaining dataforge.cli module paths.

Managed job thread names use gravetrail-agent; journals, IDs and worker module paths are unchanged.
