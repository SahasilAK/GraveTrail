# ui/

Shared Streamlit presentation and provider/assistance forms. Uses dataforge services; source content is loaded lazily.

## Subfolders
- `pages/` — [pages/KNOWLEDGE.md](pages/KNOWLEDGE.md).

## Files
- `__init__.py` — Package marker; no business behavior.
- `assistance.py` — Explicit source-range/task AI action with hash-pinned preview and durable result ID; delegates validated/quarantined response presentation and inferred merge.
- `assistance_result.py` — Reads AI record by workspace/ID, displays quarantine/validated result/usage and separately merges inferred claims with refresh; no source/response copies in session state.
- `common.py` — Shared context/store/graph caches, exact asset/source choices reset when IDs leave current options; styled graph v2 component, downloads and original-version viewer with lazy complete source and workspace line-number preferences.
- `lineage_tree.py` — render_tree loads only open native expander branches, bounded by depth/visible entries; expand-to-depth/collapse controls and cycle stops. Stores control state only.
- `provider_settings.py` — Profile forms, env-key references, connection/model discovery and task/fallback routing; no secret-value storage.
- `themes.py` — Eight named native dark/light presets, TOML-aware atomic config updates preserving unrelated settings, preset detection and bounded native reload acknowledgement. Settings Visualization owns the picker; app-wide deployment configuration.
- `unresolved_review.py` — Offline bounded diagnostic selector/context preview with adjustable source ranges and explicit hash-pinned review button; uses shared durable result presentation.
- `workspace_history.py` — Lazy native Settings panel previews bounded history eligibility, archives with retained recovery and restores missing records; all persistence lives in maintenance.py.
