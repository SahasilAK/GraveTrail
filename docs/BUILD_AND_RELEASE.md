# Build and release GraveTrail

All distributions run the existing application and shared Python services. Build from
the repository root with Python 3.11+ and `uv`; Docker additionally needs a running
Docker daemon. Executable builds use a separate, locked Python 3.11 environment and
PyInstaller. They produce a console application with a browser UI.

dbt support adds Jinja/PyYAML readers and the `dataforge.dbt` package; it requires no dbt
executable or warehouse credentials. A wheel built from the source archive must include
the tracked `.streamlit/config.toml` and `ui/dbt_sections.py`. Qualify dbt import, resource
queries and exact evidence using the [dbt fixture and boundaries](DBT_SUPPORT.md).

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
| `dist/python/dependency-overrides.txt` | Explicit tested installer compatibility policy; distribute with the wheel |
| `dist/gravetrail-VERSION-OS-ARCH.zip` | Windows executable and complete companion directory |
| `dist/gravetrail-VERSION-OS-ARCH.tar.gz` | Linux/macOS executable and companion directory |
| `dist/docker-image.json` | Local Docker image tag, content ID, OS and architecture |
| `dist/manifest.json`, `dist/SHA256SUMS` | Version/platform/build metadata, artifact sizes and SHA-256 hashes |

### Optional local API-key storage qualification — 2026-10-26

Dependency: `keyring>=25.7,<26` (locked to 25.7.0), with Windows `pywin32-ctypes==0.2.3`
and the library's `jaraco.*`/metadata dependencies. The wheel declares keyring; the frozen
build explicitly collects keyring and win32ctypes. Frozen archive inspection confirmed
`keyring.backends.Windows`, `win32ctypes.pywin32.win32cred`, its ctypes authentication
implementation and jaraco modules. The Windows executable starts its CLI successfully.

Native verification used only randomly named disposable GraveTrail-owned entries in a
temporary data-home scope: save/read, a new runtime manager, a separate Python process,
and deletion with absence confirmed. Native credential metadata reported current-user
`CRED_PERSIST_LOCAL_MACHINE` (2). Installed-wheel and frozen CLI provider-model calls also
retrieved a disposable key under an exact launch reference grant and authenticated to a
temporary loopback HTTP test server; both test entries were deleted afterward. No existing
saved credentials were read, overwritten, enumerated or deleted.

Automated lifecycle/security tests use fake native backends for locked/unavailable stores,
save/delete/database failures, scope isolation, endpoint changes, explicit source selection,
disconnect/delete, launch/MCP/background grants and absence of canaries from histories,
logs, exports, journals and backups. They do not verify OS account compromise resistance.

Final checkout acceptance: **1,288 passed, 3 skipped** (Node.js availability and Windows
symlink privileges); **60 focused provider/connection/AI/UI regressions passed**. Ruff,
whitespace, source-inventory freshness, strict MkDocs and four artifact checksums passed.
The final wheel's implementation/UI bytes match the reviewed source. No artifacts were
pushed, published or merged.

Windows persistence settings are verified by API metadata, not a reboot/domain-roaming
experiment. Real locked-vault and OS-policy failure conditions remain mocked. macOS Keychain
and Linux Secret Service are disabled pending verification of their local-only behavior.
Native-store and database updates are not one atomic transaction; crash/commit failure may
leave an orphan or missing entry, which must be cleaned or rebound explicitly. Stored keys
last until deleted, with no independent master-password lock or same-user malware protection.
See [secure configuration](SECURE_CONFIGURATION.md) for lifecycle and recovery details.

The Windows scope follows [Microsoft's credential persistence definition](https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw)
and explicitly overrides [keyring's enterprise default](https://github.com/jaraco/keyring/blob/v25.7.0/keyring/backends/Windows.py).

The Docker target builds a local image, rather than exporting an image tarball or
publishing to a registry. Its manifest hashes the image metadata document. Use the
recorded content ID to identify the local image. Executables are built for the host
OS and architecture; this is not cross-compilation. Keep the complete extracted
`gravetrail/` directory together. Never distribute just `gravetrail.exe`.

`--verify` checks every manifest entry, size, checksum and the checksum-list contents;
it rejects paths escaping the artifact directory. Checksums detect modification,
not publisher identity. Builds are versioned and dependency-locked, but binary
byte-for-byte reproducibility is not promised: timestamps, toolchain and OS differ.
Portable builds are unsigned unless explicitly processed through the Windows production signing path below. Windows installer packaging is available; production signing is not yet verified. macOS notarization and macOS/Linux installer work are not provided.

## Python installation and launches

Install a wheel in a clean virtual environment using its companion compatibility policy. Plain pip cannot resolve the temporary Streamlit/Pillow version conflict; see [installation policy](SETUP_AND_DEPLOYMENT.md#temporary-pillow-security-compatibility):

```console
uv venv .venv
uv pip install --overrides dist/python/dependency-overrides.txt dist/python/gravetrail-0.1.0-py3-none-any.whl
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
workflow. Tag versions are materialized in the build checkout. Native jobs on Windows, Linux
and macOS run the suite, build and smoke the executable, install and smoke the
wheel, verify checksums and upload Actions artifacts. A Linux job builds and checks
the container; the standalone publishing workflow skips that container job.
Running **release artifacts** directly retains the build-only behavior.

## Publish a standalone GitHub Release

Run **Actions → Publish standalone release → Run workflow** after merging the workflow.
The publish workflow builds Windows x64 only; existing direct native/archive, Python
and Docker build targets remain available. No macOS notarization or Linux packaging
was added.

Choose either:

- Enter **version** as an exact stable `X.Y.Z`, without `v`; this overrides release_type.
- Leave version empty and select **release_type**: major, minor or patch. The highest
  published stable semantic version is the base; drafts and prereleases are ignored.
  With no stable releases, the base is `0.0.0`: patch gives `0.0.1`, minor `0.1.0`,
  major `1.0.0`. For example, after `v1.4.9`, patch produces `v1.4.10`.

Exact versions must be newer than the last stable version. Existing tags are never
reused. The resolved version is materialized in each build checkout using
`uv version --no-sync`; `uv lock --check` follows. Committed pyproject/uv.lock versions
need not be edited for each release. Dependency versions remain locked. The source
tag points to the exact dispatch commit; generated distribution metadata records the
resolved release version, and the verification report records the source revision.

**dry_run** defaults to true. It accepts feature branches, builds and downloads the
final Windows installer/portable ZIP, verifies integrity and the installed payload,
repeats install/launch/upgrade/uninstall checks and generates notes. The
`verified-windows-release` Actions artifact retains the release assets and notes.
No tag or public release is created. To publish, select the default branch and
uncheck dry_run. Production signing always requires the default branch, including
validation-only runs. Publication stages a draft first and makes it public only
after asset upload succeeds. Failed drafts/tags require deliberate operator cleanup
or a new version; reruns do not overwrite them.

The publisher downloads the named `gravetrail-Windows-X64` Actions artifact into
an explicit directory. This avoids the download action's single-artifact extraction
behavior that broke the old pattern-based staging. Staging verifies the original
manifest and SHA256SUMS, version/source, installer presence, lifecycle evidence and
selected signing policy. It publishes the Windows portable ZIP, installer,
`windows-verification.json`, consolidated `manifest.json` and `SHA256SUMS`. Wheel
and source artifacts remain in the native Actions artifact.

Notes retain GitHub-generated changes, bounded commit history, exact source SHA,
trust mode and installation/upgrade guidance. Optional Copilot highlights retain the
existing bounded/no-tools configuration and fall back to ordinary notes on failure.
See [GitHub CLI release publishing](https://cli.github.com/manual/gh_release_create).

## Windows installer and signing policy

The installer uses [Inno Setup 7.1.0](https://github.com/jrsoftware/issrc/releases/tag/is-7_1_0),
pinned by upstream SHA256 in CI. Review Inno Setup's license for your organization's
use. It copies the complete PyInstaller bundle to
`%LOCALAPPDATA%\Programs\GraveTrail`, requires no elevation, offers a Start menu
shortcut and an optional desktop shortcut, and launches the existing loopback UI.
An explicit custom install directory is supported. Native Windows x64 on the hosted
Windows runner is the initial test target; x64 emulation/other architectures and old
Windows releases are not validated merely by compiler compatibility settings.

The runtime home remains `%LOCALAPPDATA%\DataForge`, or the existing
`DATAFORGE_HOME`/`--home` override. Upgrades replace program files; uninstall removes
program files and shortcuts and retains data, original evidence, settings and
exports. There is no installer option that deletes user data. Back up the home with
all UI/CLI/MCP/worker owners stopped before upgrading. A newer database migration
may prevent an older application opening it; restore a compatible backup before
rolling back. Installed processes hold a named Windows mutex; setup/uninstall ask
the user to close GraveTrail and never forcibly close live analysis.

Two modes are explicit:

- **development** (default): unsigned `gravetrail-VERSION-windows-amd64-setup-unsigned.exe`
  and an unsigned portable ZIP. This mode requires no certificate or paid service.
- **production**: `gravetrail-VERSION-windows-amd64-setup.exe`, a signed application,
  signed installer and signed uninstaller. Missing identity, key, timestamp or failed
  trust checks stop the release; no unsigned downgrade is permitted.

Production external setup (not provisioned by this change):

1. Create/protect the GitHub `windows-production` environment with required reviewers
   and default-branch-only deployment rules. Restrict the `gravetrail-signing` runner
   group to this trusted workflow; never run untrusted PR code there.
2. Provision an isolated Windows x64 runner with labels `self-hosted`, `Windows`,
   `X64`, `gravetrail-signing`, PowerShell 7 and the Windows SDK SignTool. Give its
   service account access to an organization-controlled, non-exportable publisher
   key/certificate in `Cert:\CurrentUser\My` through the organization's protected
   signing provider/HSM. A hardware-backed signing provider must support unattended
   SignTool use under that account. No PFX/password is put on command lines.
3. Set environment variables (GitHub environment **vars**) `WINDOWS_SIGNING_THUMBPRINT`
   (exact 40-digit certificate thumbprint), `WINDOWS_PUBLISHER` (intended publisher
   display name), and `WINDOWS_TIMESTAMP_URL` (trusted RFC3161 endpoint).
4. Run production validation from the default branch and retain independent publisher,
   certificate-chain and timestamp evidence before announcing trusted distribution.

`sign_windows.ps1` signs only the owned application/installer/uninstaller with
SHA256 file and timestamp digests. It verifies using SignTool `/pa /all /tw` plus
Authenticode status, exact publisher thumbprint and timestamp presence. All payload
files have SHA256 inventory records; existing third-party native signatures are
preserved and invalid signatures are rejected. Unsigned third-party binaries remain
explicitly inventoried rather than blindly re-signed. No certificates are imported
or temporary private keys created, so there is no certificate-import cleanup step.
See Microsoft's [SignTool reference](https://learn.microsoft.com/en-us/windows/desktop/seccrypto/signtool)
and [Authenticode timestamp guide](https://learn.microsoft.com/en-us/windows/win32/seccrypto/time-stamping-authenticode-signatures).
Valid signatures do not guarantee reputation/SmartScreen prompts disappear.

To package a locally built Windows bundle:

```powershell
uv run gravetrail-build --target executable --output dist/windows
./scripts/build/windows_installer.ps1 -Version 0.1.0 -SourceRevision (git rev-parse HEAD) -Output dist/windows -Compiler 'C:\path\to\ISCC.exe'
uv run python scripts/build/smoke_installer.py --directory dist/windows --finalize
uv run gravetrail-build --verify --output dist/windows
```

CI downloads the final artifact again on a separate Windows publisher job and repeats
payload/trust and installed CLI/MCP/rendered-UI checks. Lifecycle checks use isolated
paths with spaces/non-ASCII characters, retain real SQL lineage over reinstall, reject
replacement of a running UI, and compare runtime bytes before/after uninstall.
A same-version reinstall proves replacement/data preservation; a cross-version
upgrade, truly standard-user desktop account, interactive shortcut/launch experience,
clean-machine security prompts and production signing still need manual acceptance.
The guide's unsigned claims remain until actual production credentials verify the
final downloaded installer and installed application. **Packaging ready; production
signing not verified.**

The build approach follows the documented [uv Docker integration](https://docs.astral.sh/uv/guides/integration/docker/),
[PyInstaller collection flags](https://pyinstaller.org/en/stable/usage.html), and
[Hatch build-hook API](https://hatch.pypa.io/latest/plugins/build-hook/reference/).

## Windows installer acceptance — 2026-10-19

[Hosted validation run 39155104885](https://github.com/SahasilAK/GraveTrail/actions/runs/39155104885)
passed from source `8e76fd9`, resolving the first patch release to `0.0.1` while
the committed project version remained `0.1.0`. Hosted Windows passed the full suite,
native/wheel smoke, unsigned installer packaging, running-owner refusal, reinstall
lineage preservation and uninstall data/settings preservation. The separate publisher
job downloaded and verified those final bytes, repeated installed CLI/MCP/rendered UI
and lifecycle checks, and generated release notes and consolidated checksums.
The `verified-windows-release` Actions artifact contains the reviewed downloads.
This was a development validation run: no public tag/release was created. Production
signing, truly standard-user desktop testing and cross-version upgrade remain unverified.

## Previous build acceptance — 2026-10-18

The 2026-10-18 GraveTrail Windows wheel and executable passed outside-checkout SQL import,
lineage, actual stdio MCP, HTTP health and rendered UI smoke with parser 8. The branded Linux
Docker image passed non-root runtime and persistence checks on 2026-10-17. A fresh Docker
attempt on 2026-10-18 was blocked by daemon availability; it does not erase the earlier pass.

At this earlier checkpoint the source added parser 9. Rebuild and smoke wheel/native/container artifacts before
distributing those rules; older artifact results do not validate changed source. Native
Linux/macOS executable acceptance remains unrecorded here; the Windows hosted result above
supersedes this checkpoint's hosted-release gap. See [the current acceptance matrix](TESTING.md#current-acceptance-summary-2026-10-20).

## Historical verification ledger (2026-10-16)

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

When upgrading a pip installation of the previously named distribution, install the
GraveTrail wheel in a fresh virtual environment and launch it with the same explicit
`--home`. Stop the previous owner first. Keep the two distributions in separate
environments because both provide the `dataforge` Python package and legacy commands.

Existing `DATAFORGE_*` launch variables, `.dataforge/`, platform data directories,
`dataforge.duckdb`, and backup/configuration formats are retained so upgrades
reuse existing data and settings. Compose keeps its `dataforge` project name
and `dataforge-data` volume to reconnect to existing storage. Do not create
a second owner of the same home. No data migration is required.

The repository is `SahasilAK/GraveTrail`; documentation is published under
`https://sahasilak.github.io/GraveTrail/`. Clone instructions, badges and
contribution links use the renamed repository.

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

README and guide screenshots use explicit `gravetrail-*` asset filenames and show the
GraveTrail sidebar. Any old name in their source-file selectors comes from the supplied
fixture's original path, not the application branding.

## Graph image renderer and distribution proof

SVG/PNG use a shared server-side scene. Browser canvas alone would not provide
headless automation parity; a headless browser would add an executable/runtime.
`resvg-py` 0.5 supplies platform wheels and rasterizes the internally constructed
SVG without Cairo or a browser installation. No rasterizer input API accepts
uploaded SVG, URLs or arbitrary resources. Generated SVG uses fixed elements,
explicit colors, generic/local fonts and escaped text; no image links, scripts,
HTML controls or external references are emitted. PNG runs in a disposable,
timeout-bound subprocess; the frozen entry dispatches `--render-graph-image`.
The Docker runtime installs `fonts-dejavu-core` for local label rendering.
System font availability controls glyph fallback, including Unicode glyphs.
No fonts or executables are fetched during an export.

Verification recorded 2026-10-19 on Windows x64 / Python 3.11:

| Distribution | SVG | PNG | Evidence / limit |
| --- | --- | --- | --- |
| Source editable install | Passed | Passed | `uv run python scripts/build/smoke.py --python .venv/Scripts/python.exe`; subprocesses run from a disposable directory outside checkout |
| Clean wheel built from sdist | Passed | Passed | `uv run gravetrail-build --target executable --output dist/graph-images-final` installs the wheel in its clean build environment; `uv run python scripts/build/smoke.py --python dist/graph-images-final/.build/venv/Scripts/python.exe` runs outside checkout |
| Windows x64 native bundle | Passed | Passed | `uv run python scripts/build/smoke.py --executable dist/graph-images-final/.build/bundle/gravetrail/gravetrail.exe` exercises the frozen raster subprocess outside checkout |
| Linux Docker | Not run | Not run | Docker daemon unavailable on the verification host; font install and renderer dependency are configured, runtime support is unverified |
| macOS / Linux native | Not run | Not run | Require builds and smoke checks on their target hosts |

Each smoke validates standalone SVG XML and a real PNG signature/dimensions, plus
CLI lineage, stdio MCP startup and a rendered UI session. Browser checks downloaded
both formats from Explorer. Visual inspection covered fitted arrowheads, full-label
Unicode titles, cycles, a self-loop, disconnected assets, legends, warning text,
light/dark contrast and transparent output intended for a light document.
Source tests additionally cover dimension/pixel/graph/evidence/output budgets,
missing renderer, timeout/concurrency, revocation and failed artifact cleanup.
No remote provider tests or release publication were performed for this feature.
