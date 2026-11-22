# Screenshot and diagram recipes

The Overview captures include the **Open Migration** card and use the locked environment
and a disposable home on loopback. The other workspace and graph captures use application
commit `313587e`. The reference captures
for source evidence, exports, and dbt date from `1864dc8`. Use tracked sample data
and exclude browser chrome. Preserve readable text and descriptive alt text.

```sh
uv run gravetrail-ui --home .dataforge/docs-capture --port 8517 --no-browser
```

Start with a new workspace. **Run SQL example** imports the bundled fixture and
opens its graph. For the import capture, use a separate workspace and ZIP the
public files `pipeline.sql` and `stream_insert.sql` from
`tests/fixtures/vendors/databricks/`.

| Asset under `docs/assets/images/` | Reproduce the view |
| --- | --- |
| `gravetrail-overview-start.png` | Overview in an empty workspace with all four starting actions visible |
| `gravetrail-workspace-dashboard.png` | Overview after static SQL sample analysis, with **Open Migration** under Workspace tools |
| `gravetrail-source-import.png` | Sources → Import with the fixture ZIP loaded and **Databricks** selected |
| `gravetrail-analysis-results.png` | Analysis → Run after **Analyze all files**, with AI unchecked |
| `gravetrail-lineage-explorer.png` | Lineage, exact `stg.orders_clean`, upstream. Expand the table with **+**, fit, then select its header to highlight the column links |
| `gravetrail-source-evidence.png` | Same asset → Source evidence; original `03_staging/036_orders_clean.sql` and line-numbered statement |
| `gravetrail-columns.png` | Columns → Lineage graph, exact `stg.orders_clean`, **amount · cte:1**, depth 3. Fit the upstream trace and frame the cards |
| `gravetrail-export-controls.png` | Same Lineage asset → Export image popover, default SVG/light/normal options |
| `gravetrail-dbt-resources.png` | Separate dbt sample workspace, source-mode dbt ZIP, analyze locally; Lineage → dbt resources and macro impact |
| `lineage-example.png` | Standalone `docs/assets/examples/lineage.html`, Fit graph and select a relationship |

The large tutorial also verifies `pub.all_kpis` at depth 30; the screenshot uses a
smaller branch so node names remain readable. Source snippets are public synthetic
fixture data. Never capture credentials, personal absolute paths or private projects.
Review each replaced image and update this table when controls/fixtures change.

## Migration walkthrough

Use a fresh **Order migration demo** workspace with the SQL and SAS files from
[the migration example](../user-guide/migration.md#try-a-small-migration). Open the app on loopback
and record the application viewport at 1440 × 960 without browser chrome. The capture uses app
commit `1a5d3c2` for the migration UI.

| Asset under `docs/assets/images/` | Capture the view |
| --- | --- |
| `gravetrail-migration-setup.png` | Preflight with both retained files and the Databricks target. |
| `gravetrail-migration-review.png` | `accepted_orders` in **Review**, with **Show pinned source evidence** and **Annotated draft** selected. |
| `gravetrail-migration-lineage.png` | **Migrated lineage** graph showing the SQL edge and the two SAS drafts. |
| `gravetrail-migration-validation.png` | The external dbt artifact controls and configured `daily_order_totals` comparison, before importing observations. |
| `gravetrail-migration-export.png` | **Pilot handoff** prepared for `daily_order_totals`, with `stg_orders` in the included models. |
| `gravetrail-migration-walkthrough.mp4` | Record preview, conversion, the pinned SAS finding, lineage, comparison setup and pilot bundle preparation in that order. |

Keep the original capture in a disposable folder and record when each view opens. Trim the initial
blank frames, add short action captions in a margin below the UI, and encode a web-ready H.264 MP4
with `yuv420p` and `+faststart`. Check each caption against the actual screen and verify the pilot ZIP
contains both SQL models and the reconciliation template. Use no provider credentials or external
validation artifacts in these captures.

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
