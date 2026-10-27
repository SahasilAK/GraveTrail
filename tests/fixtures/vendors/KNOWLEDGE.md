# tests/fixtures/vendors/

Synthetic hand-labeled source examples, no execution or proprietary source.
- `expected.json` — Explicit expected edges, temporary identities and direct column sets.
- `tsql.sql` — SELECT INTO local #stage, downstream insert and distinct persistent stage.
- `postgres.sql` — Temporary CTAS, reachable CTE, insert and DELETE USING.
- `snowflake.sql` — Temporary CTAS/QUALIFY and source-bound MERGE.
- `bigquery.sql` — Backtick catalog/schema identifiers and CTE usage.
- `teradata.sql` — Parenthesized volatile CTAS with preserved rows and insert.
- `oracle.sql` — MERGE and CREATE OR REPLACE VIEW.
- `procedures.sas` — SORT → MEANS → TRANSPOSE explicit DATA/OUT chain.
- `postgres_procedure.sql` — Parameterless LANGUAGE SQL dollar body with two INSERT dependencies; exact original definition evidence, not proof of invocation.
- `snowflake_literal.sql` — Single/dollar-quoted EXECUTE IMMEDIATE payloads; escaped apostrophes and direct columns without execution.
- `sas_macro_variables.sas` — Chained known-value %LET expressions and double-quoted file-path resolution with original DATA/PROC evidence.

Read with explicit corresponding SQL dialect. Accuracy claims apply only to these examples.
