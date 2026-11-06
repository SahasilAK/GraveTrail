# SQL parsing

SQLGlot parses imported SQL without executing it. In **Sources → Import**, select **SQL source
type** when importing SQL. The choice applies to SQL files in the batch, including ZIP members.
**Use workspace settings** follows the longest matching folder rule, then the extension rule,
then the workspace default. **Generic SQL** explicitly selects the generic parser even in a
Databricks workspace. Parse failures produce diagnostics without switching dialects.

Supported tested operations: CTAS, CREATE VIEW/OR REPLACE, INSERT with UNION, UPDATE FROM,
MERGE USING, DELETE USING, SELECT, temporary tables, multiple statements, aliases, qualified
and quoted identifiers, CTEs, subqueries and correlated predicates. SQLGlot supports additional
dialect syntax, but tests define demonstrated coverage. Imported SQL is never executed.

Table dependencies include reachable `MERGE USING (SELECT ...)` inputs and scalar or
`EXISTS` subqueries in `UPDATE`/`DELETE`. Unreferenced CTEs remain excluded. Following a
subquery's table inputs does not establish an outer alias's value-column ownership;
unsupported DML transformations remain unresolved. Parser version 17 refreshes local
results on the next analysis. To correct an existing file, open **Sources → Inventory →
Inspect a source file**, save its SQL source type, then run **Analysis**. A successful
run replaces the previous facts even when the file bytes are unchanged. Paused AI runs created with older parser or
validator semantics require a new run, preserving the previous published graph.

## Databricks lineage

Select **Databricks** or inherit the `databricks` dialect. The cases below describe
the tested forms. Source statements and projection evidence retain the imported spelling.

| Construct | Coverage and boundaries |
| --- | --- |
| `USE CATALOG`, `USE SCHEMA` | Qualify subsequent reads and writes within that script. Fully qualified names keep their identity. |
| `STREAM(t) AS f` | Bind the alias to a static table, including with streaming read options. Dynamic names retain a diagnostic. |
| CTE stars and positional INSERT | Expand named CTE outputs in order, including chained stars and renames. Positional INSERT uses consistent imported target DDL and matching widths. Physical stars also need consistent source DDL. `BY NAME` uses exposed query names. |
| Structs | Retain qualified field paths such as `f.soil.ph`, including quoted dots in a field name. Expand a physical struct star only from consistent typed DDL. |
| Lateral column aliases | A uniquely bound preceding projection alias can supply a value. Local input columns take precedence. A physical input needs declared columns when precedence is uncertain. |
| Scalar subqueries | Follow one named or scalar SELECT output, including an aggregate, and keep qualified correlated predicates in row selection. Ambiguous correlations retain coverage gaps. |
| Pipeline expectations | Track predicates over named output projections as warning, drop, or failure inputs. Supports streaming tables, materialized views and legacy `CREATE LIVE TABLE` syntax. A constraint name creates no output column. The external legacy `LIVE` virtual schema configuration is unavailable to static analysis. |
| `EXCEPT`, `INTERSECT` | Align explicit projections by position for `ALL` and `DISTINCT`. Both sides affect row membership. Values trace to the left. Unknown widths or mismatched widths stay unresolved. |
| `LATERAL VIEW` | Trace explicitly named `EXPLODE`, `OUTER EXPLODE`, and `POSEXPLODE` outputs to their collection. Unsupported generators leave their affected outputs unresolved. |
| `PIVOT` | Track each statically named bucket's aggregate, key and grouping columns. Grouping context needs known intermediate outputs or consistent input DDL. Dynamic buckets, chained or compound pivots, and ambiguous names retain coverage gaps. |
| `AUTO CDC` | Bind a static change feed to a declared destination with a named flow or inline flow. Separate payload values from match keys, sequencing, delete/truncate conditions and history. Wildcard payload and history layouts require consistent schemas. Snapshot flows, per-row update masks and generated SCD system columns are outside this coverage. |
| Recursive CTEs | Trace explicit anchor and step projections for a `UNION ALL` with one direct self-reference. The scoped feedback is a bounded cycle in the trace. Other recursive shapes retain coverage gaps. |

See the [Databricks name-resolution reference](https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-name-resolution)
and the [AUTO CDC reference](https://docs.databricks.com/aws/en/ldp/developer/ldp-sql-ref-apply-changes-into).

## Literal procedure and dynamic SQL bodies

With the explicit `postgres` dialect, parameterless `CREATE [OR REPLACE] PROCEDURE` definitions
with `LANGUAGE SQL` and a dollar-quoted body support straight-line SELECT, common DML and
CREATE TABLE/VIEW statements. Multiple body statements contribute separate operations.
These are definition dependencies: they do not prove the procedure was invoked. Functions,
parameters, other languages, configuration-changing properties such as `SET search_path`,
BEGIN/IF/loop blocks and unsupported statements leave the whole body unresolved.
For procedure formats without a self-contained quoted body, analysis stops at the header
and reports that the remainder of the file was not analyzed. This prevents semicolon-split
body fragments from appearing as independent top-level SQL; separate supported scripts into
their own files to analyze them independently.
See PostgreSQL's [procedure definition reference](https://www.postgresql.org/docs/current/sql-createprocedure.html).

With the explicit `snowflake` dialect, `EXECUTE IMMEDIATE` accepts one literal SQL statement
in single quotes (including doubled apostrophes) or `$$` delimiters. Variables, concatenation,
USING/bind arguments, backslash escapes in single-quoted payloads and scripting blocks remain
unresolved. Nested supported wrappers stop at eight levels. See Snowflake's
[EXECUTE IMMEDIATE reference](https://docs.snowflake.com/en/sql-reference/sql/execute-immediate).

Operations use `sql-procedure-body` or `sql-literal` methods and retain the complete original
enclosing statement and its line range, including original quotes and LF/CRLF endings. Body
DDL does not supply unconditional workspace schema declarations or wildcard expansion.
`tests/test_parser_static_wrappers.py` and the three additional vendor fixtures verify these
boundaries, persistence, direct columns, exact evidence and cache reuse. Parser cache version 11
refreshes older analysis on the next run; previously built packages must be rebuilt for these rules.

## Column transformation coverage

Use [Transformation lineage](TRANSFORMATION_LINEAGE.md) to trace a column upstream through
expressions, CTEs, and physical tables, or downstream to see where it contributes values or
filters rows. The shared SQL parser keeps join and filter inputs separate from value inputs.
`COUNT(*)` retains a rowset dependency.

Plain stars expand from named CTE and derived-table outputs or a consistent imported source
schema. A positional INSERT uses an explicit target list or consistent target DDL and requires
matching widths after expansion. For unqualified join columns, a complete set of trusted input
layouts must identify one owner. DDL-backed mappings are inferred.

The shared parser follows single-output scalar subqueries with qualified correlations,
`EXCEPT` and `INTERSECT` with known positions, and explicit recursive `UNION ALL` CTEs with one
direct self-reference in the step. Set comparisons add row-membership dependencies on both
sides, and left-side expressions supply values. Incomplete layouts or ambiguous bindings retain
coverage gaps. Other boundaries include `EXISTS` membership, unsupported UPDATE/MERGE/DELETE
assignments, named windows, unknown functions, and dialect-specific projection aliases, generators,
and pivots outside the tested forms above.

Only reachable CTE scopes contribute source assets/direct columns; unused CTEs are excluded.
CTEs and subqueries do not become persistent tables. Inner base-table column uses are counted;
outer CTE/derived-column uses are not counted again as transitive base references.
Qualified aliases bind within scopes, including supported correlated parents. Ambiguous
unqualified references are diagnosed. Plain wildcards expand only from consistent imported
typed SQL DDL declarations when enabled in Workspace settings → Parsing. Expanded references
are labeled inferred and retain their query evidence and schema declaration provenance.
Unknown or modified wildcards remain unresolved except for the supported Databricks cases above.

Display names preserve spelling. Dotted quoted components retain their boundaries. Lookup
defaults to case-insensitive normalization; configure case sensitivity for your environment.
Unqualified cross-file matches link only to a unique qualified candidate and are inferred.

Statements retain the original snippet and original one-based line range. Semicolon splitting
honors comments, quoted strings, quoted identifiers and dollar strings. Procedural blocks with
internal statement syntax may remain unsupported rather than producing misleading evidence.

Explicit typed CREATE TABLE declarations are reconciled workspace-wide through the same asset
identity resolver as lineage, without assuming script execution order. Identical declarations
retain each source reference. Conflicting declarations, duplicate normalized column names,
ALTER/DROP/replacement declarations and incomplete schemas disable expansion. Ambiguous
unqualified DDL invalidates all possible declared candidates. SWAP/RENAME invalidates both
operands. LIKE, inheritance, unsupported table properties and wildcard modifiers
(EXCEPT/REPLACE/RENAME) are conservative unknowns. Schemas are not propagated through CTAS,
CTEs or CSV filename guesses. CSV headers describe the CSV asset alone. The data dictionary
distinguishes DDL-declared types from sampled CSV types and incomplete direct references.

Current exclusions: database-catalog/schema discovery, general stored procedures, runtime-built SQL,
dynamic templating,
general schema evolution, arbitrary table-valued functions and runtime temporary-session
discovery. Supplied Workspace settings → Parsing job/session IDs isolate temporary assets; persistent tables stay
workspace-global. Unspecified inputs use the legacy workspace job. Same-job mixed temporary/
persistent reads are unresolved, because execution order is unavailable. Repeated writes expose possible static
dependencies; static code alone does not determine which write executed last.


Labeled vendor fixtures cover SQL Server SELECT INTO (#/## prefix identities, including
qualified tempdb references), PostgreSQL temporary/CTE/DELETE USING, Snowflake QUALIFY/MERGE,
BigQuery three-part backtick identifiers, Teradata parenthesized volatile CTAS and Oracle
MERGE/views. SELECT INTO set queries retain both branches. SAS procedure-chain fixtures are
separate. These examples establish measured fixture coverage, not universal vendor support.
SQLGlot AST temporary flags are preserved in asset names; imported SQL is never executed.
