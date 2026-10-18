# ui/pages/

Ten focused direct scripts registered by app.py using native st.Page/st.navigation.
Existing /builder, /explorer, /columns, /tools and /settings routes remain supported.

## Files
- `dashboard.py` — Overview: contextual next action, real inventory/evidence counts, hotspots, health and recent work; no automatic analysis.
- `builder.py` — Sources: Import (ZIP/directory/allowed host, report and next Analysis link) / Inventory (filter, compact columns, report exports, lazy original source and metadata).
- `analysis.py` — Run / Diagnostics / History; explicit analyze selected/all, force rebuild and evidence validation, scoped completion notice and next actions. Delegates lazy sections to analysis_sections.py.
- `explorer.py` — Lineage: persistent exact asset/direction, Graph / full-width Tree, Traversal options, contextual step-wise/source details, bounded paths and deferred offline graph/source exports. Native tree tabs have durable evidence-direction state; explicit graph evidence overrides source scope.
- `columns.py` — Direct column usage/filter/grouping, inferred wildcard provenance, declared schema evidence and exports. Shares valid asset context with Lineage/Impact.
- `tools.py` — Code search / Data dictionary / Impact analysis. Run comparison now belongs to Analysis → History.
- `settings.py` — Workspace settings: Parsing / Resources / Appearance. Shared extracted forms preserve eighteen native theme presets, parsing/job identities, resource limits and graph/source defaults.
- `connections.py` — Connections & AI: Providers & routing / Privacy, external-request status, session credentials, logging/host roots and shared privacy validators.
- `management.py` — Data management: Storage & transfers / Backups & integrity / Cleanup & recovery / History & staging. Existing storage allowlists, mandatory backup/typed cleanup confirmation and new-home restore remain intact.
- `automation.py` — Automation & access: existing agent permissions, source disclosure/budgets, client setup and real in-process MCP handler test.

Tests: AppTest route/state/guard checks plus real-browser review of graph, theme,
responsive layouts, first import/analysis journey and actual offline HTML download.
Hidden source/AI/tree/maintenance bodies are gated. Business rules stay in src/dataforge.
