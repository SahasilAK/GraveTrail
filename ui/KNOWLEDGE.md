# ui/

Shared Streamlit presentation and provider/assistance forms. Uses dataforge services; source content is loaded lazily.

## Subfolders
- `pages/` — [pages/KNOWLEDGE.md](pages/KNOWLEDGE.md).

## Files
- `temporary_cleanup.py` — Lazy Storage panel for bounded stale staging preview, explicit selection/cleanup and retained restore; safe failure messages, per-workspace notices.
- `__init__.py` — Package marker; no business behavior.
- `assistance.py` — Explicit source-range/task AI action with hash-pinned preview and durable result ID; delegates validated/quarantined response presentation and inferred merge.
- `assistance_result.py` — Reads AI record by workspace/ID, displays quarantine/validated result/usage and separately merges inferred claims with refresh; no source/response copies in session state.
- `common.py` — Shared context/store/graph caches, exact asset/source choices reset when IDs leave current options; styled graph v2 component, downloads and original-version viewer with lazy complete source and workspace line-number preferences.
- `lineage_tree.py` — Full-width compact indented lineage rows with inline file paths, level labels, scoped theme-aware tree guides, Expand all/Collapse all and optional relationship details. Native branches stay lazy, depth/entry-bounded and cycle-safe; imported labels are Markdown-escaped. Stores controls only.
- `provider_settings.py` — Profile forms, env-key references, connection/model discovery and task/fallback routing; no secret-value storage.
- `themes.py` — Fourteen native presets: original eight unchanged plus six additive orange/Nord/Rose/Sand/Mint choices. TOML-aware atomic config updates, detection and bounded reload acknowledgement. Applies only on explicit request, app-wide.
- `unresolved_review.py` — Offline bounded diagnostic selector/context preview with adjustable source ranges and explicit hash-pinned review button; uses shared durable result presentation.
- `workspace_history.py` — Lazy native Settings panel previews bounded history eligibility, archives with retained recovery and restores missing records; all persistence lives in maintenance.py.

Settings graph confidence/status filters participate in common.load_graph cache keys before
temporary contraction; app-wide log level is excluded from workspace transfers. Saved settings
rerun with notices to establish current widget identities before the next edit.

Temporary asset choices and tree labels use shared job/session labels; persisted AI results
show their job and warn when the source assignment changed.

common.current_home validates startup-allowed session storage; open_storage_home callback
opens before resetting current-session controls. Other sessions retain their stores.
