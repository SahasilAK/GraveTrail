# ui/pages/

dbt: builder chooses project/mode/artifact paths; analysis displays coverage;
explorer adds resource/macro impact alongside the shared logical graph and column IDs.

Analysis Run delegates explicit AI controls, worker progress and validation reporting to
ui/analysis_ai.py; parser stays the unchecked default. History includes durable project runs.

Twelve focused direct scripts registered by app.py using native st.Page/st.navigation.
Existing /builder, /explorer, /columns, /tools and /settings routes remain supported.

## Files
- `lineage_builder.py` — Sidebar authoring page with Schemas & data entry / Build lineage sections. Manual schema editing, bounded import preview, explicit linked-column deletion, auto-saved canvas, native relationship entry, JSON/HTML/Excel/CSV exports and confirmed JSON replacement.
- `dashboard.py` — Overview: contextual next action, real inventory/evidence counts, hotspots, health and recent work; no automatic analysis.
- `builder.py` — Sources: Import (ZIP/directory/allowed host, report and next Analysis link) / Inventory (filter, compact columns, report exports, lazy original source and metadata).
- `analysis.py` — Run / Diagnostics / History; explicit analyze selected/all, force rebuild and evidence validation, scoped completion notice and next actions. Delegates lazy sections to analysis_sections.py.
- `explorer.py` — Lineage: exact asset/All, graph focus and Back/Forward history; direction-aware graph/tree evidence. Asset-specific paths export JSON/CSV and shared XLSX with reviewable scope, temporary/evidence/excerpt controls, explicit preparation and download without rerun.
- `columns.py` — Direct column usage/comma-term filtering/grouping, inferred wildcard provenance, declared schema evidence and exports. Unfiltered distinct used and conservatively known unused names have individual/list copy controls; unused panel stays lazy. Shares valid asset context with Lineage/Impact.
- `transformations.py` — Focused exact-column upstream/downstream traces with bounded depth/status, coverage states, roles and uncollapsed paths; lazy original-version evidence (200 lines/12k chars), guarded selector identities and bounded CSV/JSON exports with completeness markers.
- `tools.py` — Code search / Data dictionary / Impact analysis. Run comparison now belongs to Analysis → History.
- `settings.py` — Workspace settings: Parsing / Resources / Appearance. Shared extracted forms preserve eleven native theme presets, parsing/job identities, resource limits and graph/source defaults.
- `connections.py` — Connections & AI: Providers & routing / Privacy, external-request status, session credentials, logging/host roots and shared privacy validators.
- `management.py` — Data management: Storage & transfers / Backups & integrity / Cleanup & recovery / History & staging. Existing storage allowlists, mandatory backup/typed cleanup confirmation and new-home restore remain intact.
- `automation.py` — Automation & access: existing agent permissions, source disclosure/budgets, client setup and real in-process MCP handler test.

Tests: AppTest route/state/guard checks plus real-browser review of graph, theme,
responsive layouts, first import/analysis journey and actual offline HTML download.
Hidden source/AI/tree/maintenance bodies are gated. Business rules stay in src/dataforge.

Explorer Export prepares fitted SVG/PNG through services.export_graph_image; summarizes scope/appearance, explains pan/zoom independence and metadata privacy, and keeps generation errors in place. Images are built only on Prepare and are not cached.
