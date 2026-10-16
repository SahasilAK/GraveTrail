# DataForge engineering guidance

The authoritative product specification is `docs/prompts/MASTER_PROMPT.md`. Read it and
`plans/IMPLEMENTATION_STATUS.md` before continuing implementation. Work autonomously.

- Python 3.11+, Streamlit UI, SQLGlot, NetworkX, DuckDB. No imported code is executed.
- `src/dataforge/`: domain, storage, ingestion, parsers, graph, exports, LLM, services.
- `ui/`: presentation only. `app.py` is the entry point. `tests/` includes real fixtures.
- Use the SQL and SAS project ZIPs in `tests/sample_data/` for future application testing.
  Each has 85 tables, 128 lineage edges and seven ETL layers; SAS adds 16 temporary WORK
  datasets. Import either ZIP, select only its script extension (`.sql` or `.sas`),
  generate lineage and search `pub.all_kpis`: trace all seven layers to all 16 sources.
  See `tests/sample_data/KNOWLEDGE.md` for fixture details and verification limits.
- Preserve evidence (file, exact statement, line range, method) for every relationship.
- Prefer unresolved diagnostics to guessed dependencies. Never merge ambiguous names.
- Runtime data belongs under `DATAFORGE_HOME` (default `.dataforge/`, ignored).
- Credentials come from named environment variables; never persist their values.
- OmniRoute testing must use model `auto`, endpoint `http://localhost:20128/v1`, and the
  existing `OMNIROUTE_API_KEY` environment variable. Do not substitute fixed models/routes.
- Use parameterized SQL, safe relative paths, allowed import roots, bounded resources.
- Verify each vertical slice with pytest and the running UI. Update status and knowledge.
- Commands: `uv sync --extra dev`; `uv run pytest`; `uv run ruff check .`;
  `uv run streamlit run app.py --server.address 127.0.0.1`.
- Do not overwrite the user's preexisting `.gitignore` edits. Do not change the master prompt.
- Commit every feature or coherent feature group after testing, with a descriptive
  Conventional Commit message. Do not include unrelated user edits.

For a new parser, return `ParseResult` with operations and diagnostics; the analysis service
owns persistence and cross-file resolution. Keep Streamlit out of domain modules.
