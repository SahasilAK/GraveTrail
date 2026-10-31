# dbt retail example

This synthetic project exercises source-only dbt analysis without a database, dbt runtime
or AI provider. It is included in the source checkout at **`1864dc8`**; the published
**v0.0.1** release predates dbt support. For your own project, follow
[Analyze a dbt project](../project-types/dbt.md).

## Get the sample

Use [`tests/sample_data/gravetrail_dbt_lineage_test_project.zip`](https://github.com/SahasilAK/GraveTrail/blob/1864dc8/tests/sample_data/gravetrail_dbt_lineage_test_project.zip)
from the repository. The archive contains a `retail/` root with SQL and Python models,
property/source YAML, nested macros, CSV seeds, SQL/YAML snapshots, tests, docs, an exposure
and semantic declarations. It contains no credentials or warehouse data.
The [reviewed logical edge gold](https://github.com/SahasilAK/GraveTrail/blob/1864dc8/tests/fixtures/dbt/gold.json)
stays outside the imported input.

The sample deliberately includes partial cases. It supplies no generated manifest, catalog
or run-results artifact. It qualifies source mode; artifact behavior has separate
[fixture tests](https://github.com/SahasilAK/GraveTrail/blob/1864dc8/tests/test_dbt_artifacts.py).

## Run it in the UI

1. Create a workspace, then open **Sources** and select **dbt project**.
2. Upload the sample ZIP, select **source** mode and import. Keep package inclusion off.
3. Open **Analysis → Run**, leave **Use AI for analysis** unchecked and choose **Analyze all files**.
4. Open **Lineage**, select `fct_orders`, and inspect its upstream graph and evidence.
5. Expand **dbt resources and macro impact**. Inspect `money`, then `scale`, downstream.

The graph should include `raw.orders → stg_orders → int_orders → fct_orders`, with
`stg_customers → fct_orders`. `int_orders` is ephemeral but remains a logical dependency.
Seed files feed logical `countries` and `statuses`, which feed `dim_customers`.
The versioned model `orders` has distinct v1/v2 identities.

## Reproduce from the CLI

Run this PowerShell sequence from the repository after source installation. The timestamp
creates a fresh home; leave other processes on their existing homes. Replace `gravetrail`
with `uv run gravetrail` if using the checkout's uv environment.

```powershell
$repoRoot = (Get-Location).Path
$gtHome = Join-Path ([System.IO.Path]::GetTempPath()) ('gravetrail-dbt-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
$sampleRoot = Join-Path $repoRoot 'tests\sample_data'
$sampleZip = Join-Path $sampleRoot 'gravetrail_dbt_lineage_test_project.zip'
$created = gravetrail --home $gtHome --json --allow-write workspace create 'dbt retail example' | ConvertFrom-Json
$workspaceId = $created.workspace_id

gravetrail --home $gtHome --json --allow-write --allowed-root $sampleRoot ingest $sampleZip --workspace $workspaceId --source-kind dbt
gravetrail --home $gtHome --json --allow-write lineage build --workspace $workspaceId
gravetrail --home $gtHome --json workspace summary --workspace $workspaceId
gravetrail --home $gtHome --json dbt projects --workspace $workspaceId
gravetrail --home $gtHome --json --limit 100 dbt resources --workspace $workspaceId
gravetrail --home $gtHome --json lineage upstream fct_orders --workspace $workspaceId
gravetrail --home $gtHome --json lineage validate --workspace $workspaceId
```

Read macro evidence and impact using IDs from the catalog:

```powershell
$macros = gravetrail --home $gtHome --json dbt resources --workspace $workspaceId --resource-type macro | ConvertFrom-Json
$moneyId = ($macros.items | Where-Object name -eq 'money').resource_id
gravetrail --home $gtHome --json --detail detailed dbt resource $moneyId --workspace $workspaceId
gravetrail --home $gtHome --json dbt dependencies $moneyId --workspace $workspaceId --direction downstream --kind macro_call

$htmlPath = Join-Path $gtHome 'dbt-lineage.html'
gravetrail --home $gtHome --json --allow-write export graph fct_orders --workspace $workspaceId --format html --output $htmlPath
gravetrail --home $gtHome --json --allow-write export lineage fct_orders --workspace $workspaceId --format json
```

## Check the result

Observed on 25 October 2026 using the documented checkout, a dedicated home and the CLI:

| Check | Observed result |
| --- | --- |
| Import | 21 accepted source files, 0 skipped, 0 import diagnostics; duplicate content count 1 |
| First parser build | 21 analyzed, 0 cached, 19 assets, 16 edge records |
| Second unchanged build | 0 analyzed, 21 cached; same asset/edge counts |
| Workspace | `analysis_current=true`; 7 analysis diagnostics |
| dbt inventory | One `retail` project, 30 resources |
| Project coverage | Inventory complete; dependencies and columns partial; mode source |
| `fct_orders` upstream | `int_orders`, `stg_orders`, `stg_customers`, `raw.orders`, `raw.customers` |
| `money` downstream, `macro_call` | `fct_orders`, depth 1, resolved |
| `money` evidence | `source_static`, line 1 of `retail/macros/money.sql`, exact macro block |
| Evidence validation | 86 checked, 0 invalid |
| HTML/JSON exports | HTML downloaded with checksum verification; JSON returned a stored result ID |

The 16 edge records correspond to 15 distinct **display-name** pairs in the gold file;
the two `orders` versions share a name but retain different identities. Count IDs when
comparing the graph. Model/test/semantic resources also do not all become graph assets.

Partial coverage is expected: `fct_orders` calls `money`, whose body calls `scale`, and
source-only analysis does not expand either macro. `py_orders` records a literal dependency
without DataFrame column semantics. SQL and YAML snapshots record dependencies without
executing SCD logic. Tests, exposures and semantic declarations are typed resource
relationships rather than production table edges.

The semantic fixture's `order_count` refers to a measure named `orders` that is not declared
in its semantic model. Its presence in inventory does not prove that measure resolves or
that the metric can execute. Separate resource tests qualify simple declared measure and
saved-query dependency links. See [dbt coverage limits](../DBT_SUPPORT.md#models-columns-and-resources).

To compare your run, inspect IDs, origins, diagnostics, coverage and paging flags as well
as counts. A build completing and all evidence ranges validating do not establish complete
lineage or successful dbt execution.
