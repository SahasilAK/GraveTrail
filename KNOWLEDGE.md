# GraveTrail/

## Project overview
Local evidence-backed SQL/SAS/CSV/dbt engineering workspace. Python 3.11+, Streamlit UI, DuckDB persistence, SQLGlot static parsing, NetworkX investigation, Typer CLI and MCP SDK. Distribution/primary commands use gravetrail; Python package, DATAFORGE_* variables, storage paths and legacy command aliases retain dataforge compatibility.

Application entry: `app.py`; installed/frozen UI entry: `dataforge.launcher:main`; automation entry: `dataforge.cli:app`. Start a disposable home with `uv run gravetrail-ui --home <path>`. One process owns a DuckDB home; do not open it concurrently through independent UI/CLI/MCP processes.

API credentials default to session memory. Optional keyring persistence explicitly approves Windows Credential Manager with current-user/local-machine persistence; session/saved references bind data home/workspace/profile/recipient. Legacy environment references remain available, and agents need exact launch grants for saved references.

## Subfolders
- `.github/` — test/security/docs/release workflows and contribution templates; [map](.github/KNOWLEDGE.md).
- `.streamlit/` — UI defaults; [map](.streamlit/KNOWLEDGE.md).
- `docs/` — public guides, tutorials, developer architecture and reviewed assets; [map](docs/KNOWLEDGE.md).
- `src/` — domain/service package; [map](src/KNOWLEDGE.md).
- `ui/` — Streamlit presentation and components; [map](ui/KNOWLEDGE.md).
- `prompts/` — versioned manual/project assistance instructions and schemas; [map](prompts/KNOWLEDGE.md).
- `scripts/` — reproducible qualification, builds/releases and docs tooling; [map](scripts/KNOWLEDGE.md).
- `tests/` — isolated unit/integration/protocol/AppTest regression suites and fixtures; [map](tests/KNOWLEDGE.md).
- `plans/` — optional ignored local implementation/evidence records; only its map is tracked; [map](plans/KNOWLEDGE.md).

## Root files
- `app.py` — navigation, selected workspace/home, shared UI frame and session connection scope; displays cleanup results after rerun and selects a surviving/default workspace before rendering its selector. Domain decisions stay in services.
- `pyproject.toml` / `uv.lock` — dependency/build/entrypoint/test/lint contracts and generated exact lock. Temporary Pillow metadata override also lives in `dependency-overrides.txt`; see SECURITY.md before changing it.
- `README.md` — branded banner, live-docs link, status badges and quick navigation; “Nothing stays buried. Every dependency leaves a trail.” headline, product introduction, illustrative lineage, expandable real fixture screenshot and pinned-version onboarding; public docs entry point.
- `mkdocs.yml` — explicit navigation/asset publication list, theme and strict site configuration. Docs builder checks inventory, routes/headings, links/search and exact output contents.
- `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE` — contribution entry, security/reporting/compatibility policy and license.
- `Dockerfile`, `compose.yaml`, `.dockerignore` — container build/runtime/ownership and build-context policy; platform evidence is separate from source configuration.
- `.gitattributes`, `.gitignore`, `.gitleaks.toml`, `.kbignore` — text normalization, source/runtime exclusions, narrowly scoped secret exceptions and local knowledge-scan rules.

## Core contracts
Imported programs/templates remain data and never execute. Preserve original file/version/hash/coordinates and exact evidence. Parsers return ParseResult; services resolve identities and publish a coherent transaction. Direct column usage and transformation derivations are different queries. Ambiguity and traversal/coverage limits stay explicit.

Current project analysis offers static or independent AI. Protocol5 extraction validates provenance/shape/internal consistency without static semantic approval; AI facts remain inferred with semantic_coverage_not_proven. Durable checkpoints/recovery are distinct from atomic publication. Runtime credentials stay scoped or referenced, never stored secret values or job payloads. CLI/MCP enforce launch plus workspace/source/effect grants.

Use `uv sync --locked --extra dev`, focused pytest suites, then `uv run pytest -q` and `uv run ruff check .` for application changes. Docs use the locked docs group and `python scripts/docs/build.py`; source inventory requires the pinned baseline in Git history (CI checkout fetch-depth0). Context maps are tracked but excluded from the public site/package; application homes, site output, environments and local evidence are not source.
