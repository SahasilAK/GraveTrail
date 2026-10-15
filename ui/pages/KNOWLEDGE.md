# ui/pages/

Feature scripts registered by app.py through st.Page/st.navigation. Test each page with AppTest and custom graph behavior in the real browser.

## Files
- `builder.py` — Input/import, inventory, analyze/rebuild/validate, diagnostics/source viewer and lazy unresolved-review/manual AI panels. No automatic provider requests.
- `columns.py` — Direct-only column metrics/filter/grouping; labels inferred schema expansions and shows both declaration and query source evidence; report downloads include schema provenance.
- `dashboard.py` — Inventory counts, health, hotspots and recent runs with useful empty states.
- `explorer.py` — Exact asset search, lazy tree tab, workspace-scoped direction/collapse defaults, shared live/export appearance, evidence-linked source panel and bounded path CSV/JSON plus graph/source exports.
- `settings.py` — Parsing/storage/performance/privacy settings; app-wide native theme picker, workspace visualization/source defaults, configuration transfer, recoverable history and provider forms. Host roots/storage are startup environment settings.
- `tools.py` — Code search, dictionary distinguishing declared SQL schema/sampled CSV/incomplete references, downstream impact and run comparison.

Parsing Settings accepts validated default job/session IDs and relative-folder assignments;
reanalyze to apply new identity boundaries. Persistent assets remain shared.
