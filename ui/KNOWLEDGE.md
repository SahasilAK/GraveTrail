# ui/

Shared Streamlit presentation and provider/assistance forms. Uses dataforge services; source content is loaded lazily.

## Subfolders
- `pages/` — [pages/KNOWLEDGE.md](pages/KNOWLEDGE.md).

## Files
- `data_management.py` — Data management cleanup metrics, dry-run/typed confirmation, mandatory whole-home backup, rebuild, integrity/checkpoint/new-home restore and opt-in expired staging cleanup.
- `agent_settings.py` — Workspace agent permissions/budgets/auditing, client setup examples and actual in-process MCP handler test; discovers tools only when its local test panel opens. Publishes credential-free status-polling revocation snapshots.
- `temporary_cleanup.py` — Lazy Storage panel for bounded stale staging preview, explicit selection/cleanup and retained restore; safe failure messages, per-workspace notices.
- `__init__.py` — Package marker; no business behavior.
- `assistance.py` — Explicit source-range/task AI action with hash-pinned preview and durable result ID; delegates validated/quarantined response presentation and inferred merge.
- `assistance_result.py` — Reads AI record by workspace/ID, displays quarantine/validated result/usage and separately merges inferred claims with refresh; no source/response copies in session state.
- `common.py` — Shared context/store/graph caches with missing-asset lineage warnings, workspace-scoped asset widget identities avoid stale equal labels; source choices reset when IDs leave current options; styled graph v2 component, downloads and original-version viewer with lazy complete source and workspace line-number preferences.
- `lineage_tree.py` — Full-width compact indented lineage rows with inline file paths, level labels, scoped theme-aware tree guides, Expand all/Collapse all and optional relationship details. Native branches stay lazy, depth/entry-bounded and cycle-safe; imported labels are Markdown-escaped. Stores controls only.
- `provider_settings.py` — Shared validated profile/routing saves and safe environment references, masked session credential connect/clear, sanitized connection/model discovery and task/fallback routing.
- `themes.py` — Eighteen native presets: original fourteen unchanged plus curated Porcelain/Celadon/Ink/Aubergine. Selection descriptions distinguish the new palettes. TOML-aware atomic config updates, detection and bounded reload acknowledgement. Applies only on explicit request, app-wide.
- `unresolved_review.py` — Offline bounded diagnostic selector/context preview with adjustable source ranges and explicit hash-pinned review button; uses shared durable result presentation.
- `workspace_history.py` — Lazy native Settings panel previews bounded history eligibility, archives with retained recovery and restores missing records; all persistence lives in maintenance.py.

Settings graph confidence/status filters participate in common.load_graph cache keys before
temporary contraction; app-wide log level is excluded from workspace transfers. Saved settings
rerun with notices to establish current widget identities before the next edit.

Temporary asset choices and tree labels use shared job/session labels; persisted AI results
show their job and warn when the source assignment changed.

common.current_home validates startup-allowed session storage; open_storage_home callback
opens before resetting current-session controls. Other sessions retain their stores.

GraveTrail presentation: app page/sidebar title and agent examples use the new name. Reset/restore forms show RESET GRAVETRAIL / RESTORE GRAVETRAIL; services retain legacy exact phrases for scripted compatibility. Storage identifiers are unchanged.

- `presentation.py` — apply_style/eyebrow/empty_state/section and sync_context: theme-derived chrome, session-persistent local selectors, workspace/source revision invalidation of transient evidence and cleanup plans.
- `style.css` — App-owned key classes and semantic controls; responsive type/spacing, immediate focus/press feedback, reduced motion/transparency and contrast alternatives. Packaged by hatch_assets.py.
- `workspace_settings.py` — Extracted render_parsing/render_resources/render_appearance/render_privacy/render_storage forms; validators and service behavior unchanged. Forms include workspace identity; advanced mappings stay secondary.
- `analysis_sections.py` — Lazy diagnostics with pending-source gates and exact version pinning, optional preview/request/merge panels, recent runs/comparison.

Asset/query/direction/depth/collapse and analysis file selections persist via native session state. A shared workspace-scoped asset bridges Lineage, Columns and Impact. Source control keys include evidence scope to avoid stale browser labels; file content/AI responses never enter navigation state. Graph source ZIPs and original downloads generate on click. Tree direction has a durable non-widget copy while its tabs are hidden. Provider protocol keys include the selected profile.
