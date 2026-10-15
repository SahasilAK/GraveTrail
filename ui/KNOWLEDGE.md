# ui/

Shared Streamlit presentation and provider/assistance forms. Uses dataforge services; source content is loaded lazily.

## Subfolders
- `pages/` — [pages/KNOWLEDGE.md](pages/KNOWLEDGE.md).

## Files
- `__init__.py` — Package marker; no business behavior.
- `assistance.py` — Explicit source-range AI action, validated/quarantined response display and inferred merge followed by refresh.
- `common.py` — Shared context/store/graph caches, exact asset selection, graph v2 component, report downloads and original-version source viewer.
- `lineage_tree.py` — render_tree loads only open native expander branches, bounded by depth/visible entries; expand-to-depth/collapse controls and cycle stops. Stores control state only.
- `provider_settings.py` — Profile forms, env-key references, connection/model discovery and task/fallback routing; no secret-value storage.
- `workspace_history.py` — Lazy native Settings panel previews bounded history eligibility, archives with retained recovery and restores missing records; all persistence lives in maintenance.py.
