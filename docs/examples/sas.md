# SAS tutorial: uncover temporary steps

[Install](../getting-started/installation.md), create a separate **SAS sample** workspace,
and import `tests/sample_data/dataforge_sas_lineage_test_project.zip` with only `sas`
selected. Run **Analyze all files** with AI unchecked.

1. Select `pub.all_kpis` in **Lineage** and set upstream depth to 30.
2. Turn **Collapse temporary steps** off. Follow a WORK dataset path and inspect its evidence.
3. Turn collapsing on. Expected logical graph: 85 persistent tables, 128 relationships,
   seven layers and 16 source tables. There are also 16 temporary WORK datasets and
   144 physical evidence edges before collapsing.
4. Inspect a reference in **Columns**, then supported expressions in **Transformation lineage**.
5. Export/reopen HTML, recording whether temporary steps were collapsed. Reopen the
   workspace’s data home for live queries.

SAS is never executed. Fixture expectations do not establish runtime order or arbitrary
program accuracy. See [SAS coverage](../SAS_PARSING.md) and [limits](../concepts/evidence-and-coverage.md).
