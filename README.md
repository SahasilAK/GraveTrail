# Nothing stays buried. Every dependency leaves a trail.

<a name="gravetrail"></a>
<a name="nothing-stays-buried"></a>
<a name="every-dependency-leaves-a-trail"></a>

GraveTrail turns SQL, SAS and supported dbt project artifacts into explorable
lineage, dependencies and source evidence. Follow where data comes from, what
depends on it, and which code to investigate before making a change.

Built for data engineers, analysts, analytics engineers and architects untangling
unfamiliar pipelines, reviewing changes or planning migrations.

<a name="from-scattered-scripts-to-source-evidence"></a>

![Current GraveTrail Lineage view tracing the supplied SQL sample upstream](docs/assets/images/gravetrail-lineage-explorer.png)

*Real application, disposable workspace, repository sample data. Try the
[interactive lineage example](docs/examples/interactive-lineage.md).*

## Follow the questions

- **Where does this table come from?** Explore upstream inputs and temporary steps.
- **What could this change affect?** Follow downstream consumers before investigating them.
- **Where is the proof?** Inspect the original statement, source version and line range.
- **How is this column used?** Explore direct references and supported transformations.
- **What connects this dbt project?** Inspect models, versions, resources and macro impact.
- **How do I share my findings?** Export reports, graph images or interactive HTML.

<a name="know-the-boundaries"></a>

Lineage supports investigation and migration planning. It does not execute a
migration or guarantee arbitrary code is correct. Dynamic SQL, runtime macros,
ambiguous names and unsupported syntax can leave explicit gaps.

<a name="choose-local-analysis-or-optional-ai"></a>

## Local analysis; optional AI

Supported static analysis runs locally after installation. It needs **no AI account,
API key or paid model service**, including for large projects. Imported SQL, SAS,
Jinja and Python are inspected as text, never executed.

Optional AI independently extracts inferred lineage from selected source and authorized
context. An external provider receives that content; a localhost gateway may forward
it upstream. Installation normally downloads dependencies. Read
[local operation and disclosure](docs/concepts/local-and-ai.md) for the separate
static-analysis, HTML-export and documentation-site offline boundaries.

<a name="start-in-minutes"></a>

## Start with the documented version

This documentation describes development commit **1864dc8**, including dbt and the
current independent AI workflow. These features are **not all in release v0.0.1**.
Use the pinned source checkout to reproduce the walkthroughs.

Install Python 3.11+, Git and [uv](https://docs.astral.sh/uv/getting-started/installation/):

```sh
git clone https://github.com/SahasilAK/GraveTrail.git
cd GraveTrail
git checkout 1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414
uv sync --locked --extra dev
uv run gravetrail-ui --home ./.dataforge
```

<a name="try-a-real-project"></a>

Open [the local application](http://127.0.0.1:8501). In **Sources**, import
[`dataforge_sql_lineage_test_project.zip`](tests/sample_data/dataforge_sql_lineage_test_project.zip)
with only `sql` selected. In **Analysis → Run**, leave **Use AI for analysis** unchecked
and choose **Analyze all files**. In **Lineage**, search `pub.all_kpis`, select the exact
asset and set **Traversal options → Traversal depth** to **30**.

Follow the [first-lineage tutorial](docs/getting-started/quick-start.md) for evidence,
coverage and export steps, or the [dbt tutorial](docs/examples/dbt.md). Use the same
explicit home for UI, CLI and MCP. **Stop the UI before another process opens its DuckDB home.**

Locked uv includes the tested Streamlit/Pillow compatibility override. Wheel installs
need `dependency-overrides.txt`; read [installation choices](docs/getting-started/installation.md)
before using pip, Docker or older release binaries.

<a name="find-your-guide"></a>

## Find your trail

| Your next task | Guide |
| --- | --- |
| Install and complete an example | [Get started](docs/getting-started/index.md) |
| Import, analyze, explore and share | [User guides](docs/user-guide/index.md) |
| Understand SQL, SAS or dbt support | [Project types](docs/project-types/index.md) |
| Judge evidence and uncertainty | [Concepts](docs/concepts/index.md) |
| Configure optional AI and recovery | [AI analysis](docs/AI_ANALYSIS.md) |
| Query with scripts or agents | [CLI](docs/CLI_GUIDE.md) · [MCP](docs/MCP_INTEGRATION.md) |
| Locate code and extension points | [Developer path](docs/development/index.md) |
| Contribute or report a problem | [Contributing](CONTRIBUTING.md) · [Troubleshooting](docs/troubleshooting/help.md) |

The [documentation website](https://sahasilak.github.io/GraveTrail/) provides search
and themes; it may reflect an older revision until this branch is reviewed and
deployed. GitHub Pages serves documentation; run the app locally or on your trusted host.

## Build with us

```sh
uv run pytest -q
uv run ruff check .
uv run --group docs python scripts/docs/build.py
```

See [development setup](docs/development/getting-started.md) for focused verification.
The UI targets one trusted local user. Review [security](SECURITY.md) before remote
hosting or sharing exports, which can contain source code.

The [technology guide](docs/development/technology.md) explains Python, Streamlit,
SQLGlot, DuckDB and NetworkX. Legacy `dataforge` aliases and `DATAFORGE_*` variables
remain supported. Distributed under the [Apache License 2.0](LICENSE).
