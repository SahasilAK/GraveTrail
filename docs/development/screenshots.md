# Screenshot and diagram recipes

Captures in this overhaul use application commit `1864dc8`, Python 3.11+, the locked
environment and a disposable `.dataforge/docs-overhaul-ui` home on loopback port 8517.
No provider was configured or called. Screenshots show real UI with safe tracked
fixtures; browser chrome is excluded. Preserve readable text and descriptive alt/captions.

```sh
uv run gravetrail-ui --home .dataforge/docs-capture --port 8517 --no-browser
```

Create **SQL sample**, import `tests/sample_data/dataforge_sql_lineage_test_project.zip`
with only `sql` selected, and run **Analyze all files** with AI unchecked.

| Asset under `docs/assets/images/` | Reproduce the view |
| --- | --- |
| `gravetrail-workspace-dashboard.png` | Overview after static SQL sample analysis |
| `gravetrail-source-import.png` | Sources → Import, ordinary files, only sql selected, SQL ZIP loaded/imported |
| `gravetrail-analysis-results.png` | Analysis → Run after success; leave AI checkbox visibly unchecked |
| `gravetrail-lineage-explorer.png` | Lineage, exact `stg.orders_clean`, upstream, depth 30, temporary steps collapsed; frame graph/toolbar |
| `gravetrail-source-evidence.png` | Same asset → Source evidence; original `03_staging/036_orders_clean.sql` and line-numbered statement |
| `gravetrail-columns.png` | Columns, exact `stg.orders_clean`, unfiltered direct usage |
| `gravetrail-export-controls.png` | Same Lineage asset → Export image popover, default SVG/light/normal options |
| `gravetrail-dbt-resources.png` | Separate dbt sample workspace, source-mode dbt ZIP, analyze locally; Lineage → dbt resources and macro impact |
| `lineage-example.png` | Standalone `docs/assets/examples/lineage.html`, Fit graph and select a relationship |

The large tutorial also verifies `pub.all_kpis` at depth 30; the screenshot uses a
smaller branch so node names remain readable. Source snippets are public synthetic
fixture data. Never capture credentials, personal absolute paths or private projects.
Review each replaced image and update this table when controls/fixtures change.

## Lineage builder canvas

`gravetrail-lineage-builder.png` uses builder source commit `a803b6e` and a disposable
**Color trace demo** workspace. It shows the current fullscreen toolbar, including
Save canvas, Clear canvas, and Export. To reproduce it:

1. Create source schemas `customers`, `products`, and `unrelated`, intermediate
   `orders`, and targets `daily_report` and `warehouse_report`. Each has `id INT`
   and `name STRING`; all names/data are synthetic.
2. Add them explicitly to the canvas catalog. File customers/products in
   **Source group**, place the sources on the left, orders in the middle, reports
   on the right, and the unrelated table below.
3. Connect customers.id and products.id to orders.id, then orders.id to each
   report's id. Add a **Left join** between the two source id output ports.
4. Assign customers blue (`#2563eb`) and products orange (`#f97316`), use the
   **Crimson Forge** app theme, and enter **Full screen**. Fit the diagram and
   select the customers header to show downstream highlighting and dimmed peers.
5. Capture the application viewport without browser chrome, private paths,
   credentials, or provider configuration. No source analysis or AI call is needed.

The [canvas guide](../user-guide/lineage-builder.md) explains the displayed
controls and the distinction between workspace schemas and a canvas catalog.

Core diagram sources are editable SVG: [system boundaries](../assets/diagrams/system-boundaries.svg)
and [analysis sequence](../assets/diagrams/analysis-sequence.svg). Their title/description,
arrow direction and trust-boundary labels must survive edits. Mermaid sources live with
their explanations; verify browser rendering and retain SVG fallbacks.

See [documentation maintenance](documentation.md) for explicit asset registration,
HTML digest review and publication checks. Image conversion/compression must preserve
the real screen content rather than invent controls or results.
