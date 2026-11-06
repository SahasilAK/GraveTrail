# src/dataforge/parsers/

Pure static parsers returning ParseResult. Add positive/negative fixtures and bump services.PARSER_VERSION for semantic changes. No imported code is executed.

- `sql_transformations.py` — SQLGlot projection spans, scoped stars, scalar correlation, set
  membership and bounded recursive feedback in native SQL. Schema-dependent ownership and
  INSERT order defer to materialization. Databricks adds nested fields, lateral projection
  aliases, pipeline controls and generator/pivot inputs.
- `sas_transformations.py` — ordered DATA assignment versions, bounded single SET and
  explicit column options, known scalar functions and conservative runtime/unknown coverage.
Parser11 preserves DDL identifier quoting for schema expansion and refreshes column
identities; PROC SQL remaps shared derivations through SAS namespaces.

## Files
- `__init__.py` — Package marker; no business behavior.
- `csv.py` — parse_csv/bounded_records extract sampled schema/types/preview and row counts with preallocation width/record limits; values never become code.
- `sas.py` — parse_sas uses conservative DATA/PROC blocks, quote-aware known-value %LET expressions and library rules; unresolved assignments/runtime macro mutations invalidate stale bindings. Expansion is bounded; dynamic flow/name literals are not guessed; inline data is skipped.
- `sas_sql.py` — Instance-local configured SQLGlot parser for SELECT FORMAT=/LENGTH= modifiers, CALCULATED aliases and SAS DATETIME(); preserves original evidence through sas.py and diagnoses malformed/ambiguous syntax.
- `sql.py` — parse_sql uses SQLGlot reachable scopes, DML sources/targets and direct usage; wrapped_sql inspects bounded parameterless PostgreSQL SQL dollar bodies and Snowflake literal EXECUTE IMMEDIATE with original wrapper evidence. Runtime identifiers/binds/control flow stay unresolved; wrapper DDL supplies no unconditional schema. declared_schema records plain typed DDL/invalidation, excluding unused CTEs and unsafe wildcards.
- `sql_databricks.py` — native-dialect pipeline grammar and script-local USE namespace.
  Normalizes static STREAM relations before scopes and qualifies only physical table nodes afterward.
  Separates EXPECT policies and AUTO CDC change-feed controls from output fields while retaining
  the original statement and projection spans. PROC SQL keeps its instance-local parser.
- `sql_databricks_relations.py` — resolves supported LATERAL VIEW generators and static PIVOT buckets
  against selected sources, keeping generated aliases and pivot outputs out of base-column usage.

SAS parse_sas accepts sql_dialect for PROC SQL only; default/extension/folder precedence is
resolved in services.source_dialect. SAS DATA/PROC static rules are unchanged.

SQL preserves SQL Server #/## identifier flags, top-level SELECT INTO set-query targets and
Teradata volatile parenthesized CTAS inputs; current parser cache version11.

SAS rule blocks slice original source by line-anchored offsets, preserving exact whitespace
and same-line boundaries; inline data cannot redirect matching evidence offsets.

SQL routine headers use a forward-only whitespace/comment scan with dialect-specific nested
block comments and a bounded keyword regex; no ambiguous repeated prefix or source normalization.

Parser13: PROC SQL validates bounded adjacent SAS date/time/datetime constants and retains their exact typed tokens as Var so generated usage expressions keep suffixes; value derivations remain unresolved. SQL activates reachable MERGE USING and UPDATE/DELETE scalar scopes, excludes unused CTEs and restricts outer DML column maps to visible relations.

Parser14 retains private original expression offsets for SQL projections and SAS assignment versions so semantic validation cannot swap identical text between branches/versions. Literal wrapper rebinding drops inner-only offsets. Private coordinates never replace original full-operation evidence.
