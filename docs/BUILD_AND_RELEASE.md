# Build and release DataForge

All distributions run the existing application and shared Python services. Build from
the repository root with Python 3.11+ and `uv`; Docker additionally needs a running
Docker daemon. Executable builds use a separate, locked Python 3.11 environment and
PyInstaller. They produce a console application with a browser UI.

```console
uv sync --locked --extra dev
uv run dataforge-build --target python
uv run dataforge-build --target docker --output dist/container
uv run dataforge-build --target executable
uv run dataforge-build --target all
uv run dataforge-build --verify
uv run dataforge-build --verify --output dist/container
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
| `dist/dataforge-VERSION-OS-ARCH.zip` | Windows executable and complete companion directory |
| `dist/dataforge-VERSION-OS-ARCH.tar.gz` | Linux/macOS executable and companion directory |
| `dist/docker-image.json` | Local Docker image tag, content ID, OS and architecture |
| `dist/manifest.json`, `dist/SHA256SUMS` | Version/platform/build metadata, artifact sizes and SHA-256 hashes |

The Docker target builds a local image, rather than exporting an image tarball or
publishing to a registry. Its manifest hashes the image metadata document. Use the
recorded content ID to identify the local image. Executables are built for the host
OS and architecture; this is not cross-compilation. Keep the complete extracted
`dataforge/` directory together. Never distribute just `dataforge.exe`.

`--verify` checks every manifest entry, size, checksum and the checksum-list contents;
it rejects paths escaping the artifact directory. Checksums detect modification,
not publisher identity. Builds are versioned and dependency-locked, but binary
byte-for-byte reproducibility is not promised: timestamps, toolchain and OS differ.
Executables are unsigned; code signing, notarization and installers are not provided.

## Python installation and launches

Install a wheel in a clean virtual environment:

```console
python -m venv .venv
python -m pip install dist/python/dataforge_engineering_hub-0.1.0-py3-none-any.whl
dataforge-ui --no-browser
dataforge --json workspace list
dataforge mcp
```

Activate the environment first (`.venv\Scripts\Activate.ps1` in PowerShell or
`source .venv/bin/activate` on Linux/macOS). The command `dataforge ui` uses the same
launcher. `dataforge-ui` accepts `--home PATH`, `--port PORT`, `--address HOST`, and
`--no-browser`. It forwards additional Streamlit options. Loopback is the default.
Initialization runs the existing DuckDB migrations before serving.

The frozen application accepts those same UI flags. Use
`dataforge.exe --cli --json workspace list` on Windows, or
`./dataforge --cli --json workspace list` on Linux/macOS. For MCP, append `mcp`
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
docker run --rm -v dataforge_dataforge-data:/data dataforge:local dataforge --json workspace list
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
uv run python scripts/build/smoke.py --executable dist/.build/bundle/dataforge/dataforge.exe
uv run python scripts/build/smoke_docker.py --image dataforge:0.1.0
```

On Linux/macOS substitute `bin/python` and `dataforge` for Windows paths. These
checks create isolated temporary homes; Docker additionally uses a uniquely named
temporary volume/container and removes only those resources. They exercise real
SQL import, lineage traversal, stdio MCP initialization/query, HTTP health and a
rendered Streamlit WebSocket session. The Docker check also verifies non-root
execution and persistence across independent container owners. This focused smoke
does not replace full SQL/SAS fixture and interactive settings testing.

`.github/workflows/release.yml` runs on `v*` tags or manual dispatch. Tag versions
must match `pyproject.toml`. Native jobs on Windows, Linux and macOS run the suite,
build and smoke the executable, install and smoke the wheel, verify checksums and
upload release artifacts. A Linux job builds and checks the container. The workflow
does not publish packages/images, create public GitHub releases or sign binaries.
Artifacts are available from the successful Actions run. Maintainers can review
them and publish through their normal release process.

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
