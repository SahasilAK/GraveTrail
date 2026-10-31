# Export and share findings

| Export | Use | Boundary |
| --- | --- | --- |
| Interactive HTML | Explore a fixed snapshot in a browser | Embeds graph/evidence; no refresh or workspace restore |
| SVG / PNG | Include a graph in a document | Business labels included; raw source excluded from images |
| CSV / JSON reports | Inspect paths/evidence in another tool | Respect completeness/truncation/unresolved markers |
| XLSX paths | Share ordered dependency/path sheets | Logical ordering is not runtime order |
| Original source ZIP | Share analyzed originals | Can contain private code |
| Backup/configuration | Recovery or supported config transfer | Different formats and ownership rules |

In **Lineage**, **Export** prepares graph images for the entire current filtered/bounded
graph, independent of pan/zoom. Choose format, background, scale, title and legend, then
prepare/download. Other graph/report downloads appear with the analysis/evidence views.

![Export controls showing graph totals and image options](../assets/images/gravetrail-export-controls.png)

*Check totals and filters before sharing.*

## Reopen an interactive snapshot

Download interactive HTML and open the saved file in a browser. Try Fit, zoom, pan,
search and relationship selection. The [safe example](../examples/interactive-lineage.md)
documents supported interactions; standalone exports do not provide every application action.

HTML cannot import analysis back into GraveTrail. Reopen the same data home/workspace,
or use supported [backup/restore](../DATA_MANAGEMENT.md), to continue live queries.

The [CLI reference](../CLI_GUIDE.md) covers artifact downloads/checksums. For format
ownership see the [developer module guide](../development/code-map.md).
