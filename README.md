# DataForge engineering hub

A local-first Streamlit workspace for evidence-backed SQL/SAS lineage, direct column
usage and engineering investigation. Import code, build a persistent dependency model,
trace its source statements and export an interactive graph that works offline.

## Installation & Setup

Read the [Complete Setup & Deployment Guide](docs/SETUP_AND_DEPLOYMENT.md) for Python,
Docker, standalone executables, runtime credentials, backups, cleanup and troubleshooting.

| Method | Use |
| --- | --- |
| Source + uv | Recommended for engineers working with this repository |
| Python wheel | Install the packaged UI, CLI and MCP in a Python environment |
| Docker | Run with a persistent volume and restricted host port |
| Standalone bundle | Build a native directory bundle for the target OS; availability and verification vary by platform |

### Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). From the repository root:

```powershell
uv sync --locked --extra dev
uv run dataforge-ui
```

Open [DataForge](http://127.0.0.1:8501). The server binds to loopback. No paid service or
LLM is required. Without uv: create/activate a Python virtual environment, run
`python -m pip install -e ".[dev]"`, then `dataforge-ui`.
Use `dataforge-ui --home PATH --port 8502` to choose storage/port. Installed and frozen
UI builds default to a per-user data directory; the source launcher defaults to `.dataforge/`.
Pass the same explicit `--home` to UI, CLI and MCP when working with one data home.

## First workflow

1. Open **Lineage builder**. Upload a ZIP, select a nested folder, or use **Host directory**.
2. The default allowed host root is `tests/fixtures`; its `scenario` directory contains
   real deterministic sample files when running from a checkout. Choose SQL/SAS/CSV extensions and import.
3. Inspect the inventory, then select **Analyze all files**.
4. In **Lineage explorer**, search `mart.customer_summary` and choose the exact match.
   Expand upstream/downstream trees, collapse WORK stages, and click a graph edge for evidence.
5. Inspect direct references in **Column usage**. Download CSV/JSON/HTML reports,
   original source or an offline lineage graph.

The sample yields nine assets and seven dependencies, including a deliberate cycle and an
unresolved macro diagnostic. Results are parsed from the files; no sample graph is hardcoded.
For larger acceptance projects, use the SQL/SAS ZIPs in `tests/sample_data/`, choose only
their script extension and trace `pub.all_kpis`; see [fixture expectations and limits](tests/sample_data/KNOWLEDGE.md).

## Agent and automation access

The human-first UI now includes **Settings → Agent & Automation Access** with
workspace permissions, response limits, local connection testing and copyable
Codex/Claude Code configurations. Use `uv run dataforge --help` for the standalone
CLI or `uv run dataforge --home ./automation-data mcp` for local MCP stdio.
Both reuse the same deterministic stored analysis and default to compact summaries
and read-only access. Imports/builds require explicit `--allow-write` and imports
also require allowed roots. Authenticated Streamable HTTP is available for private
clients; externally bound services require a TLS reverse proxy.

Read [CLI guide](docs/CLI_GUIDE.md), [MCP setup](docs/MCP_INTEGRATION.md),
[agent workflows](docs/AGENT_WORKFLOWS.md) and [token measurements](docs/TOKEN_OPTIMIZATION.md).
DuckDB allows one owning process per runtime home; stop another owner or use a
separate home. The supplied SQL/SAS ZIPs in `tests/sample_data` are described in the
workflow guide. Both now match all 128 expected logical dependencies, including SAS
PROC SQL `FORMAT=` expressions and temporary WORK collapsing.

## Features

- Isolated persistent workspaces, import history, complete source inventory and original bytes.
- Safe ZIP/folder/allowed-root imports with hashing, encoding diagnostics and resource budgets.
- SQL AST operations, CTEs/subqueries, scoped aliases and direct columns; dedicated SAS DATA,
  PROC SQL and common procedure rules; streaming CSV metadata.
- Incremental parser cache, atomic analysis replacement, run comparisons and versioned evidence.
- Bounded upstream/downstream graphs and trees, cycles, temporary contraction with provenance.
- Code search, data dictionary, impact reports and standalone interactive HTML graph export.
- Optional provider profiles, model discovery/task routing, privacy gates and grounded AI
  validation. Unsupported or invented claims are quarantined; merged claims remain inferred.
- Native light/dark themes, source search, line ranges, copy and exact original downloads.
- Previewed source/lineage/AI/history cleanup, workspace reset/deletion, shared cache/blob
  maintenance, integrity checks and backups with restore into a new data home.
- Session-only masked provider credentials, packaged UI/CLI/MCP launchers and a common
  Python/Docker/native build interface with artifact manifests and checksums.

Supported input formats are **SQL (`.sql`), SAS (`.sas`) and CSV (`.csv`)**. ZIP archives
and browser folders preserve nested paths. CSV supplies source metadata, not executable code.

## Local configuration

```powershell
$env:DATAFORGE_HOME = 'D:\DataForge\workspaces'
$env:DATAFORGE_ALLOWED_ROOTS = 'D:\Engineering\jobs;D:\Engineering\exports'
$env:DATAFORGE_STORAGE_LOCATIONS = 'D:\DataForge\archive;D:\DataForge\sandbox'
uv run dataforge-ui
```

Settings → Storage and workspaces can open one of the startup-allowed storage locations
for the current browser session. This preserves each directory independently. At most eight
locations including DATAFORGE_HOME are accepted; additional locations must be absolute paths.
On Linux/macOS, separate allowed roots and storage locations with `:`. Runtime defaults to `.dataforge/` and is
excluded from Git. Settings → LLM providers stores credential **environment variable names**,
never secret values. Enter masked session-only credentials or supply the named startup
variable. New references default to `DATAFORGE_*`; existing explicitly named variables
remain read-only. Clearing runtime credentials removes session entries; startup environment
values remain available. Configure an API endpoint/model or a loopback Ollama/LM Studio instance.
Remote requests are disabled by default. See [LLM configuration](docs/LLM_INTEGRATION.md).

## Verify

```powershell
uv run pytest -q
uv run ruff check .
uv run python scripts/benchmark.py --files 500 --output plans/BENCHMARK_RESULTS.json
```

Tests cover secure import, persistence, parser accuracy, graph/column scopes, UI workflows,
offline exports, AI protocols, malicious output, rollback and changed/concurrent imports.
See [test coverage](docs/TESTING.md), [recorded performance](docs/PERFORMANCE.md) and
[implementation status](plans/IMPLEMENTATION_STATUS.md).

## Structure

```text
app.py                  Streamlit entry point
src/dataforge/          domain, storage, ingestion, parsers, services, graph, exports, LLM
ui/                     shared components and feature pages
prompts/                versioned task prompts, examples and JSON schema
tests/                  unit/integration/AppTest tests and deterministic scenario files
scripts/                workload/provider/agent verification and distribution smoke tools
docs/                   architecture, usage, parser coverage, security and extension guides
plans/                  plan, decisions, acceptance criteria, measurements and resume status
```

Read [User guide](docs/USER_GUIDE.md), [Architecture](docs/ARCHITECTURE.md) and
[Engineering guide](docs/IMPLEMENTATION_GUIDE.md). Future agents start with `AGENTS.md`.

## Coverage boundaries

This is static dependency analysis, not database/SAS execution. Dynamic SQL, runtime macros,
stored procedures and SAS name literals beyond supported rules are diagnosed rather than
guessed. Direct SAS variable usage is conservative; it is not a full SAS language compiler.
Unknown wildcards remain unknown. Supplied job/session IDs separate temporary assets through Settings; runtime session discovery
and repeated-write ordering require execution metadata. See [SQL](docs/SQL_PARSING.md) and
[SAS](docs/SAS_PARSING.md) coverage. Live provider verification requires an available endpoint;
the automated provider tests use protocol mocks. This local tool has no multi-user auth layer.

## Container

```sh
docker build -t dataforge:local .
docker run --rm -p 127.0.0.1:8501:8501 -v dataforge-data:/data dataforge:local
```

Docker execution is optional and must be verified on your Docker host. Mount allowed host
input directories read-only and configure `DATAFORGE_ALLOWED_ROOTS` inside the container.

## Security and privacy

Imported code is never executed. Host imports require allowed roots; archives and query
responses have resource bounds. The UI is intended for one trusted local user and binds
to loopback. It has no multi-user authentication layer. Remote LLM requests require explicit
privacy permission; source originals, exports and backups may contain sensitive information.
Protect the data home and inject credentials at runtime. See [security](docs/SECURITY.md).

Cleanup always starts with a preview. Shared cache/orphan cleanup affects the home;
workspace deletion affects its selected workspace. Back up before destructive cleanup or
upgrades. Logical row deletion/checkpointing does not promise physical disk shrinkage.

## Documentation and contribution

- [Setup and deployment](docs/SETUP_AND_DEPLOYMENT.md): installation, builds, credentials, operations and recovery.
- [User guide](docs/USER_GUIDE.md): UI workflow and evidence inspection.
- [CLI guide](docs/CLI_GUIDE.md) and [MCP integration](docs/MCP_INTEGRATION.md): agent access, policy and examples.
- [Architecture](docs/ARCHITECTURE.md) and [implementation guide](docs/IMPLEMENTATION_GUIDE.md): module boundaries and development.
- [Testing](docs/TESTING.md) and [implementation status](plans/IMPLEMENTATION_STATUS.md): evidence and remaining gates.

Contributors should read [AGENTS.md](AGENTS.md), preserve evidence and unresolved diagnostics,
run pytest/Ruff plus the affected running UI workflows, and update status/knowledge with
each tested coherent feature group. Keep runtime data and credentials out of commits.

## License

DataForge is distributed under the [Apache License 2.0](LICENSE). Bundled dependencies
have their own licenses; review them when redistributing an executable or container.
