# tests/fixtures/

Deterministic source inputs; parser and workflow tests consume these files.

## Subfolders
- `scenario/` — [scenario/KNOWLEDGE.md](scenario/KNOWLEDGE.md).
- `vendors/` — [vendors/KNOWLEDGE.md](vendors/KNOWLEDGE.md): labeled SQL dialect and SAS procedure examples.

- `parity_capabilities.json` — Checked-in48-ID contract for implemented/restricted state, actual routes/tools, scope/effects/permissions/reasons; verified against catalog plus actual Typer help/MCP schemas.
- `ai_analysis/` — Versioned synthetic SQL/SAS originals with separate fact/abstention gold; never model context. See [ai_analysis/KNOWLEDGE.md](ai_analysis/KNOWLEDGE.md).

E01 covers HTML/JSON plus fitted SVG/PNG graph artifacts; its catalog description is pinned by test_parity_coverage.py.
