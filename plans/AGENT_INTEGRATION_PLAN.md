# Agent & Automation Integration Implementation Plan

**Goal:** Add complete local CLI and compact MCP workflows while preserving the human-first UI.
**Spec:** `docs/prompts/FEATURE_AGENT_INTEGRATION.md`; master requirements remain authoritative.
**Architecture:** A presentation-free integration service delegates to Store, Importer, analyze,
LineageGraph and existing exports. Typer CLI and official Python MCP SDK are thin adapters.
Per-workspace settings can revoke access, writes and source retrieval. Startup policy narrows
workspace/import access further. Jobs and export artifacts live under DATAFORGE_HOME.
**Stack:** Python 3.11+, Typer, MCP Python SDK 1.x, existing DuckDB/NetworkX/SQLGlot/Streamlit.

## Constraints and decisions
- No imported code execution, external LLM calls or credentials persisted by integration.
- Summary output by default; explicit evidence/source requests; bounded pages, batches and code.
- Exact IDs or unambiguous names only; preserve extraction confidence and unresolved states.
- Read-only startup default; writes require both startup authorization and workspace permission.
- Network transport requires bearer authentication, explicit workspace allowlist and HTTPS for
  externally advertised endpoints. Stdio uses the launching user's OS permissions.
- DuckDB remains single-process-owned. Busy errors explain separate homes/stopping another owner;
  no unsafe concurrent writers or automatic database copying. MCP supports concurrent bounded jobs
  within its owner. CLI background workers acquire ownership after CLI exits.
- REST adds no necessary workflow beyond CLI/MCP and is intentionally omitted.
- Work in the existing checkout on a feature branch; preserve user edits and runtime homes.

## Review focus
Cross-workspace IDs/cursors/jobs; partial graph/depth and stale analysis; output budgets with
large single records; process death/job recovery; path traversal/symlinks and unauthenticated HTTP.

## Slice 1 — Shared automation service and CLI
Files: `src/dataforge/agent/{contracts,service,jobs}.py`, `src/dataforge/cli.py`, pyproject/lock;
tests: `tests/test_agent_service.py`, `tests/test_agent_cli.py`.
- [x] Write failing real-store tests for permissions, resolution, paging, evidence, cache and CLI.
- [x] Implement workspace create/list/summary, import/analyze, asset/files/issues/code search,
  lineage/impact/batch, columns, evidence, job status and bounded JSON/CSV/HTML exports.
- [x] Implement persistent bounded jobs, background CLI execution and restart interruption reporting.
- [x] Verify focused tests and existing UI, update status/knowledge/docs and include the slice in the tested feature-group commit.

## Slice 2 — MCP transport and security
Files: `src/dataforge/agent/mcp_server.py`; tests: `tests/test_agent_mcp.py`.
- [x] Write failing SDK client tests for discovery, queries/resources/prompts, errors and parity.
- [x] Implement compact typed tools reusing the service, stdio and authenticated Streamable HTTP.
- [x] Test actual stdio subprocess, HTTP unauthorized/authorized paths, budgets and no LLM calls.
- [x] Verify focused tests and UI, update status/knowledge/docs and include the slice in the tested feature-group commit.

## Slice 3 — Human settings, sample workflows and delivery
Files: `ui/agent_settings.py`, `ui/pages/settings.py`, four dedicated guides, AGENTS, README,
architecture/acceptance/test/status plans and affected KNOWLEDGE files.
- [x] Write failing AppTest for access controls, response settings, examples and connection test.
- [x] Implement Settings → Agent & Automation Access with actual shared-service test.
- [x] Verify current Codex/Claude configuration against official docs and record references.
- [x] Import both sample ZIPs separately, select .sql/.sas, inspect pub.all_kpis and WORK collapsing;
  report observed results against manifests without changing parser scope or claiming execution.
- [x] Record compact/detailed character and approximate token measurements.
- [x] Run full pytest, Ruff, lock/package checks, actual running UI and independent review; fix
  substantive findings, update implementation records and commit tested feature group.

## Validation commands
`uv run pytest -q`; `uv run ruff check .`; `uv lock --check`; `uv run dataforge --help`;
`uv run streamlit run app.py --server.address 127.0.0.1` (isolated verification home).
Expected: all applicable tests pass, explicit existing skips, healthy UI and CLI/MCP parity.


## Execution record

All three slices were implemented in this session with real-store RED→GREEN checks,
then verified together as one coherent feature group. User instruction authorized
autonomous execution without approval; implementation remained in the existing clean
checkout on `codex/agent-integration`. No master prompt, .gitignore, theme or primary
runtime data changes. Independent review and final full-suite results are recorded
in AGENT_ACCEPTANCE.md. Shared contracts are consumed unchanged by CLI/MCP/settings.
The supplied SAS fixture exposed existing parser limits; these were recorded without
guessing dependencies or expanding extraction scope. Optional REST remains omitted.
