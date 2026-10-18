# .github/workflows/

CI test matrix for Windows/Linux and Python 3.11/3.12; remote execution is not claimed until it runs.
All Linux jobs pin ubuntu-24.04. Action releases are commit-pinned and use Node24,
including the nested upload action in the Pages composite; test commands also install Node24.

## Files
- `tests.yml` — Pull-request-only uv lock install, Ruff and pytest on Windows/Linux Python 3.11/3.12; branch pushes do not launch duplicate test runs. Node enables JS syntax regression.
- `security.yml` — Read-only push/PR/weekly/manual scans: checksum-pinned Gitleaks checks full reachable history and archived tracked files/nested ZIPs using root .gitleaks.toml; pinned pip-audit checks every locked group/extra across Windows/Linux Python 3.11/3.12. Findings fail jobs; secrets are redacted and checkout credentials are not persisted.
- `release.yml` — Version-tag/manual native Windows/Linux/macOS builds, suite and real wheel/executable smoke; Linux container build/persistence; checksummed Actions artifacts. No remote runs/publication implied.

- `docs.yml` — Read-only PR strict build/publication inspection in a locked docs-only environment. Relevant main pushes/manual main runs upload only site/; deploy alone has Pages/OIDC write using the github-pages environment. Pages must be enabled separately.

- `publish-release.yml` — Manual Windows x64 release; optional exact version overrides major/minor/patch based on highest published stable release (initial 0.0.0). Branch-safe dry_run defaults true; public publishing/production require default branch. Explicit named artifact download fixes single-artifact flattening. Publisher repeats installed payload/trust/lifecycle checks, generates notes, retains assets and publishes draft-then-public at exact source SHA. Copilot fallback remains optional.
- `release.yml` additionally accepts resolved release_version and explicit development/production mode. Checkout-only uv version/lock materialization; Windows Inno Setup 7.1.0 checksum pin, complete inventory, protected signing and installed lifecycle checks before final manifest/upload. Development uses hosted Windows; production requires protected windows-production and restricted self-hosted gravetrail-signing runner/key. Existing other-platform and container build paths remain available.

Release build/upload/download patterns and executable smoke paths use gravetrail consistently; repository and Pages references now use SahasilAK/GraveTrail and /GraveTrail/.
