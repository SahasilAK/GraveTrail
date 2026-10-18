# scripts/build/

Release inputs, never generated output. The existing broad `build/` ignore rule
requires explicitly adding new files in this directory; do not change user ignore rules.

- `hatch_assets.py` — Hatch wheel hook allowlists UI Python/CSS files, prompt Markdown/JSON and default theme; avoids unsafe directory force-includes.
- `frozen_entry.py` — PyInstaller console dispatcher: default UI, `--cli` shared Typer CLI/MCP, `--worker` detached job worker.
- `build_executable.py` — Convenience wrapper around `dataforge.build.main --target executable`.
- `smoke.py` — External wheel/frozen SQL import/lineage, real stdio MCP query and HTTP/WebSocket rendered UI checks in a temporary home.
- `smoke_docker.py` — Actual non-root image smoke, CLI analysis, rendered UI, owner restart persistence and MCP; removes only uniquely named test containers/volume.
- `windows.iss` — Inno Setup per-user x64 installer; whole bundle, Start menu/optional desktop shortcut, runtime mutex refusal, no data deletion or forced process closure.
- `windows_installer.ps1` — Explicit development/production packaging, complete payload SHA256/native-signature inventory, post-signing portable archive and initial verification evidence.
- `sign_windows.ps1` — Protected certificate-store SignTool SHA256/RFC3161 signing and independent exact publisher/chain/timestamp verification; no certificate imports or secret command arguments.
- `smoke_installer.py` — Final installer install/payload hashes/trust, real CLI/MCP/rendered UI, running-owner refusal, reinstall lineage preservation and uninstall data/settings preservation; finalize writes lifecycle evidence and post-signing checksums.

Distribution smoke also requires the GraveTrail page title and MCP server identity. Docker smoke uses gravetrail image/CLI names and uniquely named disposable runtime resources.

Frozen --cli sets the program name to gravetrail so help/errors reflect the product; worker module paths remain compatible.

Image packaging: frozen_entry.py dispatches --render-graph-image; smoke.py verifies real SVG/PNG CLI files outside checkout alongside MCP and UI startup.
