# scripts/

Operational reproducibility utilities. benchmark.py creates isolated synthetic files, measures real services and persists labeled workload metrics.

## Subfolders
- `build/` — Allowlisted package assets, frozen dispatcher and actual distribution smoke drivers. See [build/KNOWLEDGE.md](build/KNOWLEDGE.md).

## Files
- `verify_agents.py` — Asserts exact logical edge sets and all-source traversal for BOTH SQL/SAS ZIPs; measures cached refresh and compact/detailed responses in a separate data home; no imported source execution.
- `benchmark.py` — CLI labeled SQL-chain benchmark, isolated temporary database, precision/recall assertions, cold/warm/traversal metrics.
- `verify_llm.py` — Opt-in real endpoint check, default OmniRoute auto/best-reasoning; synthetic SQL/SAS discovery, connection, grounding/merge/refresh/restart and safe JSON report. Credentials come from a named environment variable.

- `verify_parity.py` — Requires a new isolated home; actual CLI extension-specific ZIP import/build/warm reuse, owner close/reopen, exact original byte/hash checks, manifest traversal, actual MCP handlers/shared UI dictionary and SDK stdio catalog verification. No network provider calls.
