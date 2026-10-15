# src/dataforge/parsers/

Pure static parsers returning ParseResult. Add positive/negative fixtures and bump services.PARSER_VERSION for semantic changes. No imported code is executed.

## Files
- `__init__.py` — Package marker; no business behavior.
- `csv.py` — parse_csv/bounded_records extract sampled schema/types/preview and row counts with preallocation width/record limits; values never become code.
- `sas.py` — parse_sas uses conservative DATA/PROC blocks, macro/library rules and unresolved diagnostics. Dynamic flow/name literals are not guessed; inline data is skipped.
- `sql.py` — parse_sql uses SQLGlot reachable scopes, DML sources/targets and direct usage; declared_schema records typed DDL/invalidation (including SWAP/RENAME), and plain wildcard eligibility is separate from modifiers. Excludes unused CTEs and diagnoses failures.

SAS parse_sas accepts sql_dialect for PROC SQL only; default/extension/folder precedence is
resolved in services.source_dialect. SAS DATA/PROC static rules are unchanged.
