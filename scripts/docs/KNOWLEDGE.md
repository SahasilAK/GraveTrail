# scripts/docs/

Documentation tooling with an explicit publication boundary. Crimson Forge is the first/default site palette; saved visitor preferences still persist. Locked docs-only builds need no app imports/runtime home/provider; example authoring is separate.

- `build.py` — from repository root runs inventory --check, strict clean MkDocs build and exact artifact validation; resolves cwd internally.
- `hooks.py` — loads stdlib-only shared theme registry through runpy, configures palettes/CSS and filters public nav/assets. Rejects unsafe/missing/symlink paths; executable HTML only at the exact reviewed path/SHA-256 in PUBLIC_HTML_SHA256. Preserves theme assets and lowercase route compatibility.
- `inventory.py` — stdlib Git-path/AST full first-party index; existing links pin baseline1864dc8, new files labeled; no module execution. --check detects coverage/docstring/symbol drift without writes. Requires baseline Git history.
- `validate.py` — HTML/CSS links/anchors/resources/project prefix, exact output/search inventory and retained legacy routes/heading IDs. Exports inspect_site/inspect_inventory/inspect_legacy_routes/validate; CLI python -m scripts.docs.validate.
- `legacy_routes.json` — retained baseline42 rendered route/heading contracts; not an excuse to remove new pages or silently rewrite historical anchors.
- `example.py` — import-safe fixture HTML authoring utility; render_example lazily imports app services, analyzes tracked scenario in TemporaryDirectory, strips workspace metadata, adds CSP and prints digest for review. Normal docs build uses saved HTML.

Tests: tests/test_documentation.py exercises actual CLI/MCP references, allowlist/digest/CSP, route/link/inventory preservation; tests/test_docs_inventory.py checks complete AST-only inventory/freshness. CI docs/tests fetch-depth0 preserves baseline objects. Regenerate inventory after tooling/workflow/test additions; do not update an HTML digest without reviewing exact bytes/evidence/interactions.
