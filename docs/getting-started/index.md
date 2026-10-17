# Getting started

DataForge turns imported SQL and SAS into a local, evidence-backed dependency graph.
Use it to investigate an unfamiliar project, trace the inputs of a report, or assess
which downstream assets a change could affect. CSV imports add source metadata;
their values are never interpreted as code.

The deterministic workflow needs no API key, model, cloud account or database
connection. DataForge analyzes source text without executing the imported scripts.

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
does not promise transitive column transformation lineage.

Keep the application bound to loopback and protect its data home: it stores
complete imported originals. Optional AI assistance has separate configuration
and privacy controls. Continue with [configuration](configuration.md) before
connecting a provider or changing storage locations.
