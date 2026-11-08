# Quick start

Build and inspect a seven-layer lineage graph from the bundled SQL project.
The example runs local static analysis and requires no AI credentials.

## 1. Install and launch

Follow the [locked installation](installation.md), then open
[the local application](http://127.0.0.1:8501). A new workspace opens on **Overview**.
To design a graph yourself, choose [Open Lineage Builder](../user-guide/lineage-builder.md).
To use your own files, choose [Import sources](../user-guide/sources.md).

## 2. Run the SQL example

On **Overview**, choose **Run SQL example** in an empty workspace. GraveTrail
imports the bundled SQL archive, analyzes it locally, and opens **Lineage** focused
on `pub.all_kpis`. Select a relationship to inspect the original SQL. If your
current workspace already has files, create a new one in the sidebar first.

The example opens the full seven-layer upstream trace. Continue to
[inspect and export](#4-inspect-and-export), or use the manual import steps below
to try SAS or practice with an upload.

<a id="2-import-one-sample-project"></a>

## 3. Try a manual ZIP import

Create a workspace in the sidebar, then open **Sources**. Choose a ZIP from
the checkout's
[sample data directory](https://github.com/SahasilAK/GraveTrail/tree/main/tests/sample_data):

| Archive | Select only |
| --- | --- |
| [Download the SQL sample](https://github.com/SahasilAK/GraveTrail/raw/refs/heads/main/tests/sample_data/dataforge_sql_lineage_test_project.zip) | `.sql` |
| [Download the SAS sample](https://github.com/SahasilAK/GraveTrail/raw/refs/heads/main/tests/sample_data/dataforge_sas_lineage_test_project.zip) | `.sas` |

For the SQL sample, choose **Generic SQL** under **SQL source type**. Select
**Import into inventory** and expand **Skipped files** to see why supporting files
were omitted. Then select **Continue to Analysis**. Each project contains 85
persistent tables across seven ETL layers. The SAS project also has 16 temporary WORK datasets.

<a id="3-generate-and-explore-lineage"></a>

1. Open **Analysis → Run**, leave **Use AI for analysis** unchecked, then choose **Analyze all files** and review the reported diagnostics.
2. Open **Lineage**, search for `pub.all_kpis`, and select that exact asset.
3. Choose upstream exploration and set **Traversal options → Traversal depth** to **30**. If the visible
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
In **Lineage**, expand a table with **+** to see its known output columns and
their links to neighboring tables. Open **Columns → Lineage graph** for a deeper
trace through query steps, or choose **Direct references** to find where a column
is used. Ambiguous references and unexpanded wildcards retain their uncertainty.
Export CSV/JSON reports, an offline interactive HTML graph or the relevant source ZIP.
Review source exports for private code before sharing.

Download the interactive HTML graph and open the saved file in a browser. Try
Fit, zoom, pan, search and relationship selection. This snapshot does not restore
a workspace or run fresh analysis; reopen the same home to continue working. See
[exports and sharing](../user-guide/exports.md) and [coverage limits](../concepts/evidence-and-coverage.md).

## Try the dbt sample

Use a separate workspace for the [dbt sample ZIP](https://github.com/SahasilAK/GraveTrail/raw/refs/heads/main/tests/sample_data/gravetrail_dbt_lineage_test_project.zip).
In **Sources**, choose **Project type → dbt project**, keep **dbt analysis mode → source**,
and import the ZIP. Keep **Use AI for analysis** unchecked and analyze all files.

In **Lineage**, select `fct_orders` and explore upstream/downstream dependencies. Open
**dbt resources and macro impact**, select the `money` macro, and inspect its consumers
and original definition. Models, versions, sources, seeds, snapshots and tests have
separate resource identities. The sample includes dynamic macro/Python cases, so partial
coverage diagnostics are expected; the SQL/SAS sample counts above do not apply.

For already-generated manifest/compiled SQL, artifact selection and supported schemas,
follow [dbt project support](../DBT_SUPPORT.md). No dbt installation or warehouse connection
is required by GraveTrail.

## Continue from the CLI

**Stop the UI with Ctrl+C first.** DuckDB permits one owning process per data home;
an independent CLI or MCP process must not open the same home while the UI owns it.
From the same repository root, use the same explicit home:

```sh
uv run gravetrail --home ./.dataforge --json workspace list
uv run gravetrail --home ./.dataforge --json assets search --query pub.all_kpis --workspace WORKSPACE_ID
uv run gravetrail --home ./.dataforge --json --max-depth 30 lineage upstream ASSET_ID --workspace WORKSPACE_ID
```

Replace `WORKSPACE_ID` and `ASSET_ID` with the exact IDs returned by the preceding
commands. Global options precede subcommands. Follow `next_cursor` when present;
inspect `complete`, freshness and traversal boundaries before treating a response
as comprehensive. A larger depth limit does not remove response pagination.

Restart the UI with `uv run gravetrail-ui --home ./.dataforge` to reopen the same
workspace. See the [CLI guide](../CLI_GUIDE.md) for import, write permissions and
bounded evidence retrieval, or [configuration](configuration.md) for storage defaults.
