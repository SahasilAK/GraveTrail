# Getting started

GraveTrail turns imported SQL, SAS and dbt projects into a local, evidence-backed dependency graph.

For dbt, start with the [dbt quick-start workflow](quick-start.md#try-the-dbt-sample)
and [support reference](../DBT_SUPPORT.md). Import the project as a unit, including models,
property YAML and macros, and use local parser analysis. Supplied manifests can add compiled
SQL evidence; imported dbt/Jinja/Python code is never executed.
Use it to investigate an unfamiliar project, trace the inputs of a report, or assess
which downstream assets a change could affect. CSV imports add source metadata;
their values are never interpreted as code.

The deterministic workflow needs no API key, model, cloud account or database
connection. It is the primary, default workflow and sends no source to an AI
provider. GraveTrail analyzes source text without executing the imported scripts.

Both local and optional [AI/hybrid analysis](../AI_ANALYSIS.md) are built in. Use
local parsing alone when you want to keep source away from AI, even for a large
project. When you want additional coverage in a complex system, you can explicitly
enable AI comparison under your privacy controls. AI can help investigate gaps;
it does not guarantee complete or universally correct lineage.

## Choose your installation

| Your goal | Start here |
| --- | --- |
| Try the application or develop from a checkout | [Quick start](quick-start.md) |
| Install into an existing Python environment | [Python and wheel installation](../SETUP_AND_DEPLOYMENT.md#4-python-installation) |
| Run in a persistent container | [Docker installation](../SETUP_AND_DEPLOYMENT.md#5-docker-installation) |
| Build or run a native bundle | [Executable installation](../SETUP_AND_DEPLOYMENT.md#6-standalone-executable-installation) |

Python installations require Python 3.11 or newer. Native bundles must match the
target operating system and architecture. Build tooling in this repository does
not imply that a public binary or container image has been released.

## Your first investigation

1. Create a workspace and import a ZIP, browser-selected folder or allowed host directory.
2. Select the script extensions you want to analyze, then generate lineage.
3. Search for a table and choose its exact asset identity.
4. Trace upstream or downstream dependencies and open the source evidence.
5. Review diagnostics and export the graph, report or relevant originals.

The [quick start](quick-start.md) walks through this using the supplied seven-layer
SQL or SAS project. The [user guide](../user-guide/index.md) explains how to interpret
results, temporary stages, columns and exports.

## Know what the result means

A relationship cites its source file, analyzed version, statement, original line
range and extraction method. Static analysis cannot discover every dynamic SQL
expression, runtime macro or execution-order dependency. Unresolved diagnostics
remain visible instead of being replaced by guessed edges. Direct column usage
is separate from the bounded [Transformation lineage](../TRANSFORMATION_LINEAGE.md) view,
which maps tested SQL/SAS expressions and retains explicit unsupported boundaries.

Keep the application bound to loopback and protect its data home: it stores
complete imported originals. Optional AI assistance has separate configuration
and privacy controls. Continue with [configuration](configuration.md) before
connecting a provider or changing storage locations.
