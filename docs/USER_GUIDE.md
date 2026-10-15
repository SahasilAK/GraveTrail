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
