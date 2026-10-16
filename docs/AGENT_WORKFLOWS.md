# Agent workflows

Use these sequences after importing/analyzing a workspace. Prefer existing metadata
over opening source files. Inspect `analysis_current`, `complete`, `boundaries`,
`statuses` and `next_cursor`; never describe incomplete or inferred facts as verified.

## Investigate a table

1. `search_assets(workspace_id, query="customer_summary")` resolves candidate IDs.
2. `get_lineage(workspace_id, asset=ASSET_ID)` traverses upstream locally.
3. Follow `next_cursor`. Use `options={"detail_level":"standard"}` only for relationship IDs.
4. Retrieve needed statement IDs with `get_source_evidence` and cite exact file/line/hash evidence.

Alternatively use the `investigate_lineage` MCP prompt. It is a workflow template,
not a hidden source-reading/LLM feature.

## Direct columns and impact

`get_column_usage(workspace_id, asset="raw.customers")` returns direct stored uses;
it does not infer transitive column lineage. Standard adds references/coordinates;
detailed explicitly adds source expressions/code. Wildcards/unresolved references
retain existing conservative parser status. For a change, call
`analyze_impact(workspace_id, asset="staging.orders")`; groups describe that page,
not unreturned assets. Follow pages or drill into a specific downstream asset.
Use `get_lineage_batch` for up to 20 assets; `remaining_assets` records unprocessed
queries when aggregate budgets are reached.

## Repository automation / incremental refresh

Launch with explicit writes and allowed import roots. Call `ingest_sources`, poll
its `job_id`, then `start_lineage_analysis`, poll and query results. Reimport changed
paths and analyze again: content hashes reuse unchanged parse results. Selected
file IDs and `force=true` retain the existing service's refresh semantics. Import
does not delete previously imported files absent from a later folder snapshot.
Read `get_analysis_issues` to discover unsupported constructs, then export bounded
findings with `export_results`. No source is sent to an external model.

CLI equivalent: see [CLI_GUIDE.md](CLI_GUIDE.md). Use `--background` for detached
import/build and `jobs status --wait` to poll from CI. Every job has a persistent
result or explicit failed/interrupted status. Failures retain previous materialized
lineage; freshness marks pending/changed/configuration-mismatched facts stale.

## Supplied SQL and SAS archives

Use `tests/sample_data/dataforge_sql_lineage_test_project.zip` with `.sql` only,
and `dataforge_sas_lineage_test_project.zip` with `.sas` only, in separate workspaces.
The manifests describe 85 persistent tables, 128 logical edges and seven layers.
The SAS fixture adds 16 temporary WORK datasets (144 expected physical edges).
Check the included README, execution order, lineage CSV/JSON and query-case results.

Recommended probe: search `pub.all_kpis`, query upstream through depth 30 and verify
all 16 `src.*` tables across seven layers. Check SAS temporary collapsing separately.
Both fixtures match all 128 expected logical edges and reach all 16 sources across
seven layers. SAS yields 101 assets including 16 WORK intermediates, with 144 physical
evidence edges before collapsing. PROC SQL `FORMAT=`, `LENGTH=`, `CALCULATED` and
`DATETIME()` expressions are handled statically. SAS retains 31 diagnostics (eight
macro warnings and 23 informational library/inline-data notices), with no parse errors.
Reanalyze older workspaces to refresh parser caches; no source reimport is needed.

Run `uv run python scripts/verify_agents.py --home .dataforge/verification/agents
--output .dataforge/verification/agent-results.json` for static fixture comparisons
and output-size measurements. Use a separate closed home. This executes neither
SQL transformations nor SAS, and makes no DuckDB/SAS runtime compatibility claim.
