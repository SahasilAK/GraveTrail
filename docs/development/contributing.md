# Contributing

Contributions should improve a concrete user workflow while preserving evidence,
conservative analysis and local data safety. Use an issue to describe a reproducible bug
or a focused feature proposal. Check existing issues first, and omit credentials and
private source from examples. Follow the repository's
[security reporting guidance](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/SECURITY.md)
for vulnerabilities.

## Set up a checkout

```sh
git clone https://github.com/SahasilAK/GraveTrail.git
cd GraveTrail
git switch chore/documentation-overhaul
uv sync --locked --extra dev
git switch -c feature/describe-the-change
```

The documentation branch contains this overhaul and current implementation. Fetch it
from the reviewed remote when available; before publication, use the local review
branch. For application-only reproduction use the pinned commit in
[installation](../getting-started/installation.md). Do not assume older main/release
checkouts contain the inventory tooling.

Use Python 3.11 or newer. Follow the [newcomer workflow](getting-started.md) first, then
read the [code map](code-map.md) and [boundary contracts](../architecture/contracts.md)
before changing behavior. The [technology guide](technology.md) explains the dependency choices. If supplied locally, also read the agent instructions,
product specification and implementation status. Use `feature/`, `bugfix/`, or another
task-appropriate branch prefix; never use `codex/`. The [development overview](index.md) maps the layers and
links to extension contracts. Preserve unrelated work in your checkout.

## Make a bounded change

Find the existing service or parser responsible for the behavior before adding a new
abstraction. Keep presentation in `ui/`; share domain behavior across UI/CLI/MCP through
services. Preserve exact source evidence and prefer explicit diagnostics to guessed
dependencies. When extraction semantics change, update the parser version so incompatible
cache entries refresh.

Use the [extension recipes](extending.md) for parsers, dbt, providers, automation, exports
and migrations, and the [internal API reference](internal-api.md) for exact contracts.
Regenerate the [source inventory](source-inventory.md) after changing first-party files:

```sh
uv run python scripts/docs/inventory.py
uv run python scripts/docs/inventory.py --check
```

Never execute imported SQL/SAS, persist credential values or weaken path/resource guards.
Changes to cleanup need isolated data homes and regression coverage for preview staleness,
active jobs, retained originals and mandatory backups. General cleanup is not undone by
the specialized history/staging recovery journals.

## Verify the workflow

Run the tests for the responsible subsystem while developing. The [code map](code-map.md)
links each area to existing regression suites. For example, a parser/publication change starts
with `uv run pytest -q tests/test_sql.py tests/test_workflow.py`; an automation change also
needs its denied-policy and CLI/MCP parity tests. Then run the repository checks before submitting:

```sh
uv run pytest -q
uv run ruff check .
uv run python scripts/docs/inventory.py --check
uv run streamlit run app.py --server.address 127.0.0.1
```

Use a disposable home for application checks. Set `DATAFORGE_HOME` in the launching
shell before direct Streamlit startup, or use the explicit-home launcher instead:

```sh
uv run gravetrail-ui --home /absolute/path/to/disposable-home
```

AppTest covers Python interactions; it does not execute the graph's browser JavaScript.
Verify changed UI workflows in a real browser. Stop the UI before independent CLI/MCP
checks of that same home. Do not run destructive tests against an existing user home.

For lineage changes, import either supplied
[sample ZIP](https://github.com/SahasilAK/GraveTrail/tree/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/sample_data),
select only `.sql` or `.sas`, analyze and trace `pub.all_kpis` at depth 30 through seven
layers to all 16 sources. Compare with the bundled manifests and inspect original
statement evidence. SAS additionally exercises 16 temporary WORK datasets. These tests
analyze text; they do not prove licensed SAS or database execution compatibility.

Provider protocol mocks are repeatable without API keys. Live provider tests are separate
and must be explicitly identified. Repository OmniRoute verification uses
`http://localhost:20128/v1`, model `auto/best-reasoning` and the existing
`OMNIROUTE_API_KEY` reference; do not substitute a fixed model or expose the key.
See [testing](../TESTING.md) for commands and test boundaries. For documentation edits, follow
[documentation maintenance](documentation.md), synchronize the docs group and run the strict
site builder/validator described there. A successful local build does not establish hosted publication.

## Submit a reviewable pull request

1. Describe the problem, the resulting behavior and any compatibility/data implications.
2. Include exact verification commands and results; identify skipped or unavailable checks.
3. Update affected user/technical documentation and any local status/context maps.
4. Review the diff for unrelated edits, runtime files, credentials and private source.
5. Commit each tested feature or coherent feature group with a descriptive Conventional
   Commit message, such as `fix: retain source version in evidence exports`.

For packaging changes, smoke-test the actual installed artifact outside the checkout;
native bundles need tests on their target platform. Release publication and repository
settings changes are deliberate maintainer operations. Refer to
[build and release](../BUILD_AND_RELEASE.md) for distribution contracts.

The project uses the
[Apache License 2.0](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/LICENSE).
Include only code and sample data you have the right to contribute.
