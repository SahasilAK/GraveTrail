# Evidence, confidence and coverage limits

Use a relationship as an investigation starting point, then open its source.

| Result | Establishes | Does not establish |
| --- | --- | --- |
| Static relationship | Supported parser rules found source-backed dependency evidence | That code ran or every runtime branch was explored |
| Artifact-declared dbt edge | The supplied snapshot declares a dependency | An observed warehouse read or verified unknown runtime configuration |
| Compiled SQL expression | A supported expression appears in supplied compiled text | That it appears verbatim in the original template |
| AI-inferred fact | An inferred structured result passed host integrity checks | Semantic correctness or complete extraction |
| Missing edge | No edge exists in this analyzed view | Proof that no dependency exists |

Evidence retains source version, statement/artifact origin, coordinates and extraction
method. JSON Pointer/raw JSON slices differ from decoded compiled SQL. Pending reimports
do not rewrite evidence from earlier analysis.

Confidence is an extraction attribute, not a measured probability of correctness.
Filtering inferred facts or raising confidence changes coverage; record those filters
with shared findings.

Dynamic names, unexecuted macros, unknown schemas, Python/DataFrame behavior and unsupported
syntax can remain unresolved. Wildcards require consistent imported declarations for
supported expansion. An unused-column list describes analyzed references, not every
live consumer.

Review **Analysis → Diagnostics**, freshness, truncation, unresolved support and response
completeness together. Sample success/test counts do not measure arbitrary-project accuracy.
Read the [SQL](../SQL_PARSING.md), [SAS](../SAS_PARSING.md) or [dbt](../DBT_SUPPORT.md) limits.
