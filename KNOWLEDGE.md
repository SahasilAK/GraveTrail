# DataForge/

Local evidence-backed SQL/SAS/CSV engineering workspace. Entry: app.py; Python, Streamlit, DuckDB, SQLGlot and NetworkX.

## Project overview
Run `uv sync --locked --extra dev`, `uv run streamlit run app.py`; verify with `uv run pytest -q` and `uv run ruff check .`. Read AGENTS and plans/IMPLEMENTATION_STATUS first.

## Subfolders
- `.github/` — [.github/KNOWLEDGE.md](.github/KNOWLEDGE.md).
- `.streamlit/` — [.streamlit/KNOWLEDGE.md](.streamlit/KNOWLEDGE.md).
- `docs/` — [docs/KNOWLEDGE.md](docs/KNOWLEDGE.md).
- `plans/` — [plans/KNOWLEDGE.md](plans/KNOWLEDGE.md).
- `prompts/` — [prompts/KNOWLEDGE.md](prompts/KNOWLEDGE.md).
- `scripts/` — [scripts/KNOWLEDGE.md](scripts/KNOWLEDGE.md).
- `src/` — [src/KNOWLEDGE.md](src/KNOWLEDGE.md).
- `tests/` — [tests/KNOWLEDGE.md](tests/KNOWLEDGE.md).
- `ui/` — [ui/KNOWLEDGE.md](ui/KNOWLEDGE.md).

## Files
- `.dockerignore` — Exclude runtime data, environments and caches from Docker build context.
- `.gitattributes` — Repository text normalization policy.
- `.gitignore` — Source-control exclusions, including local runtime. Preserve separate preexisting user edits.
- `.kbignore` — Knowledge scan exclusions; this scanner uses bare-name/glob patterns rather than trailing-slash directory patterns.
- `AGENTS.md` — Repository conventions, authority, module navigation, verification commands and per-feature commit policy.
- `Dockerfile` — Optional non-root local container with persistent /data and health check; not executed in this session.
- `LICENSE` — Project license; preserve original terms.
- `README.md` — Installation, startup, first workflow, features, configuration, structure and honest limits.
- `app.py` — Entry point: configure logs, cache Store, select/create workspaces, register six st.Page scripts.
- `pyproject.toml` — Package/dependency constraints, pytest/Ruff settings, bundled prompts and runtime-safe sdist allowlist.
- `uv.lock` — Generated reproducible dependency lock; update with uv, never by hand.
