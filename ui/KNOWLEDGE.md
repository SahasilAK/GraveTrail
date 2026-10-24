# ui/

Shared Streamlit presentation and provider/assistance forms. Uses dataforge services; source content is loaded lazily.

`analysis_ai.py` exposes request-budget estimates, configured versus advertised output capacity, pending recovery and recent safe request diagnostics. Active workers retain Cancel during HTTP waits/backoff; completed split ancestry is separate from pending work.

## Subfolders
- `pages/` — [pages/KNOWLEDGE.md](pages/KNOWLEDGE.md).

## Files
- `dbt_sections.py` — Project coverage and resource/macro-impact panels over shared reports; exact resource IDs and source/generated evidence.
- `icon.png` — Supplied navy/orange icon with transparent exterior, shared byte-for-byte with Pages and packaged with the UI.
- `data_management.py` — Data management cleanup metrics, dry-run/typed confirmation, mandatory whole-home backup, rebuild, integrity/checkpoint/new-home restore and opt-in expired staging cleanup.
- `agent_settings.py` — Workspace agent permissions/budgets/auditing, client setup examples and actual in-process MCP handler test; discovers tools only when its local test panel opens. Publishes credential-free status-polling revocation snapshots.
- `temporary_cleanup.py` — Lazy Storage panel for bounded stale staging preview, explicit selection/cleanup and retained restore; safe failure messages, per-workspace notices.
- `__init__.py` — Package marker; no business behavior.
- `assistance.py` — Explicit source-range/task AI action with hash-pinned preview and durable result ID; delegates validated/quarantined response presentation and inferred merge.
- `assistance_result.py` — Reads AI record by workspace/ID, displays quarantine/validated result/usage and separately merges inferred claims with refresh; no source/response copies in session state.
- `common.py` — Shared context/store/graph caches with missing-asset lineage warnings, workspace-scoped asset widget identities avoid stale equal labels; source choices reset when IDs leave current options; styled graph v2 component, downloads and original-version viewer with lazy complete source and workspace line-number preferences.
- `lineage_tree.py` — Full-width compact indented lineage rows with inline file paths, level labels, scoped theme-aware tree guides, Expand all/Collapse all and optional relationship details. Native branches stay lazy, depth/entry-bounded and cycle-safe; imported labels are Markdown-escaped. Stores controls only.
- `lineage_navigation.py` — ALL_ASSETS sentinel, exact graph focus and workspace-scoped Back/Forward history of asset/query/direction/depth/collapse/view/Tree-tab controls; new asset navigation clears the forward branch.
- `copy_names.py` — Theme-aware v2 comma-separated name lists with individual/list clipboard controls; textContent preserves imported names safely and COPY_JS supplies offline fallback.
- `provider_settings.py` — Setup order: endpoint, credentials, connection test/discovery, fetched-model selection or manual identifier, then validated save. Works on unsaved drafts; endpoint/reference/auth/version changes and credential actions invalidate lists. Explicit process-environment input clears on submission; session-only connect/clear stays separate. Model check and task/fallback routing remain explicit.
- `themes.py` — Eleven native presets: unchanged Ocean dark/Ink dark plus nine semantic palettes. Loaded-preset detection includes sidebar colors. TOML-aware atomic config updates, detection and bounded reload acknowledgement. Applies only on explicit request, app-wide.
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

- `presentation.py` — apply_style/eyebrow/empty_state/section and sync_context: theme-derived chrome, cached supplied icon/two-color wordmark, readable action labels, session-persistent local selectors, workspace/source revision invalidation of transient evidence and cleanup plans.
- `style.css` — App-owned key classes and semantic controls; responsive type/spacing, immediate focus/press feedback, reduced motion/transparency and contrast alternatives. Packaged with icon.png by hatch_assets.py. Legacy chrome remains unchanged; new palettes add muted/card roles.
- `workspace_settings.py` — Extracted render_parsing/render_resources/render_appearance/render_privacy/render_storage forms; validators and service behavior unchanged. Forms include workspace identity; advanced mappings stay secondary.
- `analysis_sections.py` — Lazy diagnostics with pending-source gates and exact version pinning, optional preview/request/merge panels, recent runs/comparison.
- `analysis_ai.py` — AI opt-in, hybrid default, offline preview and background build/report. Preparation renders an immediate expandable native status, actual throttled file/task activity and show_time spinner; terminal duration freezes and failures/blockers expand. Automatic budgets reuse one preview; custom limits recheck. Refreshes the whole report once on terminal worker completion.

Asset/query/direction/depth/collapse and analysis file selections persist via native session state. A shared workspace-scoped asset bridges Lineage, Columns and Impact. Source control keys include evidence scope to avoid stale browser labels; file content/AI responses never enter navigation state. Graph source ZIPs and original downloads generate on click. Tree direction has a durable non-widget copy while its tabs are hidden. Provider protocol keys include the selected profile.

`analysis_ai.py` retains numeric menus with per-control Automatic/Custom origin, reset, offline recommendations, optional per-build source/context character allowance and durable Continue/retry choice. `provider_settings.py` retains selected capability metadata, explicit native inspection, invalid-draft-safe editing and automatic/custom profile limits; legacy numbers remain Custom.

Budget values have non-widget session storage so navigation cannot discard Custom ceilings; Continue inherits saved numeric limits unless Reset explicitly releases them. Manual chunk-size help distinguishes the automatic project planner.

`analysis_ai.py` preview identifies semantic source tasks, original-context projection paging and provisional review sizing. Existing Custom controls/Continue remain; the shared service owns per-batch checkpoints and final atomic publication.

Provider request timeout accepts1–3600seconds without changing saved/default values. analysis_ai progress uses journal start/stage/finish timestamps for two-second total/wait elapsed refresh and frozen terminal duration; queued state stays distinct. Assistance/review/provider checks use native show_time spinners.

`analysis_ai.py` now exposes files/request and parallel maxima immediately after enabling AI, separate execution and lifetime budgets, quota/unknown-outcome recovery and dbt project disclosure. `provider_settings.py` adds a non-secret shared quota-group label.

AI previews expose a collapsed-by-default, lazy sortable Source files and request sizes table with original characters, maximum source/full-envelope request sizes, limits and blockers. Adaptive views/component composition are described alongside the controls.

Protocol 5 supersedes older AI control notes above: analysis_ai shows one optional run output ceiling, provider/model/family, automatic token preview, stage progress and compatible continue/unknown retry. Historical reports remain readable; old protocols require a new build. provider_settings binds discovered/manual token capacity, preserves manual overrides and requires explicit legacy disclosure-limit migration. No new character/window/parallel/review controls.

Gateway settings separate connection/read inactivity and expose shared/unknown retry limits. New OmniRoute profiles default to read300/connect5/shared2/unknown2; legacy saved timeouts and disabled automatic unknown recovery remain preserved. Reports use safe connection explanations/diagnostics and require manual acknowledgement only for disabled or exhausted recovery.

`analysis_ai` budget overrides show a 10–50% maximum output share (default30), effective allowances/capacity provenance/clamps, and optional Advanced exact input/output. Shared allocator pins preview/dispatch/resume; saved profiles remain unchanged. Partial publication shows incomplete coverage and Retry unresolved AI work; reports distinguish unresolved items/unprocessed files/semantic gaps. Cancelled recovery never claims unpublished lineage was published.

Explicit slider changes become run-only output overrides, respecting real model caps/Advanced values. Ready previews are cached per session with source/settings/profile/request/credential-availability pins; invalid previews are not cached. Active progress renders before inventory and skips preparation controls; hidden budget widgets persist for the session.
