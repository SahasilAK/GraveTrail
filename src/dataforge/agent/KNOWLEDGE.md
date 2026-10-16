# src/dataforge/agent/

Shared deterministic automation layer. CLI and MCP delegate to the existing services,
Store, Importer, LineageGraph and exports; no source execution or LLM requests.

## Files
- `__init__.py` — Package marker.
- `contracts.py` — AccessPolicy, QueryOptions, AgentSettings, AgentError and compact JSON;
  credential-free workspace revocation snapshots support polling while DuckDB is busy.
- `service.py` — AgentService routes workspace/import/build/search/lineage/columns/source/
  impact/batch/export/jobs; applies scope, source disclosure, freshness, budgets and audit.
- `paging.py` — Query/revision-bound cursors and whole-record serialized character budgets.
- `jobs.py` — Two-worker local jobs, one per workspace; atomic JSON journals, heartbeat expiry,
  bounded status/results and explicit terminal states; Windows reader/replacement retries.
- `worker.py` — Fixed detached CLI job entry point; rechecks authorization, never shell commands.
- `mcp_server.py` — Official SDK typed async tools, resources, prompt; one structured payload,
  independent stdio and bearer-protected Streamable HTTP with explicit workspace restrictions.

Runtime artifacts stay under HOME/agent; no schema migration. DuckDB has one process owner.
Read-only is the startup default. Settings may revoke access/source/writes; source code
requires an explicit evidence request or detailed response. Polling avoids long transactions.
