# scripts/build/

Release inputs, never generated output. The existing broad `build/` ignore rule
requires explicitly adding new files in this directory; do not change user ignore rules.

- `hatch_assets.py` — Hatch wheel hook allowlists UI Python files, prompt Markdown/JSON and default theme; avoids unsafe directory force-includes.
- `frozen_entry.py` — PyInstaller console dispatcher: default UI, `--cli` shared Typer CLI/MCP, `--worker` detached job worker.
- `build_executable.py` — Convenience wrapper around `dataforge.build.main --target executable`.
- `smoke.py` — External wheel/frozen SQL import/lineage, real stdio MCP query and HTTP/WebSocket rendered UI checks in a temporary home.
- `smoke_docker.py` — Actual non-root image smoke, CLI analysis, rendered UI, owner restart persistence and MCP; removes only uniquely named test containers/volume.

Distribution smoke also requires the GraveTrail page title and MCP server identity. Docker smoke uses gravetrail image/CLI names and uniquely named disposable runtime resources.

Frozen --cli sets the program name to gravetrail so help/errors reflect the product; worker module paths remain compatible.
