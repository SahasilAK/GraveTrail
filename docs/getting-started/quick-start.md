# Quick start

Build and inspect a seven-layer lineage graph from the supplied sample project.
This workflow uses static analysis only; no LLM or credentials are needed.

## 1. Install and launch

Install Python 3.11+, Git and [uv](https://docs.astral.sh/uv/), then run:

```sh
git clone https://github.com/SahasilAK/dataforge-engineering-hub.git
cd dataforge-engineering-hub
uv sync --locked --extra dev
uv run dataforge-ui --home ./.dataforge
```

Open [the local application](http://127.0.0.1:8501). The launcher uses loopback and
port 8501 by default. `./.dataforge` is a persistent runtime directory relative
to the repository root and is ignored by Git. You can instead supply an
absolute path outside the checkout.

For pip, Docker and executable alternatives, use the
[installation reference](../SETUP_AND_DEPLOYMENT.md).

## 2. Import one sample project

Create a workspace in the sidebar, then open **Lineage builder**. Choose a ZIP from
the checkout's
[sample data directory](https://github.com/SahasilAK/dataforge-engineering-hub/tree/main/tests/sample_data):

| Archive | Select only |
| --- | --- |
| `dataforge_sql_lineage_test_project.zip` | `.sql` |
| `dataforge_sas_lineage_test_project.zip` | `.sas` |

Import the selected files and inspect the inventory. The archives include expected
lineage manifests and other supporting files; selecting only the script extension
keeps those reference files out of the analysis. Each project contains 85 persistent
tables across seven ETL layers. The SAS project also has 16 temporary WORK datasets.

## 3. Generate and explore lineage

1. Run **Analyze all files** and review the reported diagnostics.
2. Open **Lineage explorer**, search for `pub.all_kpis`, and select that exact asset.
3. Choose upstream exploration and set traversal depth to **30**. If the visible
   graph or tree is bounded, increase its node limit or inspect the bounded exports.
4. Trace the published result through all seven layers to all **16 source tables**.
5. Select a relationship to inspect its statement and original line range. For SAS,
   compare the graph with temporary steps shown and collapsed.

The fixture has 128 logical lineage relationships. SAS has 144 physical evidence
edges before temporary-step collapsing. SQL's registry can include setup/schema
assets in addition to the 85 tables, so its total asset count is not a table count.
Diagnostics can remain even when this known fixture's logical graph is complete.

The graph represents known static dependencies. Layer order is not proof of runtime
execution order, and a clean fixture result does not establish universal parser coverage.

## 4. Inspect and export

Use the source panel to compare a relationship with the complete original code.
Open **Column usage** for direct column references; ambiguous references
and unexpanded wildcards retain their uncertainty. Export CSV/JSON reports, an
offline interactive HTML graph or the relevant source ZIP from the available controls.
Source exports can contain private code, so review them before sharing.

## Continue from the CLI

**Stop the UI with Ctrl+C first.** DuckDB permits one owning process per data home;
an independent CLI or MCP process must not open the same home while the UI owns it.
From the same repository root, use the same explicit home:

```sh
uv run dataforge --home ./.dataforge --json workspace list
uv run dataforge --home ./.dataforge --json assets search --query pub.all_kpis --workspace WORKSPACE_ID
uv run dataforge --home ./.dataforge --json --max-depth 30 lineage upstream ASSET_ID --workspace WORKSPACE_ID
```

Replace `WORKSPACE_ID` and `ASSET_ID` with the exact IDs returned by the preceding
commands. Global options precede subcommands. Follow `next_cursor` when present;
inspect `complete`, freshness and traversal boundaries before treating a response
as comprehensive. A larger depth limit does not remove response pagination.

Restart the UI with `uv run dataforge-ui --home ./.dataforge` to reopen the same
workspace. See the [CLI guide](../CLI_GUIDE.md) for import, write permissions and
bounded evidence retrieval, or [configuration](configuration.md) for storage defaults.
