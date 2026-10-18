# SQL parsing

SQLGlot is used as an AST parser; imported SQL is never sent to DuckDB for execution. Configure
an explicit dialect for vendor syntax or folder prefixes; generic SQL is the default. Parse
failures are diagnostics, never silently replaced by regex guesses or alternate dialects.

Supported tested operations: CTAS, CREATE VIEW/OR REPLACE, INSERT with UNION, UPDATE FROM,
MERGE USING, DELETE USING, SELECT, temporary tables, multiple statements, aliases, qualified
and quoted identifiers, CTEs, subqueries and correlated predicates. SQLGlot supports additional
dialect syntax, but tests define demonstrated coverage. Imported SQL is never executed.

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

The dedicated [Transformation lineage](TRANSFORMATION_LINEAGE.md) view adds output/value
mapping for projections, aliases, expressions, constants, CASE, aggregates/windows, scoped
CTEs/derived tables, explicit INSERT positions and positional UNION branches. Join/filter
context stays separate from value dependencies. `COUNT(*)` retains a rowset dependency.
Consistent imported DDL can infer plain wildcard and INSERT target mappings; it is not
runtime schema verification. A single plain INSERT wildcard maps expanded source positions
to declared destination names only when both schemas have matching cardinality; mixed or
unknown layouts remain unresolved. DDL retains original identifier quoting alongside the
existing name/type schema fields, so expansion preserves quoted case. UPDATE/MERGE/DELETE
transformations, recursive SQL,
scalar/correlated value subqueries, unknown functions and unsupported wildcard layouts
have explicit coverage boundaries. Named windows, EXCEPT/INTERSECT, lateral projection aliases,
base-table positional column aliases and duplicate outputs also remain conservative boundaries.
The broader operation list above describes table
lineage, not complete column coverage.

Only reachable CTE scopes contribute source assets/direct columns; unused CTEs are excluded.
CTEs and subqueries do not become persistent tables. Inner base-table column uses are counted;
outer CTE/derived-column uses are not counted again as transitive base references.
Qualified aliases bind within scopes, including supported correlated parents. Ambiguous
unqualified references are diagnosed. Plain wildcards expand only from consistent imported
typed SQL DDL declarations when enabled in Workspace settings → Parsing. Expanded references
are labeled inferred and retain their query evidence and schema declaration provenance.
Unknown or modified wildcards remain unresolved instead of fabricating names.

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
