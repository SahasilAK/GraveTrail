# GraveTrail/

Local evidence-backed SQL/SAS/CSV engineering workspace. Entry: app.py; Python, Streamlit, DuckDB, SQLGlot and NetworkX.

## Project overview
Run `uv sync --locked --extra dev`, `uv run streamlit run app.py`; verify with `uv run pytest -q` and `uv run ruff check .`. Read local AGENTS and plans/IMPLEMENTATION_STATUS when supplied; this map and child maps are tracked repository documentation.

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
- `.gitleaks.toml` — Extend default secret detectors; only exact dummy redaction-test credentials in tests/test_connections.py are allowlisted, requiring both path and secret matches.
- `.gitignore` — Source-control exclusions, including local runtime. Preserve separate preexisting user edits.
- `.kbignore` — Knowledge scan exclusions; this scanner uses bare-name/glob patterns rather than trailing-slash directory patterns.
- `AGENTS.md` — Repository conventions, authority, module navigation, verification commands, current OmniRoute auto/best-reasoning route and per-feature commit policy.
- `Dockerfile`, `compose.yaml` — Locked multi-stage non-root image, persistent /data, UI/MCP owner profiles and health check; actual Linux container smoke verified on Docker Desktop.
- `LICENSE` — Project license; preserve original terms.
- `README.md` — “Nothing stays buried.” headline and “Every dependency leaves a trail.” supporting line, live documentation link, animated hero, installation, first workflow, features and honest limits. Branding is shared with the app sidebar, Pages homepage/banner and site description.
- `app.py` — Entry point: shared frame, workspace dialog and context guards; eleven native routes grouped into Workspace, Explore and Administration. Transformation lineage follows Columns; existing builder/explorer/settings URLs remain valid.
- `pyproject.toml` — Package/dependency constraints (including pure-Python XlsxWriter), CLI aliases, MCP SDK/Typer, pytest/Ruff settings, bundled prompts and runtime-safe sdist allowlist.
- `uv.lock` — Generated reproducible dependency lock; update with uv, never by hand.

Storage selection is per-session and startup-allowlisted (DATAFORGE_STORAGE_LOCATIONS); app.py
opens the validated home before workspace navigation. Default remains DATAFORGE_HOME.

Documentation: `mkdocs.yml` and separate locked docs group build 38 public pages with scripts/docs/build.py. CONTRIBUTING.md and SECURITY.md are root entry points. README is a product introduction with real fixture imagery. Site output is ignored/excluded; canonical uppercase guide sources remain.

Context policy: All project KNOWLEDGE.md maps are tracked so humans and agents can navigate a clean checkout, including maps inside otherwise ignored context folders. AGENTS.md, .kbignore, .codex/ and implementation records remain local-only. New branches use feature/, bugfix/ or another appropriate prefix; never codex/.

GraveTrail branding: distribution/commands use gravetrail (legacy dataforge commands remain aliases). Internal Python package, DATAFORGE_* variables, .dataforge/platform homes, database/portable formats and Compose project/volume stay compatible. Repository links, origin and the case-sensitive Pages prefix use SahasilAK/GraveTrail and /GraveTrail/. Build outputs and MCP display/resource aliases use GraveTrail.

Rebrand audit: frozen CLI program name, sample install paths and cleanup guide use GraveTrail; README/guide screenshot references use gravetrail-prefixed real captures. BUILD_AND_RELEASE lists intentionally retained compatibility names.

Parser9: bounded PostgreSQL SQL procedure dollar bodies, Snowflake literal dynamic SQL and
quote-aware known-value SAS %LET expressions with stale-binding invalidation. Imported code
never executes; original wrapper/block evidence survives. docs/TESTING.md is the tracked
current acceptance matrix; optional local status/matrix ledgers retain dated historical records.

Palette update: app retains Ocean dark (default)/Ink dark plus nine shared semantic palettes; Pages retains Ink dark/Celadon light plus those nine. Supplied icon and two-color wordmark; names, layout and interactions stay unchanged.

UI redesign: Apple Design guides system typography, native theme tokens and scoped presentation CSS. Sources and Analysis are separate; administration has four focused routes. App/Pages share the visual language, with no entrance animations or remote font dependency. Navigation/state and delivery checklist: docs/USER_GUIDE.md; local plan: plans/UI_REDESIGN.md when available.

Column transformations: parser11/migration5 add scoped SQL/PROC SQL and bounded DATA-step
derivations alongside direct usage. `transformations.py` shares identity, materialization,
catalog and bounded traversal across the new page, CLI and MCP. Coverage/upgrade limits:
docs/TRANSFORMATION_LINEAGE.md; benchmark: scripts/benchmark_transformations.py.

Static graph images share the browser scene and filtered graph across UI, CLI and MCP. resvg-py wheels provide PNG without Cairo/browser runtimes; Docker includes DejaVu fonts and frozen builds dispatch a private render worker. Limits and packaging evidence: docs/USER_GUIDE.md and docs/BUILD_AND_RELEASE.md.

AI project builds: parser12/migration6 preserve the offline parser default and add explicit
hybrid/experimental AI modes, complete immutable units, source-backed validation, optional
bounded review, staged atomic publication and offline accepted-fact reuse. UI, CLI and MCP
share analysis_service/project_analysis; prompts stay in root prompts/. Public behavior,
flow diagram and qualification limits: docs/AI_ANALYSIS.md. Current parity: 48 capabilities,
103 CLI routes/29 groups and 83 MCP tools. Two synthetic live SQL smoke cases are development
evidence only; source/packaging checks and open release gates are dated in docs/TESTING.md.

README and Pages position local parser analysis as the primary default with no source sent to AI; optional AI/hybrid supports additional investigation in complex projects, with explicit disclosure and no completeness guarantee.

Parser13/validator2: SAS PROC SQL typed constants preserve complete generated usage text; their value derivations remain unresolved. DML follows reachable USING/scalar subqueries with outer-only alias ownership. Semantic versions pin AI caches and continuation. Banking archive scorer masks fixture answers; table-only manifests cannot qualify column precision. Evidence: docs/TESTING.md.
