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

Read with explicit corresponding SQL dialect. Accuracy claims apply only to these examples.
