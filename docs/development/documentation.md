# Maintain the documentation

Documentation is Markdown, reviewed alongside code. Material for MkDocs supplies search,
navigation, code copying, light/dark mode, responsive layouts and Mermaid rendering.
See [local preview and publishing](../deployment/github-pages.md) for setup.

## Find the right home

```text
README.md                    Repository introduction and quick start
docs/index.md                Documentation website landing page
docs/getting-started/         First lineage and configuration
docs/user-guide/              Task-focused how-to guides
docs/concepts/                Explanations and coverage boundaries
docs/project-types/           SQL, SAS and dbt workflows
docs/examples/                Reproducible tutorials and interactive snapshot
docs/integrations/            CLI, MCP and optional provider navigation
docs/architecture/            Architecture and coverage navigation
docs/deployment/              Runtime options and GitHub Pages publishing
docs/development/             Contribution and documentation workflows
docs/troubleshooting/         Problem-oriented help
docs/assets/                  Public branding, diagrams and styles
docs/*.md                    Existing detailed canonical references
mkdocs.yml                   Site navigation and explicit publication list
scripts/docs/                Build, link and publication inspection
.github/workflows/docs.yml   PR validation and main-only Pages deployment
```

Existing uppercase reference files retain their original URLs. Section indexes organize
them without duplicating their technical content. Keep one authoritative explanation
and link to it from the relevant workflow. Internal prompts, plans and review reports
remain ignored local context. All project `KNOWLEDGE.md` maps are tracked for humans
and agents browsing the repository; they are excluded from documentation site pages.

## Change or add a page

1. Verify behavior in the implementation, current CLI `--help`, and recorded acceptance.
   Distinguish implemented, tested, experimental and unsupported behavior.
2. Edit the relevant reference or add a substantial page under its section. Use one
   descriptive H1, short paragraphs, labeled code fences and descriptive image alt text.
3. Register a new page in `mkdocs.yml` under `nav`. An unlisted document is excluded
   from HTML and search, even if it exists under `docs/`.
4. Link to Markdown source paths relative to the current document. MkDocs rewrites
   them to site URLs. Use exact heading fragments. References outside `docs/` need
   an explicit GitHub source URL pinned to the documented implementation commit, not `../../src/...` site links.
5. Preview and build:

   ```sh
   uv sync --locked --group docs --extra dev
   uv run --group docs mkdocs serve --dev-addr 127.0.0.1:8000
   uv run --group docs python scripts/docs/build.py
   uv run --group docs pytest tests/test_documentation.py -q
   ```

6. Review desktop/mobile presentation, keyboard navigation, the supported light/dark palettes, the theme selector and search.
   Update implementation status/affected knowledge maps for substantial changes.
7. Open a pull request. After it merges to `main`, the workflow publishes relevant changes.

## Images, diagrams and motion

Keep public assets under `docs/assets/` and individually list each in
`extra.public_assets` in `mkdocs.yml`. Use SVG for original branding/diagrams. Use real,
isolated application screenshots only; never present a mockup as the running product.
Remove credentials, user paths and proprietary source before saving a screenshot.

Preserve visible keyboard focus, reduced-motion preferences and readable light/dark colors.
Fonts are system fonts, so no font service is required. Mermaid fences use Material's
supported integration; interactive Mermaid rendering can require the theme's external
Mermaid module. The static SVG diagrams remain usable without that module.

## Publication checks

`scripts/docs/hooks.py` limits source files to nav documents and named assets and rejects
unsafe paths, missing sources and symlinks. `scripts/docs/build.py` performs a clean strict
build and invokes `scripts/docs/validate.py` on the exact output destined for Pages.

The inspector checks every generated local HTML link/fragment and image, CSS resources,
repository-prefix paths, expected pages/assets, search entries and unexpected files.
Repository `blob/main` references are checked against local files before the branch is
merged. It does not perform live availability checks on every external website; review
external service links when changing integrations. Never copy an entire checkout or
runtime directory into `site/`.

## Dependency updates

Documentation tooling lives in `[dependency-groups].docs` in `pyproject.toml` and the
shared `uv.lock`; production application requirements are unchanged. To update a pin,
edit the docs group, run `uv lock`, reinstall, then run the strict build and focused
publication tests. Review the lock diff and browser rendering before committing.

CI uses the docs-only locked environment; it does not need application data, model
credentials, Docker, Node.js or a running Streamlit server to publish documentation.
The existing application and release workflows retain their own checks.

## Keep code and documentation aligned

Treat tutorials as complete working journeys, how-to guides as one task, concepts as
explanations, and reference as precise supported behavior. Keep canonical detail in
one place; section indexes orient and link. Retain old page paths and heading IDs or
provide meaningful compatibility anchors when reorganizing. Never use knowledge maps
as public pages.

When a parser, import mode, UI label, provider policy, data contract, command, export
or packaging behavior changes, review its task guide, coverage reference, example and
source-map entry together. Label unreleased behavior and update checkout instructions;
a package version alone is insufficient during development. CLI/MCP tables are tested
against actual registrations.

Regenerate the complete first-party inventory with:

```sh
uv run python scripts/docs/inventory.py
uv run python scripts/docs/inventory.py --check
uv run --group docs pytest tests/test_documentation.py tests/test_docs_inventory.py tests/test_site_themes.py -q
```

The inventory uses AST/Git paths, never imports app modules. Curated responsibilities,
contracts and extension guidance belong in the adjacent developer pages. Update affected
KNOWLEDGE maps separately, outside public navigation.

## Reproduce screenshots and diagrams

Use a disposable home such as `.dataforge/docs-capture` on a separate loopback port.
Import only tracked safe fixtures, run static analysis without credentials, and capture
actual app controls. See [capture recipes](screenshots.md) for the fixture, page, selection
and capture context for each image. Replace captions/alt text with the capture, remove
personal paths and review visible source before sharing. Do not use generated imagery
as application evidence.

Edit standalone SVG diagram sources in `docs/assets/diagrams`; preserve title/description,
legible labels and arrow meanings. For Mermaid, check actual browser rendering and
keep the SVG fallback usable when an external Mermaid module is unavailable.

## Review the executable HTML asset

The sole public HTML snapshot is `assets/examples/lineage.html`. Recreate it with:

```sh
uv run python scripts/docs/example.py
```

Review all embedded labels, evidence snippets and relative paths. Reopen the result
in a browser and test fit, zoom, pan, search, selection and keyboard access. The generator
adds a content policy blocking network use; no external scripts/assets are needed.
It uses a temporary home and no provider. Run-local IDs can change between captures.

After reviewing, update only its SHA-256 entry in `scripts/docs/hooks.py`, then run the
strict build and publication tests. Do not add general `.html` support or copy the supplied
personal export into the site. The exact-name/digest exception and sandboxed iframe keep
other HTML and all unlisted assets excluded. Browser network-disabled verification is
separate from source inspection/content-policy enforcement; record which was exercised.
