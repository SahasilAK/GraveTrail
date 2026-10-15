# ui/pages/

Feature scripts registered by app.py through st.Page/st.navigation. Test each page with AppTest and custom graph behavior in the real browser.

## Files
- `builder.py` — Input selection/import, filtered inventory, analyze/rebuild/validate, diagnostics/source viewer and optional AI.
- `columns.py` — Direct-only column usage metrics, filters, grouping, evidence and report downloads.
- `dashboard.py` — Inventory counts, health, hotspots and recent runs with useful empty states.
- `explorer.py` — Exact asset search, dependency trees, focused graph, evidence-linked source panel and graph/path/source exports.
- `settings.py` — Parsing/storage/performance/visualization/privacy settings and provider form routing. Host roots/storage are startup environment settings.
- `tools.py` — Code search, provenance-labeled dictionary, downstream impact and run snapshot comparison.
