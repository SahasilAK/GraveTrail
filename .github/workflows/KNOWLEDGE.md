# .github/workflows/

CI test matrix for Windows/Linux and Python 3.11/3.12; remote execution is not claimed until it runs.

## Files
- `tests.yml` — uv lock install, Ruff and pytest on Windows/Linux Python 3.11/3.12; Node enables JS syntax regression.
- `release.yml` — Version-tag/manual native Windows/Linux/macOS builds, suite and real wheel/executable smoke; Linux container build/persistence; checksummed Actions artifacts. No remote runs/publication implied.
