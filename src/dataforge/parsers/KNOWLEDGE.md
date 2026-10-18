# src/dataforge/parsers/

Pure static parsers returning ParseResult. Add positive/negative fixtures and bump services.PARSER_VERSION for semantic changes. No imported code is executed.

## Files
- `__init__.py` — Package marker; no business behavior.
- `csv.py` — parse_csv/bounded_records extract sampled schema/types/preview and row counts with preallocation width/record limits; values never become code.
- `sas.py` — parse_sas uses conservative DATA/PROC blocks, quote-aware known-value %LET expressions and library rules; unresolved assignments/runtime macro mutations invalidate stale bindings. Expansion is bounded; dynamic flow/name literals are not guessed; inline data is skipped.
- `sas_sql.py` — Instance-local configured SQLGlot parser for SELECT FORMAT=/LENGTH= modifiers, CALCULATED aliases and SAS DATETIME(); preserves original evidence through sas.py and diagnoses malformed/ambiguous syntax.
- `sql.py` — parse_sql uses SQLGlot reachable scopes, DML sources/targets and direct usage; wrapped_sql inspects bounded parameterless PostgreSQL SQL dollar bodies and Snowflake literal EXECUTE IMMEDIATE with original wrapper evidence. Runtime identifiers/binds/control flow stay unresolved; wrapper DDL supplies no unconditional schema. declared_schema records plain typed DDL/invalidation, excluding unused CTEs and unsafe wildcards.

SAS parse_sas accepts sql_dialect for PROC SQL only; default/extension/folder precedence is
resolved in services.source_dialect. SAS DATA/PROC static rules are unchanged.

SQL preserves SQL Server #/## identifier flags, top-level SELECT INTO set-query targets and
Teradata volatile parenthesized CTAS inputs; parser cache version9.

SAS rule blocks slice original source by line-anchored offsets, preserving exact whitespace
and same-line boundaries; inline data cannot redirect matching evidence offsets.
