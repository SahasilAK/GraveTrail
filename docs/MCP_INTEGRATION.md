# MCP integration

DataForge uses the official `mcp` Python SDK (locked 1.30.0). CLI, MCP and the UI
reuse Store, Importer, the analysis service, LineageGraph and exports. The adapters
contain no parser implementation. Normal queries use persisted facts and never
invoke an LLM or execute imported source.

## Recommended: local stdio

```bash
dataforge --home ./automation-data --allowed-workspace WORKSPACE_ID mcp
```

Launch from the installed environment, or use an absolute Python executable and
`-m dataforge.cli`. Stdio writes MCP JSON-RPC only to stdout; OS/process permissions
are its security boundary. Do not open the same home in another Streamlit/CLI/MCP
process. Settings supplies ready-to-copy configurations using actual absolute paths.

Codex `config.toml` example (replace paths and ID):

```toml
[mcp_servers.dataforge]
command = "D:/DataForge/.venv/Scripts/python.exe"
args = ["-m", "dataforge.cli", "--home", "D:/DataForge/automation-data", "--allowed-workspace", "WORKSPACE_ID", "mcp"]
```

Claude Code project `.mcp.json`:

```json
{
  "mcpServers": {
    "dataforge": {
      "command": "D:/DataForge/.venv/Scripts/python.exe",
      "args": ["-m", "dataforge.cli", "--home", "D:/DataForge/automation-data", "--allowed-workspace", "WORKSPACE_ID", "mcp"]
    }
  }
}
```

Alternatively register an installed CLI:
`claude mcp add --transport stdio dataforge -- dataforge --home ./automation-data mcp`.
Formats were checked against the [official Codex MCP guide](https://developers.openai.com/codex/mcp)
and [official Claude Code MCP guide](https://code.claude.com/docs/en/mcp) on 2026-10-16.
These are examples only; DataForge does not modify client configuration.

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
dataforge --home ./automation-data --allowed-workspace WORKSPACE_ID mcp --transport streamable-http --host 127.0.0.1 --port 8765
```

Endpoint: `http://127.0.0.1:8765/mcp`. Every request requires an Authorization
bearer header, including GET/POST/DELETE. Explicit workspace IDs are mandatory;
unauthenticated network startup is refused. For Codex HTTP configuration:

```toml
[mcp_servers.dataforge]
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
unencrypted backend. DataForge does not terminate TLS itself. DNS rebinding/Origin
checks remain enabled; external hostname comes from the declared public URL.
Request bodies cap at 64 KB, admitted HTTP requests at eight, and jobs at two.
SDK protocol/validation errors are bounded by the SDK; application errors omit
exception internals. HTTP access logging is disabled to keep source/credentials out.

## Discovery and tools

Tools use validated schemas, explicit workspace scoping and summary defaults:

| Tools | Purpose |
| --- | --- |
| `list_workspaces`, `create_workspace`, `get_workspace_summary` | Discovery/setup/counts |
| `ingest_sources`, `start_lineage_analysis`, `get_job_status` | Managed import and cached analysis |
| `search_assets`, `get_lineage`, `get_lineage_batch` | Exact identity and local traversal |
| `get_column_usage`, `analyze_impact` | Direct columns and downstream groups |
| `search_source_code`, `get_source_evidence` | Metadata-only search and explicit evidence |
| `get_analysis_issues` | Unresolved/failed diagnostic pages |
| `export_results`, `get_export` | Scoped artifact creation and explicit retrieval |

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

Resources: `dataforge://workspaces`,
`dataforge://workspaces/{workspace_id}/summary`,
`dataforge://workspaces/{workspace_id}/jobs/{job_id}`. They enforce the same
permissions and response caps; tools provide continuation. Prompt:
`investigate_lineage(workspace_id, asset)` suggests identity resolution, compact
traversal and focused evidence; it neither reads arbitrary files nor calls an LLM.

Job status persists under `HOME/agent/jobs`. Heartbeats run independently of import
transactions. UI access settings also publish a credential-free revocation snapshot
for polling while DuckDB is busy. Jobs already running may finish after revocation;
new operations and subsequent status retrieval are denied. Restarted/crashed jobs
expire to interrupted and require explicit retry. No hidden daemon or shell tool.
