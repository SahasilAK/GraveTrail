# User guide

For multi-model dbt repositories, choose **Sources → Project type → dbt project**.
Import configured models, property YAML and macros together, then run parser analysis.
See [the dbt workflow](project-types/dbt.md), [retail example](examples/dbt.md) and
[dbt support reference](DBT_SUPPORT.md) for artifact selection, resource impact and limits.

Create or switch workspaces in the sidebar. Every workspace has its own source inventory,
analysis, settings and provider profiles. Workspaces reopen automatically after restart.

## Choose how to analyze

**Local parsing is the primary, default option.** Leave **Use AI for analysis**
unchecked in **Analysis → Run** to build lineage and column information without
sending source to an AI provider. No model connection, API key or AI token usage is
needed, including for large projects.

When you want additional coverage in a large or complex system, optionally enable
AI. This workflow independently extracts validated inferred facts from selected files.
Parser results do not fill AI omissions. It sends selected source/context to your
configured provider under the privacy controls. Review evidence, omissions and
unresolved cases; AI cannot guarantee complete or universally correct lineage.
See [AI project analysis](AI_ANALYSIS.md) for the build flow and limits.

## Find your way around

The sidebar keeps your active workspace above three navigation groups. Use **New
workspace** to open a creation dialog. Changing pages never starts an analysis or an AI request.

| Group | Destination | What belongs here |
| --- | --- | --- |
| Workspace | Overview | Health, recent runs and the next useful action |
| Workspace | Sources | ZIP/folder/host import; Inventory, original file details and exports |
| Workspace | Analysis | Run selected/all files, rebuild, validation; Diagnostics and optional AI review; History and run comparison |
| Explore | Lineage | Graph or full-width Tree; source evidence, paths and graph/source exports |
| Explore | Columns | Direct usage, grouping, declared schema evidence and reports |
| Explore | Transformation lineage | Output/value transformations, distinct dependency roles, coverage and original source evidence |
| Explore | Engineering tools | Code search, data dictionary and downstream impact |
| Administration | Workspace settings | Parsing, Resources and Appearance, including all eleven themes |
| Administration | Connections & AI | Provider profiles, session credentials, routing and Privacy |
| Administration | Data management | Storage & transfers, Backups & integrity, Cleanup & recovery, History & staging |
| Administration | Automation & access | Agent permissions, response budgets, client configuration and local connection test |

Selections persist between related exploration views when valid. Workspace and
source revision changes discard stale source previews and cleanup plans. Unsaved
preferences are discarded when you leave their form; saved settings require the
explicit Save action. `/builder` now opens Sources, `/explorer` opens Lineage, and
`/settings` opens workspace preferences, so existing page bookmarks still work.

**Import:** In Sources → Import choose a ZIP, browser folder or allowed host directory. Select
extensions before importing; only selected supported files are read. The inventory shows
encoding, size, lines, hashes and parsing status. Duplicate content at different paths remains
traceable. Reimporting an existing path replaces the active inventory entry without losing
original bytes needed by prior evidence. Imports are additive; omitted files are not deleted.

Open **Analysis → Run**, then choose **Analyze all files** or select paths. Normal analysis reuses unchanged parses; Rebuild
forces parsing. Diagnostics explain ambiguous/dynamic constructs. A failed run preserves
the previous committed facts. A newer file imported during a run remains pending.

**Review unresolved code:** Open **Unresolved review queue** in Analysis → Diagnostics after analysis. It
lists up to 100 current SQL/SAS warnings and errors, with errors first. CSV, informational
and pending-file diagnostics are excluded. Choose a diagnostic to preview its containing
statement or bounded nearby context, then adjust original start/end lines if needed. The exact
selected range is preserved; source and referenced known assets are never shortened to force a fit.
As in project AI Analysis, context follows the selected evidence: the prompt lists known
asset names referenced in that range, excluding comments and string literals. The preview
shows included and total job-visible asset counts. The complete catalog remains available
locally for grounded validation; unrelated catalog growth does not enlarge the request.
If the complete relevant context still exceeds capacity, submission remains blocked.
The offline preview shows the SQL/SAS task profile/model, complete redacted request's estimated
input tokens, input allowance, output reservation, counting method and blocking reasons.
**Request AI review of this range** uses the SQL/SAS task route
configured in Connections & AI and all existing privacy and redaction controls. No background
requests occur. If source changes after the preview, refresh it before requesting again.

Both Diagnostics AI panels require confirmed, current model capacity. In **Connections & AI**, inspect
the selected model or explicitly confirm its capacity; legacy profiles also require the explicit
source-disclosure migration choice. The default output share is 30%, bounded by a saved Custom
output cap and model limits, with reasoning and safety reserves applied once. Project-analysis
session overrides do not affect focused assistance or change saved profiles. `token_capacity` profiles
use token capacity instead of legacy implicit character ceilings; `explicit` profiles retain
their configured source-character disclosure restriction. Submission is disabled when blocked.
CLI `ai review preview`/`ai chunks` and MCP `preview_diagnostic_review`/`preview_ai_chunks`
expose the same `budget` diagnostics and a `request_fingerprint` for the selected range.
The UIs pin that fingerprint on submission; CLI/MCP callers can pass it as `expected_request`
(CLI `--expected-request`). Dispatch rechecks capacity, source, profile and privacy; an
authorized fallback uses its own model limits. Chunk previews remain an explicit optional
selection aid; focused requests never automatically split or schedule remaining chunks.

Validated responses can be merged separately as inferred relationships. Quarantined output
changes no facts. A valid relationship does not resolve a parser warning about a column or
runtime construct; diagnostics remain until deterministic analysis resolves them. The queue
is a bounded manual review list, not an automatic batch agent. **Optional AI assistance**
remains available for manual source-range/task selection. AI results are read from local
retained activity records and can expire under the configured retention policy.

Both panels use the same source-grounded proposal workflow. Known assets are context rather
than a closed list: executable source syntax can support a resource missed by static analysis.
The host checks exact quotes, original file coordinates, source hash, configured dialect,
job/session identity and bound read/write roles. A wrong location can be corrected only when
the exact quote occurs once inside the authorized selection; the result retains both the
reported and corrected coordinates. Comments, string contents, uninvoked SAS macro bodies,
runtime guesses and ambiguous resource identities cannot establish additions.

Results distinguish existing static operations, validated AI resources to create/reuse,
relationship proposals, evidence corrections and unresolved symbols. **Merge grounded
relationships as inferred** explicitly accepts eligible resources and relationships in one
transaction. Repeat acceptance does not duplicate them. Accepted AI relationships stay
inferred after normal Analysis/refresh; changed source, job, parsing settings or conflicting
identity require a new review. Quarantine shows a safe reason and changes no facts. Historical
results remain readable and must pass current evidence checks before acceptance; historical
advisory results cannot be merged. Column suggestions and code explanations remain advisory.

Focused verification supports the configured parser's SQL/SAS operations plus a bounded
literal INSERT/SELECT syntax witness for backticks and MySQL VALUES(column) upserts. It does
not establish arbitrary runtime or unsupported dialect semantics. Configuring MySQL for a
MySQL folder can improve static parsing; source fixture comments do not configure the dialect.

**Explore:** Search and explicitly select an exact asset. Searching `orders` in the supplied
fixture yields raw/staging/mart choices. Use upstream/downstream trees and graph direction,
set depth and collapse temporary stages. Graph search highlights nodes; click nodes to highlight
their upstream path, or edges to inspect operation evidence. Fit/zoom/pan controls are keyboard
and mouse accessible. Cycles are reported and traversal terminates.

Tree tabs render only the active direction. Opening a branch loads its immediate descendants;
closed descendants are not rendered. Use **Expand all** to open branches up to the traversal limit, or **Collapse all** to close them. The graph-node limit also
bounds visible tree entries. Workspace settings → Appearance sets the initial tree expansion depth.

**Dependency paths and exports** provides upstream root-to-target and downstream target-to-
terminal paths with ordered CSV/JSON downloads. Each step references its original file hash,
statement, line range, extraction method and verification status. Collapsed temporary steps
retain all intermediate evidence. Depth boundaries and cycle boundaries are explicit, and
path-limit truncation is reported. These reports describe the known static graph, not runtime
execution order or proof that unresolved source constructs do not exist.

Choose **Export to Excel** in that area to review the asset, direction, depth/path
limits, temporary stages and evidence options, then **Prepare Excel workbook** and
**Download Excel workbook**. `Lineage Paths` shows numbered dataset columns from
source to target even for upstream traversal. `Lineage Steps` stores one ordered
relationship per path position; several citations do not create extra steps.
Paths wider than eight datasets continue on numbered segments with one overlapping
dataset. Shared IDs retain joins and job-scoped temporary identity. Some temporary
stages remain visible when collapsing them would combine distinct parallel routes.

The optional `Evidence` sheet contains original file/hash/line citations. Raw
SQL/SAS excerpts require the separate explicit option. Without that sheet, evidence
IDs/status remain references, not offline citations. The workbook records a committed
revision, UTC export time, filters, counts and coverage warnings. Steps show data
dependencies, not runtime execution order. Unknown or unsupported analysis does not
become complete lineage merely because a path reaches a known graph boundary.

Excel exports are bounded to 500 paths, depth 30, 20,000 relationships and evidence
references (2,000 relationships by default), eight dataset columns per segment,
32 MiB of text and 64 MiB of workbook data. Graph input is capped at 20,000 assets
and 100,000 evidence edges. Generation has a cooperative 30-second deadline, with
checks between bounded phases and rows. Relationship/path/depth omissions are labeled;
evidence/text/time limits fail with a narrower-selection message. A cell that cannot
fit Excel's 32,767-character limit fails explicitly, without clipping. Labels and
excerpts are literal text; no formulas or external links are generated.

The source panel filters to relevant files. It shows original line ranges, statement snippets,
complete syntax-highlighted source, source search and byte-exact downloads. Code blocks have a
copy button. Old facts show the corresponding analyzed original version when newer code is pending.
Step numbers are logical dependency order, not runtime execution order.

**Columns:** Select a source asset, filter names and group by file or usage context. This report
contains direct references only. Wildcards show unknown coverage when no trusted schema exists.
Ambiguous unqualified columns are diagnostics rather than assigned arbitrarily.
Above **Group by**, **Distinct used columns** lists every known direct column independently
of the text filter. Copy a single name with its adjacent icon or use **Copy list** for the
comma-separated names. The column filter accepts comma-separated terms and matches any term.
The collapsed **Unused columns** section lists declared columns without known direct usage,
with the same copy controls. Missing/conflicting schemas and unresolved wildcards make this
list unknown; it is not proof of non-use in a live system.
For a consistent imported SQL CREATE TABLE schema, plain wildcards expand to known columns
as inferred references. The declaration viewer shows the original DDL and its analyzed file
version alongside the query evidence. Reports include the schema source location. Schema
changes/conflicts and wildcard modifiers retain uncertainty. Disable expansion in Parsing and
lineage settings if desired. No database connection or CSV-to-table name guess is involved.

**Export:** Download lineage/report CSV/JSON, an offline interactive HTML graph and relevant
original source ZIP. Exports contain selected source evidence, so share them according to your
code's confidentiality. Spreadsheet formula prefixes are escaped in CSV exports.

**Tools:** Search literal text across code (CSV data excluded), inspect the provenance-labeled
dictionary or assess static downstream impact. Compare completed runs in **Analysis → History**.

**Workspace settings:** Set SQL dialect/folder overrides, SAS libraries/static macros, case policy, import
limits, parsing workers, graph depth/node limits and optional AI privacy/profiles. Storage home
and host roots are startup environment settings. Data management → Storage & transfers lets you edit the active
workspace name and description without changing its identity or imported files. Configuration
export/import preserves parsing, resource and graph settings in a new workspace. Imports validate
types, SQL dialects and numeric limits and are transactional. Earlier v1 configurations remain
supported. Profiles, credentials, privacy permissions, sources and analysis history are excluded;
this is a configuration transfer, not a workspace backup. Deletion requires typing the current
workspace name.

**Visualization defaults:** Save graph direction, temporary-step collapse, label density,
node palette and edge width in Workspace settings → Appearance. Compact labels shorten long names;
full names fit inside wider nodes; hidden labels still expose exact names in keyboard-accessible
nodes, tooltips and evidence. Semantic colors distinguish asset kinds; the neutral palette uses
one fill. Live Explorer and offline graph HTML/JSON share these settings. Direction and collapse
remain adjustable for the current exploration. Preferences belong to each workspace and are
included in safe configuration transfers.

**Color themes:** In Workspace settings → Appearance choose a preset, then click
**Apply theme**. The saved configuration selects the active theme; the checked-in
configuration currently selects **Crimson Forge**. The original **Ocean dark** colors and those of
**Ink dark** are preserved. Nine additional palettes are available: **Obsidian & Ember**,
**Arctic Mint**, **Amethyst Terminal**, **Fossil & Copper**, **Carbon & Volt**,
**Crimson Forge**, **Cobalt Atlas**, **Rose Circuit**, and **Steel Glacier**.

Each new palette has separate canvas, sidebar, panel, text, border and action colors.
Its graph distinguishes source, intermediate and target nodes, secondary edges,
highlighted paths and selected evidence. Node layout and graph controls are unchanged.
Bright action backgrounds use readable dark labels; links and the two-color GraveTrail
wordmark use a readable shade of the theme accent. The supplied icon has a transparent exterior.

Presets apply across the local app and all workspaces and persist in its native
`.streamlit/config.toml`, separately from workspace configuration transfers. The picker
waits briefly for native configuration reload; refresh the page if a reload hint appears.
The configuration must be writable. Fonts, spacing and sidebar layout overrides are retained;
preset-owned sidebar colors reset when returning to Ocean dark or Ink dark.
An existing customized or retired palette stays active until you apply a supported preset.

GitHub Pages offers the same nine new palettes alongside its original **Ink dark** and
**Celadon light**. First visits load **Obsidian & Ember**. The site remembers dropdown selections independently of the local app.

Choose complete source expanded or relevant statements first, and whether code displays line
numbers. Relevant-first mode keeps the **Complete source** panel closed when evidence snippets
are available; open it to load the full display. Files without focused evidence default to full
source. Exact original line ranges remain on evidence panels even when code numbers are hidden.

**History maintenance:** In Data management → History & staging, open **Archive and restore old
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
coherent; newly imported unselected files remain pending. Logging level in Connections & AI → Privacy
is app-wide for the data home, persists across restart and is not transferred with workspaces.

Data management → History & staging → Clean stale temporary files previews application-created
history staging files at least24 hours old. Select files explicitly before cleaning. A retained
compressed recovery copy is committed first; choose it to restore without overwriting an
existing file. Restored files are fresh and not immediately eligible again. Sources, databases,
JSON history archives and arbitrary temporary files are excluded. This clears staging files;
retained recovery bytes mean total disk usage may not shrink. No automatic cleanup runs.


**Storage locations:** Configure `DATAFORGE_HOME` for the default directory and optionally
`DATAFORGE_STORAGE_LOCATIONS` with additional absolute directories before startup (Windows
separator `;`, Linux/macOS `:`, maximum eight total). Data management → Storage & transfers lists
these allowed locations. Select one and press **Open storage location**. This browser session
opens that independent database and resets its workspace controls; other sessions stay where
they are. Files are never migrated by this action. Open the previous location to return to its
persisted workspaces. A failed open keeps the current workspace. New browser sessions start in
the default location. Storage locations and permissions are excluded from workspace transfers.

**Job/session identity:** Workspace settings → Parsing accepts a default ID and folder-prefix map.
Use supplied IDs to separate temporary datasets belonging to different jobs; the longest folder
prefix wins. Reanalyze after changes. Persistent tables remain shared. Mixed temporary and
persistent writes to the same name in a job leave reads unresolved. Static source cannot
establish runtime execution order. Exact selectors and graph labels show nondefault job IDs.

CSV sample rows in Workspace settings → Parsing controls retained preview and sampled type inference
(0–100; default25). Zero retains no sample and leaves inferred types unknown. Reanalyze after
changes. Inventory counters and extension breakdown refresh immediately after analysis.
Lineage switches between Graph and full-width Tree. Traversal depth and temporary-step
collapse live in **Traversal options**. Step-wise lineage and source evidence appear below
the active view, stacking on narrower screens.

Choose **All** in the exact asset selector to display the entire workspace graph, including
disconnected assets. All keeps confidence and temporary-step settings but ignores focused
depth/node limits; choose an exact asset for a tree or dependency paths. Large workspaces may
take longer to draw. **Fullscreen** expands the graph; use **Exit fullscreen** or Escape to leave.
Each node has an icon to copy its full asset name. Double-click a node (or Alt+Enter when
focused) to make it the exact selected asset. **Back** and **Forward** restore previous asset
views and their search, direction, depth and temporary-step controls within this session.

In Graph, the source selector follows **upstream**, **downstream** or **combined**; in Tree,
it follows the active dependency tab. All includes evidence across the full displayed graph.
Clicking a graph asset or edge narrows evidence to that selection. Source scope labels the
current context; changing graph traversal controls clears the previous graph selection.


## Automation & access

Open Automation & access for CLI instructions, copyable Codex/Claude
configuration, workspace permissions, source disclosure, response budgets and auditing.
The local connection test invokes the real MCP handler in-process. To connect a separate
client to this data home, stop the Streamlit owner first or use an isolated automation home.
See [CLI_GUIDE.md](CLI_GUIDE.md) and [AGENT_WORKFLOWS.md](AGENT_WORKFLOWS.md).

## Interaction and accessibility

Controls give immediate press/focus feedback; pages have no entrance sequence or
animation that replays on rerun. Reduced motion removes transforms and transitions;
reduced transparency uses solid navigation surfaces; increased contrast strengthens
focus and borders. Graph pan/zoom is direct and keyboard nodes/edges support Enter
and Space. Tables and code retain their own scroll areas at narrow widths.

**Export report** groups CSV/JSON/HTML formats. In Lineage, **Export graph & sources**
contains the offline graph, graph JSON and original source ZIP. Files are generated
only when requested. These exports can contain private source evidence.

Use **Export** beside the Lineage history controls to prepare a standalone **SVG**
or **PNG** image. **Entire filtered graph** fits every node in the current bounded
result, independently of browser pan/zoom. Review the selected asset, direction,
depth, filters, temporary-step policy and node/relationship counts before downloading.
SVG remains editable vector XML; PNG is a real raster image. Both share the live
graph's layout, labels, palette and edge width. Full identifiers remain in SVG
titles when compact labels are shown. Source code, evidence panels and buttons
are excluded. Asset/workspace identifiers can still contain private business metadata.

Light is the default background; dark and transparent are explicit choices.
Transparent uses dark text/edges for placement on a light document. Choose normal
or 2× resolution and optionally include a title and legend. Depth/node boundaries,
filters, collapsed intermediates, stale analysis and analysis warnings appear in
the image. These images describe the filtered result, never complete workspace coverage.

Limits: 1,000 nodes, 5,000 relationships, 20,000 evidence records during temporary
contraction, 4 MiB SVG, 16 MiB PNG; PNG additionally
allows at most 8,192 pixels per side, 16 million pixels and 15 seconds of rasterization.
Each application process allows two concurrent PNG workers; busy requests can retry.
Excessive images fail with advice to reduce depth/scale or use SVG. Empty graphs
have no image. A failed export leaves the current graph intact. No image cache
is retained; each preparation snapshots the current committed graph/settings.
PNG requires the bundled `resvg-py` dependency; if unavailable, SVG remains usable
and the UI/capability response reports that PNG is unavailable. Exports never
download software, fonts or external image resources.

## Build lineage with optional AI

On **Analysis**, **Use AI for analysis** is initially unchecked. Enable it to preview the
selected family, provider/model, disclosed files, file parts and estimated token/request
counts. Choose **Analyze with AI** explicitly to start independent AI extraction.
Preview and ordinary page reruns send no requests. Hybrid comparison and additional AI
review are unavailable in this checkout. An explicit static build uses static results.

Use **Connections & AI** to configure the provider and deliberate privacy settings.
Remote processing of a complete file across parts still requires complete-source
permission. Confirm unknown model capacity before dispatch. The saved report distinguishes
processing progress, inferred facts and unresolved semantic coverage. After bounded item
recovery, available validated work can publish with incomplete coverage; fatal errors,
stale inputs and cancellation preserve the previous committed graph. See the full
[AI project analysis guide](AI_ANALYSIS.md).


## Resumable AI analysis

SQL, SAS and dbt use independent AI file extraction with token-budgeted packing. Each
build has one active physical request. **AI budget overrides** controls a 10–50% maximum
output share (default 30%) and optional exact token overrides. Allocation is pinned for
resume; file-count, parallel-request and execution-window controls are unavailable.
Compatible resumes reuse saved successes and retain cumulative attempt/output reservations.
Unknown responses may have been billed and require the configured recovery policy or
explicit retry acknowledgement. **Retry unresolved AI work** retries only unfinished
items after partial publication. See [AI flow](user-guide/ai-analysis-flow.md) and
[controls/recovery](user-guide/ai-analysis-controls-and-recovery.md).

## Column lineage graph

In **Columns**, choose an asset and switch between **Direct references** and
**Lineage graph**. Choose a column and direction. Arrows point from inputs through
transformation boxes to outputs. Solid edges carry values; dashed edges show
selection, filter, join, rowset, partition and order context. Select a graph box or
edge, or use the keyboard-accessible **Transformation step** selector, to inspect
logic. Multiple writers remain separate choices.

**Transformation logic** shows expression, statement preview, roles, effects and
coverage. **Analyzed source file** opens the exact historical file used by Analysis,
with original line numbers, 200-line pages, search and original-byte download.
Changed or unavailable historical versions are explicitly reported. Compiled dbt
expressions identify unavailable original-source coordinate mapping.

The display fits at most 600 nodes and 1,200 edges, retaining whole transformation
units. Omission counts do not change trace completeness. The **Steps and paths**
table and exports retain the full bounded trace of up to 200 derivations.
The previous Transformation lineage route still opens the same renderer.
