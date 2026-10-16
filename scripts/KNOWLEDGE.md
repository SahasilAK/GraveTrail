# scripts/

Operational reproducibility utilities. benchmark.py creates isolated synthetic files, measures real services and persists labeled workload metrics.

## Files
- `verify_agents.py` — Static SQL/SAS ZIP/manifests, all-source probe, cached refresh and compact/detailed response measurements in an explicitly separate data home; no imported source execution.
- `benchmark.py` — CLI labeled SQL-chain benchmark, isolated temporary database, precision/recall assertions, cold/warm/traversal metrics.
- `verify_llm.py` — Opt-in real endpoint check with synthetic SQL/SAS; discovery, connection, grounding/merge/refresh/restart and safe JSON report. Credentials come from a named environment variable.
