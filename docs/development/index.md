# Develop GraveTrail

<!-- Compatibility anchors for sections now linked from this page. -->
<span id="development"></span>
<span id="engineering-contracts"></span>
<span id="find-the-responsible-layer"></span>
<span id="guides-by-task"></span>


GraveTrail is a local Python application for inspecting SQL, SAS and dbt dependencies with
retained source evidence. Streamlit, the CLI and MCP are clients of shared services. The
Python package remains named `dataforge`; the distribution and primary commands use
`gravetrail`.

These developer pages describe the source baseline
[`1864dc8`](https://github.com/SahasilAK/GraveTrail/tree/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414)
on `codex/resumable-ai-lineage`, rather than assuming local `main` or release `v0.0.1`
contains the same interfaces. The baseline is 48 commits ahead of local `main` (`d809c33`).
dbt support and current independent AI postdate v0.0.1; current behavior must be read against
this pinned source. Python examples describe **internal developer APIs**, not a stability
promise for third-party packages. Use the [CLI guide](../CLI_GUIDE.md) and
[MCP guide](../MCP_INTEGRATION.md) for supported automation surfaces.

## A useful first hour

1. [Set up a disposable checkout and follow one import](getting-started.md). Run the small
   persisted workflow before exploring the largest modules.
2. Read [how the system works](../architecture/overview.md) and the
   [contracts at each boundary](../architecture/contracts.md).
3. Find the owning subsystem in the [code map](code-map.md). Use the complete
   [source inventory](source-inventory.md) to locate individual files and exports.
4. Use the [technology guide](technology.md) to understand each dependency's actual role,
   then the [internal API examples](internal-api.md) to follow stored evidence.
5. Make a focused change using [extension recipes](extending.md) and the
   [contribution workflow](contributing.md).

## Choose a reading path

| Your task | Start here | Then inspect |
| --- | --- | --- |
| Fix SQL or SAS lineage | [Parser recipe](extending.md#extend-a-parser) | `models.py`, parser regression tests, `services.py` publication |
| Add dbt resource support | [dbt recipe](extending.md#extend-dbt-support) | discovery, resources, resolution, evidence and artifacts |
| Investigate graph or column results | [Code map](code-map.md#facts-and-investigation) | exact asset IDs, graph limits, schema and column coverage |
| Change AI extraction/recovery | [AI architecture](../architecture/ai-analysis-pipeline.md) | coordinator, validation, durable requests and publication |
| Add an automation operation | [Transport recipe](extending.md#add-a-service-operation-and-transport) | shared service policy, CLI/MCP adapters and parity tests |
| Change settings or storage | [Boundary contracts](../architecture/contracts.md) | validators, revisions, migration/backup/restore tests |
| Change the website | [Documentation maintenance](documentation.md) | docs group, navigation, publication allowlist and strict build |

## Working rules

Imported programs are data. Keep parsing and investigation free of execution. Preserve file
identity, source hash, exact statement text and original coordinates when changing a result.
Unknown or ambiguous relationships need diagnostics and coverage markers. Keep Streamlit in
the presentation layer; CLI and MCP must reuse policy-checked services. Use a disposable data
home and a single owning DuckDB process. Runtime credentials belong to request/session scopes
or named environment references, never stored profile values or job journals.
