# GraveTrail Setup and Deployment

This is the main installation and operations reference. For recorded verification and
remaining release gates, see [build verification](BUILD_AND_RELEASE.md).

## 1. Introduction

GraveTrail engineering hub helps data engineers, analysts and architects investigate SQL,
SAS and CSV projects. Import files, generate evidence-backed table lineage, trace upstream
and downstream dependencies, inspect original statements and direct column usage, and
export results. SQL/SAS scripts are analyzed statically; imported code is never executed.

The Streamlit UI, CLI and MCP server share Python services and a local DuckDB data home.
No LLM, cloud account or paid service is needed for deterministic analysis. Optional LLM
assistance requires explicit configuration and privacy permission.

Choose a source installation for development, an installed wheel for an existing Python
environment, Docker for an isolated server runtime, or a host-specific executable bundle
when available. Build tooling creates these artifacts from the same source. This repository
does not imply that a public binary or container registry release has been published.

## 2. System requirements

| Requirement | Guidance |
| --- | --- |
| Python | `pyproject.toml` requires Python 3.11 or newer. Use the locked environment for reproducible source builds. |
| OS | Python code and build scripts target Windows, Linux and macOS. Local verification is recorded by platform in implementation status; do not infer native binary compatibility from source compatibility. |
| Tools | Git for cloning; [uv](https://docs.astral.sh/uv/) for the documented locked development/build commands. Ordinary pip supports source/wheel installation. |
| Browser | A current browser capable of running Streamlit and JavaScript graph components. |
| CPU/RAM | Begin with 2 CPU cores and 4 GB RAM for small projects as a planning allowance, not a benchmarked minimum. Increase resources for large sources, graphs or executable builds. |
| Disk | Reserve space for Python dependencies, complete imported originals, DuckDB, retained history and backups. Builds require additional temporary space. |
| Docker | A working Docker CLI and Linux container engine; Compose v2 for `docker compose`. |
| Network | Dependency/image downloads during installation. Optional providers need access to their configured endpoints; deterministic analysis and offline HTML exports need no provider connection. |

Import defaults are bounded: 10,000 files, 20 MiB per file, 200 MiB decompressed total,
100 MiB uploaded archive and compression ratio 200. Some limits are configurable within
validated bounds. Local models have their own hardware requirements.

Local smoke checks have exercised a clean Windows wheel installation outside the checkout
and the Linux Docker image, including import, lineage, UI connection, persistence and MCP.
Native executable and remote runner acceptance are tracked separately in implementation
status; this does not establish Linux/macOS native executable startup.

## 3. Quick start

For engineers starting from this repository, use the locked source environment:

```sh
git clone https://github.com/SahasilAK/dataforge-engineering-hub.git
cd dataforge-engineering-hub
uv sync --locked --extra dev
uv run gravetrail-ui
```

Open [GraveTrail](http://127.0.0.1:8501). The launcher defaults to loopback and port 8501.
Stop it with Ctrl+C. In a checkout, runtime data defaults to `.dataforge/` under the
working directory. Keep this directory out of source control.

## 4. Python installation

### Source installation with pip

Clone as above, then create a dedicated environment. Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\gravetrail-ui.exe --home D:\DataForge\data
```

Linux/macOS:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/gravetrail-ui --home "$HOME/.local/share/dataforge"
```

Using the environment's executables directly avoids activation and PowerShell execution
policy issues. pip resolves the declared version ranges; `uv sync --locked` uses the lock.

### Wheel installation

Obtain or build the wheel described in section 7 and install its actual filename:

```sh
python -m pip install /path/to/gravetrail-0.1.0-py3-none-any.whl
gravetrail-ui --home /path/to/dataforge-data
gravetrail --help
```

`0.1.0` is the current source version, not a claim of a published release. Replace it
with the version actually built. An installed wheel includes UI pages, graph assets,
Streamlit configuration and prompt resources; it runs outside the source checkout.

Launcher equivalents are `python -m dataforge.launcher` and
`gravetrail --home /path/to/dataforge-data ui`. From the checkout, direct development
startup also remains available:

```sh
uv run streamlit run app.py --server.address 127.0.0.1
```

To choose another port or suppress automatic browser opening:

```sh
gravetrail-ui --home /path/to/dataforge-data --port 8502 --no-browser
```

Install from the repository root if pip cannot locate `pyproject.toml`. If an executable
is missing from PATH, invoke it through the environment's `Scripts` or `bin` directory.
Stop the owner and back up the home before upgrading; see section 13.

## 5. Docker installation

From the repository root:

```sh
docker build -t gravetrail:local .
docker run --name gravetrail-ui --init -d -p 127.0.0.1:8501:8501 -v dataforge-data:/data gravetrail:local
docker logs -f gravetrail-ui
```

The image starts the UI on container port 8501, runs as UID/GID 10001 and stores data
at `/data`. A named volume preserves it after container removal. The published host
port is bound to loopback; do not remove that restriction for an unprotected deployment.

For Compose, choose **one owner** of the volume:

```sh
docker compose --profile ui up --build -d
docker compose logs -f ui
docker compose stop ui
```

The `ui` and `mcp` profiles use the same volume and owner container name to discourage
simultaneous ownership. For an interactive stdio MCP process after stopping/removing UI:

```sh
docker compose --profile ui down
docker compose --profile mcp run --rm --no-deps mcp
```

Do not add `-v` to `docker compose down` when retaining data. A containerized stdio
agent integration should use an attached `docker run --rm -i ... gravetrail mcp`, with
the same volume and no other owner. See [MCP integration](MCP_INTEGRATION.md).

Inject provider credentials at runtime from the launching environment; never put values
in Dockerfiles, image build arguments or committed Compose files. For example, with
`DATAFORGE_OPENAI_API_KEY` already supplied by your secret manager:

```sh
docker run --name gravetrail-ui --init -d -p 127.0.0.1:8501:8501 -v dataforge-data:/data -e DATAFORGE_OPENAI_API_KEY gravetrail:local
```

Only supply credentials required by that container. Environment values are visible to
administrators who can inspect the container. A local model's `localhost` inside a container
refers to the container itself; configure a reachable endpoint and the privacy gate.

For host imports, mount a directory read-only and allow its **container** path:

```sh
docker run --name gravetrail-ui --init -d -p 127.0.0.1:8501:8501 -v dataforge-data:/data -v /absolute/jobs:/imports:ro -e DATAFORGE_ALLOWED_ROOTS=/imports gravetrail:local
```

Bind-mounted data directories must be writable by UID 10001; fix permissions on the
dedicated data directory or use a named volume. Do not grant broad host permissions.
To stop/remove a plain container, use `docker stop gravetrail-ui` then
`docker rm gravetrail-ui`. Rebuild and start a replacement using the same volume to update.

## 6. Standalone executable installation

Obtain a bundle built from a trusted revision for your OS and architecture, or create it
with section 7. A locally built Windows artifact is named like
`gravetrail-0.1.0-windows-amd64.zip`; other hosts produce their own platform archive.
Compare the archive SHA-256 with `SHA256SUMS` from the same trusted build. Checksums
detect modification but do not authenticate an untrusted publisher.

Extract the **entire** archive, keeping its `gravetrail` directory and internal dependencies
together. On Windows:

```powershell
.\gravetrail\gravetrail.exe --home D:\DataForge\data --port 8501
.\gravetrail\gravetrail.exe --cli --home D:\DataForge\data --json workspace list
```

Stop the UI before running a CLI or MCP process against the same home. `--cli` routes to
the regular CLI, including `mcp`; without it the binary launches the UI. On Linux/macOS,
the equivalent executable is `./gravetrail/gravetrail`. Build on the target platform;
Windows executables do not run natively on Linux/macOS. Native Linux/macOS bundle startup
requires its own runner verification and is not established by the Windows build.

User data is outside the extracted program directory; see section 11. Stop the old binary,
back up the home, extract the new bundle separately and launch with the same `--home`.
No system-wide installer or automatic updater is provided. If startup fails, run from a
terminal to capture errors, check extraction completeness, port availability and OS security
controls. Unsigned builds may trigger platform warnings; code signing/notarization is not
claimed. Do not move only the executable or disable system protections to hide a failure.

## 7. Building from source

Use a clean checkout, Python 3.11 and uv. Docker builds additionally require an available
Linux Docker engine; executable builds install the locked PyInstaller build extra in an
isolated build environment. From the repository root:

```sh
uv sync --locked --extra dev --extra build
uv run gravetrail-build --target python
uv run gravetrail-build --target docker
uv run gravetrail-build --target executable
uv run gravetrail-build --verify
```

`--target all` runs every target; `--root PATH` chooses the source root and `--output PATH`
chooses the artifact directory (default `dist`). Targets produce:

| Target | Output |
| --- | --- |
| `python` | Wheel and source archive under `dist/python/` |
| `docker` | Local `gravetrail:VERSION` image plus `dist/docker-image.json` identifying it |
| `executable` | Host OS/architecture archive containing a PyInstaller directory bundle, plus wheel |
| All builds | `dist/manifest.json` and `dist/SHA256SUMS` with version, platform and artifact hashes |

Docker image metadata is not an exported image tarball. `--verify` checks the recorded
files and hashes; it is not a runtime smoke test or reproducible-byte guarantee. Install
the wheel in a clean environment, launch its UI outside the checkout, and launch the
actual extracted executable against an isolated home. Verify health and real workflows.
For Docker, verify startup, persisted data after restart, and input-volume boundaries.
Build subprocesses receive an allowlisted environment; source/package/image definitions
exclude runtime databases and common secret files. Inspect artifacts before distribution.

Version comes from `pyproject.toml`. Keep `uv.lock` consistent when changing dependencies.
The [release workflow](https://github.com/SahasilAK/dataforge-engineering-hub/blob/main/.github/workflows/release.yml) supports matching `vVERSION` tags
and manual dispatch, builds native artifacts on Windows/Linux/macOS runners, smoke-tests
them, and uploads workflow artifacts. Its container job builds/tests the image and uploads
metadata. It does not publish a GitHub Release or push an image. Observed remote execution
status is recorded in implementation status; a workflow definition is not a verified run.
The local build commands do not upload artifacts.
See [build and release](BUILD_AND_RELEASE.md) for reusable smoke scripts and CI details.

## 8. Initial application setup

1. Create or select a workspace in the sidebar. Give it a recognizable name.
2. Open **Lineage builder**. Upload a ZIP, choose browser folder files, or select an
   accessible **Host directory** under a startup-allowed root.
3. Select `.sql`, `.sas` and/or `.csv`. Only selected extensions are imported for analysis.
4. Inspect accepted/skipped files, encoding diagnostics and original content.
5. Choose **Analyze all files** to persist the dependency model.
6. In **Lineage explorer**, search a table, choose its exact asset identity and inspect
   upstream/downstream trees, graph paths and relationship evidence.
7. Open **Column usage** for direct references. Unknown wildcards and dynamic names remain
   unresolved; direct references do not imply full transitive column transformation lineage.

For supplied SQL/SAS projects, import either ZIP in `tests/sample_data/`, select only its
script extension and search `pub.all_kpis` after analysis. Fixture expectations, parser
limits and acceptance details are in [testing guide](TESTING.md)
and [agent workflows](AGENT_WORKFLOWS.md).

Host access is configured before startup. PowerShell example:

```powershell
$env:DATAFORGE_HOME = 'D:\DataForge\data'
$env:DATAFORGE_ALLOWED_ROOTS = 'D:\Engineering\jobs;D:\Engineering\exports'
$env:DATAFORGE_STORAGE_LOCATIONS = 'D:\DataForge\archive;D:\DataForge\sandbox'
uv run gravetrail-ui
```

These non-secret settings apply to the launching process. Linux/macOS use `:` between
paths, for example `export DATAFORGE_ALLOWED_ROOTS=/srv/jobs:/srv/exports`.
The UI can switch among startup-allowed storage locations (at most eight including the
primary home); switching does not copy or merge workspaces. Additional locations must
be absolute paths. Installed builds do not rely on repository test fixtures being present.

## 9. LLM connection configuration

Open **Settings → LLM providers**, choose a provider and save a profile with a non-secret
endpoint, available model/deployment identifier and credential **variable name**. Profiles
persist validated non-secret preferences, not credential values. URLs with embedded
credentials or authentication query parameters are rejected.

| Provider | Default credential reference |
| --- | --- |
| OpenAI | `DATAFORGE_OPENAI_API_KEY` |
| Anthropic | `DATAFORGE_ANTHROPIC_API_KEY` |
| Ollama | `DATAFORGE_OLLAMA_API_KEY` |
| LM Studio | `DATAFORGE_LM_STUDIO_API_KEY` |
| OmniRoute | `DATAFORGE_OMNIROUTE_API_KEY` |
| Databricks Model Serving | `DATAFORGE_DATABRICKS_TOKEN` |
| Azure OpenAI | `DATAFORGE_AZURE_OPENAI_API_KEY` |
| Gemini | `DATAFORGE_GEMINI_API_KEY` |
| OpenRouter | `DATAFORGE_OPENROUTER_API_KEY` |
| OpenAI compatible | `DATAFORGE_CUSTOM_API_KEY` |

For a saved profile, enter the value in the masked **Runtime credential** field and choose
**Connect for this session**. It stays in that browser session's runtime manager and is
passed directly to adapters. **Clear runtime credentials** removes these in-memory values.
The application does not save entered keys to DuckDB, files, exports or the OS environment.
Re-enter them after a fresh session/restart unless supplied by the launch environment.
Clearing session values cannot erase a credential inherited from that environment.

Alternatively, provision the named variable through the launcher/service secret manager.
Startup variables are read-only. Existing profiles that explicitly name legacy variables
remain compatible; the app does not overwrite unrelated `OPENAI_API_KEY` or similar values.
Never put a key in command arguments, committed configuration, `.env` files or build inputs.
Privileged local processes may inspect process memory/environment; session isolation is
not an OS security boundary or a guarantee of forensic memory erasure.

Use **Discover models** and **Test model connection** explicitly. Enable remote requests
under **Security and privacy** before using a non-loopback endpoint. Full-source remote
transmission has a separate permission. Local Ollama/LM Studio endpoints may need no key.
Network-mounted or container-host model endpoints may be classified as remote.

For this repository's OmniRoute verification, use endpoint `http://localhost:20128/v1`,
model `auto/best-reasoning` and the existing `OMNIROUTE_API_KEY` reference. Do not substitute a fixed route.
Gateway availability remains an external verification condition. See
[LLM integration](LLM_INTEGRATION.md) for task routing and grounding behavior and
[secure configuration](SECURE_CONFIGURATION.md) for credential lifecycle details.

## 10. CLI and MCP setup

Python installation provides `gravetrail`. Global options precede subcommands:

```sh
gravetrail --home /path/to/data --json workspace list
gravetrail --home /path/to/data --allow-write --json workspace create ecommerce
gravetrail --home /path/to/data --json assets search --query pub.all_kpis --workspace WORKSPACE_ID
gravetrail --home /path/to/data --json --max-depth 30 lineage upstream ASSET_ID --workspace WORKSPACE_ID
```

Replace uppercase placeholders with returned IDs; workspace names are not IDs. Command
groups cover workspace, ingest, lineage, assets, columns, source, impact, batch, jobs,
export, cleanup and maintenance. `gravetrail --help` and each group's `--help` are authoritative.
Writes require startup `--allow-write` and workspace permission; host imports also require
allowed roots. Normal analysis queries never invoke an LLM.

Start local read-only stdio MCP in the installed environment:

```sh
gravetrail --home /path/to/data --allowed-workspace WORKSPACE_ID mcp
```

For Codex, configure a local process using actual absolute paths:

```toml
[mcp_servers.gravetrail]
command = "D:/DataForge/.venv/Scripts/python.exe"
args = ["-m", "dataforge.cli", "--home", "D:/DataForge/data", "--allowed-workspace", "WORKSPACE_ID", "mcp"]
```

Settings → **Agent & Automation Access** provides configurations for the selected home
and policy. Stdio uses local process permissions. Network MCP additionally requires a
named runtime bearer credential, explicit workspace scope and a TLS reverse proxy for
external binding; it has no built-in OAuth/login flow. See the complete
[CLI guide](CLI_GUIDE.md) and [MCP integration](MCP_INTEGRATION.md).

For efficient investigation, resolve asset IDs, request compact lineage, honor freshness,
`complete`, boundaries and cursors, then fetch only relevant evidence lines. MCP
`inspect_cleanup` and `preview_cleanup` are read-only; no destructive MCP tool is exposed.

**DuckDB has one owning process per data home.** Stop UI before independent CLI/MCP access,
or use a separate home. A single MCP process shares its Store and jobs internally.

## 11. Data storage and backup

| Launch method | Default data home when `DATAFORGE_HOME`/`--home` is absent |
| --- | --- |
| Source launcher or CLI | `.dataforge/` in the current working directory |
| Installed/frozen UI, CLI and MCP on Windows | `%LOCALAPPDATA%\DataForge` |
| Installed/frozen UI, CLI and MCP on macOS | `~/Library/Application Support/DataForge` |
| Installed/frozen UI, CLI and MCP on Linux | `$XDG_DATA_HOME/dataforge`, otherwise `~/.local/share/dataforge` |
| Docker | `/data`, backed by the configured volume |

The UI, CLI and MCP share the same default-home resolver. Pass `--home` explicitly
when selecting another installation's data. `gravetrail --home PATH ui` uses that explicit
home. The packaged UI copies default theme configuration once into the home and
preserves subsequent edits.

`dataforge.duckdb` contains workspace metadata, settings, inventory, current analysis,
retained history and AI records. `blobs/<sha256>` stores complete immutable original bytes
shared across workspaces. `history-recovery/` contains recovery archives/staging;
`agent/` holds job journals, scoped exports, audit and revocation metadata. `backups/`
holds maintenance archives. Parser cache is shared within the database.

Use the UI database maintenance controls, or stop other owners and run:

```sh
gravetrail --home /path/to/data --json maintenance inspect
gravetrail --home /path/to/data --allow-write --json maintenance backup
gravetrail --allow-write maintenance restore /path/to/backup.zip /path/to/NEW-data --confirm "RESTORE GRAVETRAIL"
```

Backup creates a checkpointed database snapshot and managed runtime files with a manifest
and SHA-256 per file. Existing backups and unrelated files are excluded; protect any
additional files separately. The built-in archive is limited to 512 MiB and 50,000 files;
use a full offline filesystem backup for larger homes. Keep application version/lock
information alongside backups. A restore validates bounds, paths, hashes and schema into
staging, then publishes to a **new, nonexistent directory**. It never overwrites a live
home. The UI selects an archive from the current home's `backups/` and restores into a
generated sibling directory. Validate it before launching with `--home` pointing to it;
restart with the new storage allowlist if selecting it through UI storage controls.

For a complete filesystem backup, stop all owners and copy the entire home using your
normal backup tool. Never copy a database while another process owns it. Backups include
source and retained AI content; they are sensitive and are not encrypted by GraveTrail.

## 12. Cleanup and maintenance

Open **Settings → Data Management & Cleanup**. Choose scope/category, inspect real record
counts and file sizes, create a dry-run preview and type the displayed confirmation.
Workspace operations require its exact name; shared cleanup uses `CLEAN SHARED DATA`;
full application reset uses `RESET GRAVETRAIL`. A changed preview is rejected and must be
refreshed. Active analysis, managed jobs and AI requests block unsafe operations.

| Category | Effect |
| --- | --- |
| Sources | Selected/all inventory; invalidates all workspace graph, analysis and AI records to prevent dangling evidence. Reimport missing sources and rebuild. |
| Lineage | Graph, statements, operations, columns, diagnostics and analysis runs; imported originals/configuration remain. |
| Columns | Direct column usage only; force a rebuild when regenerating it. |
| AI | AI records and the complete dependent graph/history; rebuild deterministic lineage afterwards. |
| History | Eligible terminal, unreferenced analysis/import history; may select an unreferenced analysis run. |
| Jobs | Terminal/stale job journals for the workspace. |
| Shared cache | Global parser cache; affects future analysis performance in every workspace. |
| Workspace reset | Generated analysis/AI/history and associated outputs; retains imported inventory and configuration. |
| Workspace deletion | Workspace rows/configuration/inventory and its managed outputs. |
| Orphan blobs | Shared unreferenced originals; retained history/snapshots protect references. Recovery archives conservatively prevent blob collection. |
| Application reset | All known application runtime rows and managed files; preserves code, documentation, backups and unrecognized files. |

Source-derived copies can remain in shared parser cache or retained blobs after inventory
deletion. Preview shared cache/orphan cleanup separately. Repository `KNOWLEDGE.md`,
`AGENTS.md`, README and prompts are maintained documentation and are never cleanup targets.
There is no separate embedding index or generated knowledge directory to clear.

CLI cleanup defaults to dry-run. Save its preview to a **new** file, review it, then apply:

```sh
gravetrail --home /path/to/data --json cleanup inspect --workspace WORKSPACE_ID
gravetrail --home /path/to/data --json --output lineage-preview.json cleanup lineage --workspace WORKSPACE_ID --dry-run
gravetrail --home /path/to/data --allow-write --json cleanup lineage --workspace WORKSPACE_ID --no-dry-run --preview lineage-preview.json --confirm "Workspace name" --backup
gravetrail --home /path/to/data --json workspace reset --workspace WORKSPACE_ID --dry-run
```

`cleanup sources` supports repeatable `--file-id`; `cleanup history` supports `--run-id`.
CLI workspace categories are sources, lineage, columns, ai, history, jobs, reset and
workspace; shared cache/orphans/application reset are UI operations. Apply requires
`--allow-write` plus workspace policy and the saved preview. A successful whole-home backup is mandatory (the default `--backup`); `--no-backup`
is refused. This also requires whole-home authorization.

The separate recoverable history/temporary cleanup controls archive eligible old records
and stale application-created staging files before deletion. Their recovery journals are
bounded; this is not an undo facility for general category cleanup. Automatic expired
temporary cleanup, when enabled, runs when opening cleanup settings rather than as an OS
scheduler. It only targets app-created recovery staging files older than 24 hours, up to
100 files and 25 MiB per visit, retaining recoverable database bytes. Review the scope
before enabling.

Database maintenance supports integrity/schema/reference inspection and a checkpoint:

```sh
gravetrail --home /path/to/data --allow-write maintenance checkpoint
```

Checkpoint flushes DuckDB's WAL; neither it nor logical row deletion guarantees a smaller
database file. Displayed logical JSON row estimates are not physically reclaimable bytes.
Rebuild lineage through Lineage builder or `lineage build --force` after a derived-data
reset. Without a backup, source/workspace/application deletion may be irreversible. See
[data management](DATA_MANAGEMENT.md) for detailed category dependencies and recovery limits.

## 13. Updating the application

Stop every owner, back up the home and record the old version before upgrading.

- **uv checkout:** review your working tree, update to the intended revision, then run
  `uv sync --locked --extra dev` and launch with the same explicit home.
- **pip source/wheel:** install the intended revision/wheel with the environment's pip,
  then launch from that environment with the same home.
- **Docker:** stop/remove the old container, rebuild the intended image and recreate the
  container with the same named volume. Do not remove the volume.
- **Executable:** extract the new bundle separately and launch it with the existing home.

Store applies versioned transactional schema migrations when opening a home. Existing
data is preserved by migration code; keep a complete backup for failure recovery and
validate workspace counts, inventory and representative evidence after an upgrade.
Downgrades are not automatically reversible. Restore the pre-upgrade backup to a new
home and use its matching code if rollback is needed. Do not manually edit migration rows.

## 14. Troubleshooting

| Symptom | Action |
| --- | --- |
| Dependency/install failure | Confirm Python 3.11+, correct environment and repository root; retry the locked uv installation. Check download/proxy access without exposing credentials. |
| UI command missing | Use the environment's executable path or `python -m dataforge.launcher`. Reinstall the current package. |
| Port already in use | Stop the intended previous process or use `gravetrail-ui --port 8502`. Do not terminate unrelated processes. |
| UI starts but browser does not open | Open the loopback URL manually; inspect terminal output and health endpoint `/_stcore/health`. |
| `storage_busy` / DuckDB lock | Stop the UI, MCP or worker owning that exact home, or choose a separate home. Do not delete lock/WAL files to bypass ownership. |
| Docker daemon unavailable | Start a supported Linux engine and check `docker info`. A CLI installation alone is insufficient. |
| Docker permission denied | Ensure dedicated `/data` mount permits UID 10001; prefer a named volume. Input mounts should be read-only and allowed inside the container. |
| Executable fails | Extract all bundled files, run from a terminal, check matching OS/architecture and review quarantine/antivirus findings. |
| Encoding/binary diagnostic | Inspect the original file; convert an intentional copy to a supported text encoding and reimport. GraveTrail reports undecodable/binary content rather than silently changing evidence. |
| Missing runtime credential | Re-enter the masked session credential or provision the exact variable referenced by the profile before restarting. Clearing session credentials leaves launch variables available. |
| LLM test fails | Check endpoint/model/auth method, provider availability, network and privacy settings. A local gateway may require a credential and may forward data remotely. |
| Cleanup preview expired | Refresh after data/settings/jobs change; inspect the new scope before confirming. |
| Migration/integrity failure | Stop the owner, preserve the failed home and logs, restore a known compatible backup to a new home. Never drop tables or delete the database as a repair shortcut. |

See [troubleshooting](TROUBLESHOOTING.md), [security](SECURITY.md) and implementation status
for observed limitations. Sanitize source, paths and credentials before sharing diagnostics.

## 15. Security and privacy

The app is a local, single-user tool without a multi-user authentication layer. Keep UI
bound to loopback. An administrator deploying a shared service must supply appropriate
authentication, TLS, access control and process/data isolation. Session-scoped provider
keys prevent accidental runtime sharing; they do not make an untrusted shared host safe.

Imports never execute SQL/SAS or embedded instructions. Path validation, allowed roots,
resource budgets and parameterized storage SQL protect ingestion boundaries. Source
originals deliberately retain complete content and may themselves contain secrets.
Protect homes, exports and backups using OS permissions and encryption where required.

Entered credentials remain in memory; launch variables remain read-only. Profiles allow
non-secret preferences only. Redaction is best effort; never deliberately import secrets
or send them to providers. External LLM requests require privacy gates and explicit user
action; opening an assistance panel does not send code. Retained AI bodies are opt-in.
Loopback gateways may route remotely, so understand their recipient policy.

For network MCP, follow bearer credential, scope and TLS-proxy requirements in the
[MCP guide](MCP_INTEGRATION.md). Do not expose plaintext backends. Docker uses a non-root
runtime; mount only necessary data and imports, and inject secrets at runtime. Anyone
with Docker administrative privileges or data-home filesystem access remains trusted.

## 16. Development and contribution

Read the [contribution guide](development/contributing.md),
[build verification](BUILD_AND_RELEASE.md) and [implementation guide](IMPLEMENTATION_GUIDE.md)
before changing behavior. Agent instructions, product specifications and implementation
records may also be supplied as ignored local working files.

| Path | Responsibility |
| --- | --- |
| `src/dataforge/` | Domain models, storage, ingestion, parsers, graphs, exports, LLM, cleanup and agent services |
| `ui/`, `app.py` | Presentation, session controls and entry point |
| `prompts/` | Versioned grounded-assistance templates and schemas |
| `tests/` | Unit/integration/UI tests, fixtures and supplied SQL/SAS projects |
| `scripts/`, `.github/workflows/` | Verification, build entry scripts and automation |
| `docs/` | Operating guides, design and verification guidance |

```sh
uv sync --locked --extra dev
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run streamlit run app.py --server.address 127.0.0.1
```

Ruff lint is the required repository check. Review formatting differences before applying
formatting; a formatting check is not a claim that historical files all use Ruff formatting.
Verify real UI workflows as well as AppTest; browser graph behavior needs a real browser.

New parsers return `ParseResult` operations/diagnostics; analysis services own persistence
and cross-file resolution. Preserve file, exact statement, line range and method for each
relationship. Prefer an unresolved diagnostic to guessed identities. Increment parser
version when extraction semantics change. New providers extend the existing adapter,
runtime credential mapping, validation and protocol tests; honor privacy before network I/O.
See [extension guide](EXTENDING_THE_APP.md). Test cleanup with isolated homes, preserve
unrelated edits, update knowledge/status and commit tested coherent feature groups.

For a release, update version/lock, run tests/lint, build with section 7, smoke-test the
actual distribution artifacts, review secret/data exclusions and record platform limits.
Keep release publication a deliberate maintainer operation.

## 17. Frequently asked questions

**Can I work without an API key or internet?** Yes. Installed deterministic analysis,
lineage exploration and offline HTML exports need no provider. Installation/downloads and
optional remote assistance need network access.

**Does GraveTrail execute my scripts?** No. It performs static analysis. Dynamic SQL,
runtime SAS macros and execution-order-dependent behavior may remain unresolved.

**Can the UI and MCP open one home simultaneously?** Use one owning process per home.
Stop one before starting another, or assign separate homes. Separate homes do not synchronize.

**Why did clearing sources leave disk data?** Original blobs and parser cache are shared;
retained evidence/history can reference old originals. Review shared cache/orphan cleanup.
Database logical deletion also does not guarantee physical file shrinkage.

**Can I undo cleanup?** General cleanup requires a backup for recovery. Specialized
recoverable history/staging cleanup has its own bounded journals. Restore whole-home
backups into a new directory and validate before switching.

**Are API keys saved when I save a profile?** No. A profile stores a variable name and
validated non-secret settings. Entered keys remain in session memory; startup environment
credentials remain available until the launching environment/process is changed.

**Where is my data after replacing an executable?** In the per-user home or explicit
`--home`, independently of the extracted bundle. Always pass the same home when updating.

**Can I build every platform on Windows?** Executables are host-platform builds. Use
appropriate Windows/Linux/macOS runners and test each native artifact before distribution.

**What is the license?** The repository includes the [Apache License 2.0](https://github.com/SahasilAK/dataforge-engineering-hub/blob/main/LICENSE).
Review dependency licenses when redistributing a bundled application.

## CLI and MCP UI coverage

The [46-ID capability matrix](CLI_MCP_CAPABILITIES.md) lists all permitted shared operations and local-only restrictions. New launch grants are independent: configuration, outbound AI with exact origins/credential references, and unrestricted application settings. Use `gravetrail capabilities` and subgroup `--help` to inspect the installed version. Local `--allow-admin` cannot launch MCP. Existing packaged artifacts must be rebuilt to include these new routes; source verification commands are in the [testing guide](TESTING.md).

See [GraveTrail rebrand compatibility](BUILD_AND_RELEASE.md#gravetrail-rebrand-compatibility) before upgrading an existing installation.
