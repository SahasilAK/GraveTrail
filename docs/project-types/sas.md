# Analyze a SAS project

Import SAS in **Sources**, choose ordinary files and select `sas`. Run static analysis
with AI unchecked. No SAS license/runtime or model account is required.

Supported DATA steps, PROC SQL and bounded procedure/macro forms establish source-backed
dependencies. Temporary WORK datasets retain job identity. Toggle **Collapse temporary
steps** in Lineage to compare logical dependencies with intermediate steps.

Known-value macro handling is bounded. It does not execute arbitrary control flow,
external includes, runtime functions or environment-dependent paths. A missing edge
can reflect a coverage gap; inspect diagnostics and original source.

Use **Columns** for direct usage and **Transformation lineage** for supported expressions.
Exact rules/exclusions live in [SAS coverage](../SAS_PARSING.md) and
[transformation coverage](../TRANSFORMATION_LINEAGE.md).

Try [the SAS tutorial](../examples/sas.md). Optional AI remains inferred and does not
establish runtime correctness.
