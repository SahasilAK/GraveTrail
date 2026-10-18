# .github/workflows/

CI test matrix for Windows/Linux and Python 3.11/3.12; remote execution is not claimed until it runs.
All Linux jobs pin ubuntu-24.04. Action releases are commit-pinned and use Node24,
including the nested upload action in the Pages composite; test commands also install Node24.

## Files
- `tests.yml` — Pull-request-only uv lock install, Ruff and pytest on Windows/Linux Python 3.11/3.12; branch pushes do not launch duplicate test runs. Node enables JS syntax regression.
- `security.yml` — Read-only push/PR/weekly/manual scans: checksum-pinned Gitleaks checks full reachable history and archived tracked files/nested ZIPs using root .gitleaks.toml; pinned pip-audit checks every locked group/extra across Windows/Linux Python 3.11/3.12. Findings fail jobs; secrets are redacted and checkout credentials are not persisted.
- `release.yml` — Version-tag/manual native Windows/Linux/macOS builds, suite and real wheel/executable smoke; Linux container build/persistence; checksummed Actions artifacts. No remote runs/publication implied.

- `docs.yml` — Read-only PR strict build/publication inspection in a locked docs-only environment. Relevant main pushes/manual main runs upload only site/; deploy alone has Pages/OIDC write using the github-pages environment. Pages must be enabled separately.

- `publish-release.yml` — Manual default-branch stable X.Y.Z publication; project/lock/tag preflight, reused native build gates, consolidated verified archives/checksums, exact SHA tag and public Release. Optional Copilot highlights use only GITHUB_TOKEN in a separate read-only job; failure/skipping falls back to GitHub notes/commits. `release.yml` is callable with skip_container while direct tag/manual runs remain build-only.

Release build/upload/download patterns and executable smoke paths use gravetrail consistently; repository and Pages URLs remain unchanged until the post-merge rename.
