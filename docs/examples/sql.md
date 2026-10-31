# SQL tutorial: follow a published KPI

You inherited a project and need to know which sources feed a published result.
Follow [the first-lineage tutorial](../getting-started/quick-start.md) with
`tests/sample_data/dataforge_sql_lineage_test_project.zip` and only `sql` selected.

Investigate `pub.all_kpis` upstream at depth 30. Expected logical graph: 85 persistent
tables, 128 relationships, seven layers and 16 source tables. Registry assets can
include setup/schema objects, so total assets is not the persistent-table count.

Select a relationship, open its original statement, and identify inputs/outputs.
Switch downstream from a source to identify consumers needing investigation if it changes.
Review diagnostics and export completeness rather than relying only on appearance.

Download interactive HTML and reopen it in your browser. Compare with [the smaller
interactive example](interactive-lineage.md), which teaches graph controls rather
than reproducing this large fixture’s expected counts.
