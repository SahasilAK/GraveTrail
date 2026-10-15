# ui/pages/

Feature scripts registered by app.py through st.Page/st.navigation. Test each page with AppTest and custom graph behavior in the real browser.

## Files
- `builder.py` — Input selection/import, filtered inventory, analyze/rebuild/validate, diagnostics/source viewer and optional AI.
- `columns.py` — Direct-only column metrics/filter/grouping; labels inferred schema expansions and shows both declaration and query source evidence; report downloads include schema provenance.
- `dashboard.py` — Inventory counts, health, hotspots and recent runs with useful empty states.
- `explorer.py` — Exact asset search, active lazy tree tab, focused graph, evidence-linked source panel and bounded ordered path CSV/JSON plus graph/source exports.
- `settings.py` — Parsing/storage/performance/visualization/privacy settings, validated workspace editing/configuration transfer and provider form routing. Host roots/storage are startup environment settings.
- `tools.py` — Code search, dictionary distinguishing declared SQL schema/sampled CSV/incomplete references, downstream impact and run comparison.
