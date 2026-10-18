# Build and release GraveTrail

All distributions run the existing application and shared Python services. Build from
the repository root with Python 3.11+ and `uv`; Docker additionally needs a running
Docker daemon. Executable builds use a separate, locked Python 3.11 environment and
PyInstaller. They produce a console application with a browser UI.

```console
uv sync --locked --extra dev
uv run gravetrail-build --target python
uv run gravetrail-build --target docker --output dist/container
uv run gravetrail-build --target executable
uv run gravetrail-build --target all
uv run gravetrail-build --verify
uv run gravetrail-build --verify --output dist/container
```

`--root PATH` selects the source checkout; `--output PATH` selects the artifact
directory (default `dist/`, relative to the current directory). Run builds against
a stable checkout. Do not run independent builds into the same output directory
concurrently. `all` sequences the targets. Runtime homes and build outputs are
excluded from the container context. Build subprocesses receive a small allowlist
of operating-system variables and do not inherit provider credentials or the
application's runtime configuration.

## Artifacts and verification

| Output | Contents |
|---|---|
| `dist/python/*.whl` | Installable application, UI pages, prompts and default theme |
| `dist/python/*.tar.gz` | Source distribution, including release/build tooling |
| `dist/gravetrail-VERSION-OS-ARCH.zip` | Windows executable and complete companion directory |
| `dist/gravetrail-VERSION-OS-ARCH.tar.gz` | Linux/macOS executable and companion directory |
| `dist/docker-image.json` | Local Docker image tag, content ID, OS and architecture |
| `dist/manifest.json`, `dist/SHA256SUMS` | Version/platform/build metadata, artifact sizes and SHA-256 hashes |

The Docker target builds a local image, rather than exporting an image tarball or
publishing to a registry. Its manifest hashes the image metadata document. Use the
recorded content ID to identify the local image. Executables are built for the host
OS and architecture; this is not cross-compilation. Keep the complete extracted
`gravetrail/` directory together. Never distribute just `gravetrail.exe`.

`--verify` checks every manifest entry, size, checksum and the checksum-list contents;
it rejects paths escaping the artifact directory. Checksums detect modification,
not publisher identity. Builds are versioned and dependency-locked, but binary
byte-for-byte reproducibility is not promised: timestamps, toolchain and OS differ.
Executables are unsigned; code signing, notarization and installers are not provided.

## Python installation and launches

Install a wheel in a clean virtual environment:

```console
python -m venv .venv
python -m pip install dist/python/gravetrail-0.1.0-py3-none-any.whl
gravetrail-ui --no-browser
gravetrail --json workspace list
gravetrail mcp
```

Activate the environment first (`.venv\Scripts\Activate.ps1` in PowerShell or
`source .venv/bin/activate` on Linux/macOS). The command `gravetrail ui` uses the same
launcher. `gravetrail-ui` accepts `--home PATH`, `--port PORT`, `--address HOST`, and
`--no-browser`. It forwards additional Streamlit options. Loopback is the default.
Initialization runs the existing DuckDB migrations before serving.

The frozen application accepts those same UI flags. Use
`gravetrail.exe --cli --json workspace list` on Windows, or
`./gravetrail --cli --json workspace list` on Linux/macOS. For MCP, append `mcp`
after `--cli` and any global CLI options. The frozen dispatcher also supports the
existing detached job worker; no second application implementation is maintained.

## Writable runtime data

`DATAFORGE_HOME` or explicit `--home` selects the runtime home. Source development
launches default to `.dataforge/` in the current directory. Installed/frozen defaults:

| OS | Default home |
|---|---|
| Windows | `%LOCALAPPDATA%\DataForge` |
| Linux | `$XDG_DATA_HOME/dataforge`, otherwise `~/.local/share/dataforge` |
| macOS | `~/Library/Application Support/DataForge` |

Installed/frozen launchers copy the default theme once to
`HOME/.streamlit/config.toml`, preserving later edits and an explicitly supplied
`DATAFORGE_THEME_CONFIG` path. Database, blobs, jobs and theme changes live outside
the installed package/bundle. Updates replace application files and retain this
home; back up the home with all owners stopped before upgrading.

## Docker and Compose

The image uses a multi-stage build, `uv sync --locked --no-dev --no-editable`,
Python slim, UID/GID 10001 and `/data` for persistence. Only the runtime virtual
environment enters the final stage. The checkout, tests, PyInstaller, local databases
and developer environments are absent from that stage. A strict context allowlist
includes only required build inputs; the wheel hook similarly allowlists UI and
prompt assets. Provider tokens are never build arguments.

```console
docker compose --profile ui up --build -d
docker compose --profile ui logs -f
docker compose --profile ui down
docker compose --profile mcp run --rm --no-deps mcp
```

The UI binds host loopback port 8501; `DATAFORGE_UI_PORT` changes the host port.
The named `dataforge-data` volume retains runtime files after containers stop.
`docker compose down` retains that volume. Removing it with `down -v` permanently
removes the data and is not part of routine shutdown or upgrades.

Choose one owner at a time. Both profiles use the same container name to prevent
simultaneous normal `up` deployments; DuckDB also refuses conflicting database
owners. Stop the UI before one-off CLI/MCP containers. For example, after building
with Compose:

```console
docker compose --profile ui down
docker run --rm -v dataforge_dataforge-data:/data gravetrail:local gravetrail --json workspace list
docker compose --profile mcp run --rm --no-deps mcp
```

The default volume name assumes the default Compose project name `dataforge`.
Custom project names change it. MCP uses stdio and exposes no network port. Compose
does not inject credentials by default. For a required provider, use explicit
runtime forwarding such as `docker compose --profile mcp run --rm -e DATAFORGE_OPENAI_API_KEY mcp`.
Supply the host variable in that launching process; do not place it in the repository.
Bind-mounted homes must be writable by UID 10001. Shared/network DuckDB ownership
is unsupported; consult [MCP integration](MCP_INTEGRATION.md).

## Reusable smoke checks and CI

After a wheel installation, run the smoke driver using the project's development
environment; point `--python` to the clean installation's interpreter:

```console
uv run python scripts/build/smoke.py --python dist/wheel-smoke/Scripts/python.exe
uv run python scripts/build/smoke.py --executable dist/.build/bundle/gravetrail/gravetrail.exe
uv run python scripts/build/smoke_docker.py --image gravetrail:0.1.0
```

On Linux/macOS substitute `bin/python` and `gravetrail` for Windows paths. These
checks create isolated temporary homes; Docker additionally uses a uniquely named
temporary volume/container and removes only those resources. They exercise real
SQL import, lineage traversal, stdio MCP initialization/query, HTTP health and a
rendered Streamlit WebSocket session. The Docker check also verifies non-root
execution and persistence across independent container owners. This focused smoke
does not replace full SQL/SAS fixture and interactive settings testing.

`.github/workflows/release.yml` runs on `v*` tags, manual dispatch, or as a reusable
workflow. Tag versions must match `pyproject.toml`. Native jobs on Windows, Linux
and macOS run the suite, build and smoke the executable, install and smoke the
wheel, verify checksums and upload Actions artifacts. A Linux job builds and checks
the container; the standalone publishing workflow skips that container job.
Running **release artifacts** directly retains the build-only behavior.

## Publish a standalone GitHub Release

Merge `.github/workflows/publish-release.yml` into the repository's default branch
before using it. It appears in **Actions → Publish standalone release → Run workflow**.
Select the default branch, enter the exact committed project version (for example,
`0.1.0`), and run it. Stable `X.Y.Z` versions are supported; do not prefix the input
with `v`. If you are preparing a new version, update it first:

```console
uv version 0.2.0
uv lock --check
```

Commit both `pyproject.toml` and `uv.lock`, review and merge them, then dispatch with
`0.2.0`. The workflow does not make version-bump commits. Mismatched versions,
non-default-branch runs and existing version tags fail before native builds start.

The workflow reuses all three native builds and their real executable/wheel smoke
checks. Publication waits for every native job, downloads their artifacts without
merging platform directories, and verifies each original manifest, size and checksum.
It requires one version-matching executable archive per OS. It publishes the three
standalone archives plus a consolidated `manifest.json` and `SHA256SUMS`; Python
packages remain available in Actions artifacts. The consolidated manifest's platform
and Python fields describe the publishing runner; each archive filename identifies
its target OS and architecture.

Only after those checks does the publishing job create `vX.Y.Z` at the exact dispatch
commit and publish **GraveTrail vX.Y.Z** under the repository's Releases tab. It uses
only the built-in `GITHUB_TOKEN` with `contents: write` in that job. No personal token,
provider key, additional account connection or signing certificate is required.
Repository rules still apply: restrictions on tag creation or token write permissions
can block publication. The workflow never overwrites an existing tag or release.
If publication fails after creating the tag, inspect any draft release and uploaded
assets before deliberately removing the failed draft/tag or selecting a new version;
a rerun cannot silently replace them.

Notes always include GitHub-generated changes, up to 100 commits since the previous
reachable version tag, the exact source SHA, download/startup instructions and upgrade
guidance. **Try Copilot highlights** defaults to enabled. A separate job uses the
same short-lived token with `copilot-requests: write`, a pinned Copilot CLI, no tools,
no built-in MCP servers, no repository instructions and a 90-second request timeout.
Only bounded commit records are provided to the model. Its highlights are labeled
AI-generated and supplement the original change records.

Copilot can use the built-in token in personal repositories (billed to the owner's
seat) and organization repositories (subject to organization policy/billing). It uses
Copilot credits, with a soft one-credit response limit. Disable the checkbox to skip
AI entirely. Missing entitlement, policy/auth failures, CLI installation errors,
timeouts or unusable responses retain the normal notes and do not block publication.
See [GitHub's Copilot Actions authentication guide](https://docs.github.com/en/copilot/concepts/agent-capabilities/agent-powered-workflows-and-operations/copilot-cli-in-github-actions)
and [GitHub CLI release publishing](https://cli.github.com/manual/gh_release_create).

The workflow does not publish to PyPI or a container registry, sign/notarize binaries,
or build installers. GitHub-generated tags created with `GITHUB_TOKEN` do not start
another tag-triggered Actions build. Native platform support and publication are
established only when the hosted workflow actually passes; local configuration
validation is not a hosted release test.

The build approach follows the documented [uv Docker integration](https://docs.astral.sh/uv/guides/integration/docker/),
[PyInstaller collection flags](https://pyinstaller.org/en/stable/usage.html), and
[Hatch build-hook API](https://hatch.pypa.io/latest/plugins/build-hook/reference/).

## Verification ledger (2026-10-16)

- Windows Python 3.11.16: focused distribution regressions cover platform homes,
  copy-once themes, tamper/missing/unsafe artifacts, credential-free build
  environments and real wheel/sdist builds with dummy secret/database canaries.
- Clean Windows wheel: CLI workspace/import/lineage and stdio MCP query passed;
  HTTP health and a real rendered Streamlit session passed outside the checkout.
- Docker Desktop daemon 29.2.1, Linux amd64 image: actual build and non-root CLI,
  import/lineage, UI render, persistent volume and stdio MCP checks passed; all
  smoke containers and volumes were removed.
- Final Windows standalone: rebuilt executable passes SQL import/lineage, stdio MCP,
  HTTP health and an actual rendered WebSocket UI session. Frozen startup explicitly
  disables Streamlit development mode. Final artifacts are under `dist/release/`;
  `dataforge-build --verify --output dist/release` verifies all four manifest entries.
- Native Linux/macOS executable builds and hosted Actions runs have not been
  executed from this Windows session. The workflow supplies their verification
  gates; their presence alone is not evidence of platform support.

## GraveTrail rebrand compatibility

GraveTrail is the new application and distribution name. Use `gravetrail`,
`gravetrail-ui`, and `gravetrail-build`; the `dataforge`, `dataforge-ui`, and
`dataforge-build` commands remain compatibility aliases. Python imports and
`python -m dataforge.cli` / `python -m dataforge.launcher` stay unchanged.

When upgrading a pip installation of `dataforge-engineering-hub`, install the
GraveTrail wheel in a fresh virtual environment and launch it with the same explicit
`--home`. Stop the previous owner first. Keep the two distributions in separate
environments because both provide the `dataforge` Python package and legacy commands.

Existing `DATAFORGE_*` launch variables, `.dataforge/`, platform data directories,
`dataforge.duckdb`, and backup/configuration formats are retained so upgrades
reuse existing data and settings. Compose keeps its `dataforge` project name
and `dataforge-data` volume to reconnect to existing storage. Do not create
a second owner of the same home. No data migration is required.

Repository and documentation links still use `dataforge-engineering-hub`
until the repository is renamed after merge.

### Names intentionally retained

| Existing identifier | Reason it stays |
| --- | --- |
| `src/dataforge/`, `dataforge.*` imports and module launchers | Existing scripts, plugins and packaged asset lookups use this Python namespace. The distribution and primary commands are GraveTrail. |
| `DATAFORGE_*` launch variables and credential references | Existing launch configuration and credential authorization keep working. |
| `.dataforge/`, platform `DataForge` data homes, `dataforge.duckdb` | Existing workspaces, originals and settings reopen without moving data. |
| Backup, history and portable configuration format IDs | Previously exported files remain readable. |
| Compose project `dataforge` and `dataforge-data` volume | Upgrades reconnect to the existing physical volume. |
| `dataforge://` resources and old console commands | Compatibility aliases; new configurations use GraveTrail. |
| Supplied `dataforge_*_lineage_test_project.zip` files and their internal paths | Original test fixtures and evidence retain their exact names and bytes. |
| `dataforge-engineering-hub` repository and Pages links | The repository rename is planned after merge. |

README and guide screenshots use explicit `gravetrail-*` asset filenames and show the
GraveTrail sidebar. Any old name in their source-file selectors comes from the supplied
fixture's original path, not the application branding.
