# Connect your tools

The Streamlit UI, CLI, and MCP server call the same application services and query the
same stored analysis. Deterministic investigation works without a provider. Optional AI
uses configured profiles and explicit privacy permissions.

## Choose an interface

| Interface | Best for | Reference |
| --- | --- | --- |
| CLI | Shell automation, JSON queries, controlled imports/analysis, local administration | [CLI guide](../CLI_GUIDE.md) |
| MCP stdio | A local AI client querying a dedicated data home | [MCP setup](../MCP_INTEGRATION.md) |
| MCP Streamable HTTP | Private clients with bearer authentication and workspace scope | [MCP transport and permissions](../MCP_INTEGRATION.md) |
| Provider profiles | Optional source explanation, diagnostic assistance, and grounded lineage claims | [LLM providers](../LLM_INTEGRATION.md) |

There is no standalone REST API. MCP's HTTP transport exposes MCP, not an unrestricted
web API. The [capability matrix](../CLI_MCP_CAPABILITIES.md) records implemented routes
and explicit policy restrictions, including read-only MCP maintenance and local-admin cleanup.

## Query before reading source

```sh
uv run gravetrail --help
uv run gravetrail --home ./automation-data --json workspace list
```

With an analyzed home, resolve the workspace and asset IDs first. Check freshness,
completeness and cursors, then request bounded graph/column/report results. Retrieve
source evidence only when needed. Start from the [agent workflows](../AGENT_WORKFLOWS.md)
and [response budget guidance](../TOKEN_OPTIMIZATION.md) for complete examples.

## Automate a workspace workflow

| Task | CLI | MCP |
| --- | --- | --- |
| Import selected files, inspect analysis attempts, download evidence | [Source and graph workflows](../CLI_GUIDE.md#source-graph-and-builder-workflows) | [Source, graph and Builder tools](../MCP_INTEGRATION.md#source-graph-and-builder-tools) |
| Import schemas, edit a design or save a named snapshot | [Builder workflow](../CLI_GUIDE.md#source-graph-and-builder-workflows) | [Builder tools](../MCP_INTEGRATION.md#source-graph-and-builder-tools) |
| Preview a migration, resume a file stage, review a diff or export a dbt pilot | [Guided AI migration](../CLI_GUIDE.md#guided-ai-migration) | [Guided AI migration](../MCP_INTEGRATION.md#guided-ai-migration) |

One process owns each DuckDB home. Stop the UI before a separate CLI/MCP process opens
that home, or give automation its own home. Pass an explicit `--home` consistently.
Read-only is the launch default; write, configuration, network and application grants
are independent. An agent cannot grant itself broader access.

## Configure AI deliberately

Use **Connections & AI → Providers & routing** to create profiles and assign tasks. Use masked
session credentials or named read-only launch variables. Profile persistence stores
references, never secret values. Clear session credentials when finished.
Project Lineage has its own routing assignment. Clear any assignments that use a profile before
removing it.

Remote requests need privacy permission; full source disclosure has its own control.
Output must validate against known files, quotes and line ranges before explicit merge.
Model confidence alone never makes a dependency verified.

- [Provider protocols and coverage](../LLM_INTEGRATION.md)
- [Secure credential configuration](../SECURE_CONFIGURATION.md)
- [Prompt architecture and schemas](../PROMPT_ENGINEERING.md)
