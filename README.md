# DataForge engineering hub

A local-first Streamlit workspace for evidence-backed SQL/SAS lineage, direct column
usage and engineering investigation. Import code, build a persistent dependency model,
trace its source statements and export an interactive graph that works offline.

## Start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). From the repository root:

```powershell
uv sync --locked --extra dev
uv run streamlit run app.py
```

Open [DataForge](http://127.0.0.1:8501). The server binds to loopback. No paid service or
LLM is required. Without uv: create/activate a Python virtual environment, run
`python -m pip install -e ".[dev]"`, then `python -m streamlit run app.py`.

## First workflow

1. Open **Lineage builder**. Upload a ZIP, select a nested folder, or use **Host directory**.
2. The default allowed host root is `tests/fixtures`; its `scenario` directory contains
   real deterministic sample files. Choose SQL/SAS/CSV extensions and import.
3. Inspect the inventory, then select **Analyze all files**.
4. In **Lineage explorer**, search `mart.customer_summary` and choose the exact match.
   Expand upstream/downstream trees, collapse WORK stages, and click a graph edge for evidence.
5. Inspect direct references in **Column usage**. Download CSV/JSON/HTML reports,
   original source or an offline lineage graph.

The sample yields nine assets and seven dependencies, including a deliberate cycle and an
unresolved macro diagnostic. Results are parsed from the files; no sample graph is hardcoded.

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

## Local configuration

```powershell
$env:DATAFORGE_HOME = 'D:\DataForge\workspaces'
$env:DATAFORGE_ALLOWED_ROOTS = 'D:\Engineering\jobs;D:\Engineering\exports'
uv run streamlit run app.py
```

On Linux/macOS, separate allowed roots with `:`. Runtime defaults to `.dataforge/` and is
excluded from Git. Settings → LLM providers stores credential **environment variable names**,
never secret values. Configure an API endpoint/model or a loopback Ollama/LM Studio instance.
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
scripts/                reproducible synthetic workload benchmark
docs/                   architecture, usage, parser coverage, security and extension guides
plans/                  plan, decisions, acceptance criteria, measurements and resume status
```

Read [User guide](docs/USER_GUIDE.md), [Architecture](docs/ARCHITECTURE.md) and
[Engineering guide](docs/IMPLEMENTATION_GUIDE.md). Future agents start with `AGENTS.md`.

## Coverage boundaries

This is static dependency analysis, not database/SAS execution. Dynamic SQL, runtime macros,
stored procedures and SAS name literals beyond supported rules are diagnosed rather than
guessed. Direct SAS variable usage is conservative; it is not a full SAS language compiler.
Unknown wildcards remain unknown. WORK/session and repeated-write ordering cannot be
reconstructed without execution metadata. See [SQL](docs/SQL_PARSING.md) and
[SAS](docs/SAS_PARSING.md) coverage. Live provider verification requires an available endpoint;
the automated provider tests use protocol mocks. This local tool has no multi-user auth layer.

## Container

```sh
docker build -t dataforge .
docker run --rm -p 127.0.0.1:8501:8501 -v dataforge:/data dataforge
```

Docker execution is optional and must be verified on your Docker host. Mount allowed host
input directories read-only and configure `DATAFORGE_ALLOWED_ROOTS` inside the container.
