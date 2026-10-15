# User guide

Create or switch workspaces in the sidebar. Every workspace has its own source inventory,
analysis, settings and provider profiles. Workspaces reopen automatically after restart.

**Build:** In Lineage builder choose a ZIP, browser folder or allowed host directory. Select
extensions before importing; only selected supported files are read. The inventory shows
encoding, size, lines, hashes and parsing status. Duplicate content at different paths remains
traceable. Reimporting an existing path replaces the active inventory entry without losing
original bytes needed by prior evidence. Imports are additive; omitted files are not deleted.

Choose Analyze all files or select paths. Normal analysis reuses unchanged parses; Rebuild
forces parsing. Diagnostics explain ambiguous/dynamic constructs. A failed run preserves
the previous committed facts. A newer file imported during a run remains pending.

**Review unresolved code:** Open **Unresolved review queue** in Builder after analysis. It
lists up to 100 current SQL/SAS warnings and errors, with errors first. CSV, informational
and pending-file diagnostics are excluded. Choose a diagnostic to preview its containing
statement or bounded nearby context, then adjust original start/end lines if needed. A long
range has a truncated preview and cannot be sent until it fits the workspace context budget.
Previewing needs no provider. **Request AI review of this range** uses the SQL/SAS task route
configured in Settings and all existing privacy, redaction and profile budgets. No background
requests occur. If source changes after the preview, refresh it before requesting again.

Validated responses can be merged separately as inferred relationships. Quarantined output
changes no facts. A valid relationship does not resolve a parser warning about a column or
runtime construct; diagnostics remain until deterministic analysis resolves them. The queue
is a bounded manual review list, not an automatic batch agent. **Optional AI assistance**
remains available for manual source-range/task selection. AI results are read from local
retained activity records and can expire under the configured retention policy.

**Explore:** Search and explicitly select an exact asset. Searching `orders` in the supplied
fixture yields raw/staging/mart choices. Use upstream/downstream trees and graph direction,
set depth and collapse temporary stages. Graph search highlights nodes; click nodes to highlight
their upstream path, or edges to inspect operation evidence. Fit/zoom/pan controls are keyboard
and mouse accessible. Cycles are reported and traversal terminates.

Tree tabs render only the active direction. Opening a branch loads its immediate descendants;
closed descendants are not rendered. Use **Expand tree to depth** and **Expand to depth** to
open several levels, or **Collapse tree** to close all branches. The graph-node limit also
bounds visible tree entries. Settings → Visualization sets the initial tree expansion depth.

**Dependency paths and exports** provides upstream root-to-target and downstream target-to-
terminal paths with ordered CSV/JSON downloads. Each step references its original file hash,
statement, line range, extraction method and verification status. Collapsed temporary steps
retain all intermediate evidence. Depth boundaries and cycle boundaries are explicit, and
path-limit truncation is reported. These reports describe the known static graph, not runtime
execution order or proof that unresolved source constructs do not exist.

The source panel filters to relevant files. It shows original line ranges, statement snippets,
complete syntax-highlighted source, source search and byte-exact downloads. Code blocks have a
copy button. Old facts show the corresponding analyzed original version when newer code is pending.
Step numbers are logical dependency order, not runtime execution order.

**Columns:** Select a source asset, filter names and group by file or usage context. This report
contains direct references only. Wildcards show unknown coverage when no trusted schema exists.
Ambiguous unqualified columns are diagnostics rather than assigned arbitrarily.
For a consistent imported SQL CREATE TABLE schema, plain wildcards expand to known columns
as inferred references. The declaration viewer shows the original DDL and its analyzed file
version alongside the query evidence. Reports include the schema source location. Schema
changes/conflicts and wildcard modifiers retain uncertainty. Disable expansion in Parsing and
lineage settings if desired. No database connection or CSV-to-table name guess is involved.

**Export:** Download lineage/report CSV/JSON, an offline interactive HTML graph and relevant
original source ZIP. Exports contain selected source evidence, so share them according to your
code's confidentiality. Spreadsheet formula prefixes are escaped in CSV exports.

**Tools:** Search literal text across code (CSV data excluded), inspect the provenance-labeled
dictionary, assess static downstream impact or compare completed analysis runs.

**Settings:** Set SQL dialect/folder overrides, SAS libraries/static macros, case policy, import
limits, parsing workers, graph depth/node limits and optional AI privacy/profiles. Storage home
and host roots are startup environment settings. Storage and workspaces lets you edit the active
workspace name and description without changing its identity or imported files. Configuration
export/import preserves parsing, resource and graph settings in a new workspace. Imports validate
types, SQL dialects and numeric limits and are transactional. Earlier v1 configurations remain
supported. Profiles, credentials, privacy permissions, sources and analysis history are excluded;
this is a configuration transfer, not a workspace backup. Deletion requires typing the current
workspace name.

**Visualization defaults:** Save graph direction, temporary-step collapse, label density,
node palette and edge width in Settings → Visualization. Compact labels shorten long names;
full names fit inside wider nodes; hidden labels still expose exact names in keyboard-accessible
nodes, tooltips and evidence. Semantic colors distinguish asset kinds; the neutral palette uses
one fill. Live Explorer and offline graph HTML/JSON share these settings. Direction and collapse
remain adjustable for the current exploration. Preferences belong to each workspace and are
included in safe configuration transfers.

**Color themes:** In Settings → Visualization choose **Ocean dark**, **Forest dark**,
**Amethyst dark** or **Graphite dark**, or one of their four light equivalents, then click
**Apply theme**. Dark presets apply dark appearance directly, including native forms, tables,
charts and sidebar. Presets apply across the local app and all workspaces and persist in its
native `.streamlit/config.toml`, separately from workspace configuration transfers. The picker
waits briefly for native configuration reload; refresh the page if a reload hint appears.
The configuration must be writable. Custom layout/sidebar overrides are retained.

Six additional choices are available alongside those original eight: **Claude orange light**,
**Claude orange dark**, **Nord light**, **Rose light**, **Sand light** and **Mint light**.
The orange choices are inspired by Claude's warm palette. Existing theme names and colors
are preserved. Adding these options does not apply a different theme; choose **Apply theme**
only when you want to change the current appearance.

The selector is a dropdown with fourteen named options (five dark and nine light).
If an older running server still shows four theme buttons after an upgrade, restart
the Streamlit server from the updated checkout, then refresh the browser page.

Choose complete source expanded or relevant statements first, and whether code displays line
numbers. Relevant-first mode keeps the **Complete source** panel closed when evidence snippets
are available; open it to load the full display. Files without focused evidence default to full
source. Exact original line ranges remain on evidence panels even when code numbers are hidden.

**History maintenance:** In Settings → Storage and workspaces, open **Archive and restore old
history**. Choose recent analysis/import counts to retain and a batch limit (up to 100 records
per type). Preview shows eligible records; the latest completed analysis, active edge/inventory
references and running analyses are protected, so more than the requested count may remain.
**Archive eligible history** removes those metadata rows transactionally after preparing local
recovery, with a compressed database copy committed in the same transaction. Select a recovery
archive and **Restore selected history** to insert missing records without replacing existing
history. Restore prefers the database copy and works after restart even if the JSON file is lost.
Recovery copies remain retained; this reorganizes history and does not reclaim source-file disk
space or guarantee that DuckDB immediately shrinks. Original blobs, current facts and AI evidence
are untouched. This is a manual operation, not a scheduled retention policy or a full backup.

SQL dialect selection uses default, then extension override, then the longest matching folder
prefix. For .sas only PROC SQL uses this dialect; DATA/PROC rules remain SAS. Graph confidence
and inferred visibility preferences filter the view and graph exports, without deleting facts.
Parsing diagnostics can be filtered for display; the unresolved review queue still preserves
warnings/errors. Analyze can reuse unchanged results or reparse selected/all files. On parser or
configuration changes, previously analyzed incompatible files refresh to keep the workspace
coherent; newly imported unselected files remain pending. Logging level in Security and privacy
is app-wide for the data home, persists across restart and is not transferred with workspaces.
