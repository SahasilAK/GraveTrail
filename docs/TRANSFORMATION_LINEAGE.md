# Column transformation lineage

Choose **Transformation lineage**, directly below **Columns** in Explore, to follow a
column's value through analyzed SQL or SAS. **Columns** retains the existing direct
usage report. A join/filter reference can influence which rows appear without supplying
the value of every output column.

## Trace a column

1. Import sources and run **Analysis**. Existing workspaces keep their table/direct-usage
   facts after upgrade; transformation coverage appears after analysis with parser 11.
2. Choose an exact asset, including its job identity for temporary tables. Select a
   physical output column, or paste a column name or exact column ID.
3. Choose **How it is produced** (upstream) or **What it affects** (downstream), depth
   and resolution status. The page displays at most 200 derivations and 500 selector entries.
4. Inspect a transformation to see its original expression, input roles, branch and
   immutable source hash. The source preview shows at most 200 lines / 12,000 characters
   from the analyzed original. Intermediate CTE and SAS assignment versions remain visible.
5. Export the bounded trace as CSV or JSON. Both include coverage and truncation markers,
   even when no derivation is known. Image export is not part of this feature.

For `o.quantity * o.unit_price AS gross_amount`, the value inputs are exactly quantity
and unit_price. `WHERE o.status = 'COMPLETE'` is `row_filter` context; join keys have
the `join` role. CASE/IF tests use `value_selection`; windows preserve `partition` and
`order`. Aggregates/windows retain relation `rowset` context. `COUNT(*)` does not depend
on every column. A literal-only output is a constant with zero value inputs; row context
can still apply. Downstream paths label value effects separately from row-selection effects.
Display input limits do not change those labels. Equivalent quoted and unquoted column names share an
identity under workspace case rules; quoted case and escaped identifier characters are retained.

## Tested static coverage

| Construct | Behavior |
| --- | --- |
| SQL projection, alias, expression, literal, CAST, CASE/IF | Named output derivations and distinct dependency roles |
| Aggregation/window | Argument columns, rowsets and partition/order roles |
| CTE/derived table | Statement-local intermediate columns; each expression remains inspectable |
| INSERT SELECT | Explicit target lists map by position; consistent imported target DDL can infer a mapping after a single plain wildcard expands. Unknown or mismatched target schemas and mixed wildcard layouts stay unresolved |
| UNION | Branch-specific derivations map by position; incompatible cardinality stays unresolved |
| Plain wildcard | Single-source consistent imported DDL may expand as inferred; modifiers, scoped/branch schemas and ambiguous layouts stay unresolved |
| SAS PROC SQL | Shared SQL contract, with SAS library/WORK identity and original source evidence |
| SAS DATA | Ordered explicit assignment versions, simple single SET and explicit KEEP/DROP/RENAME where ownership/output names are established |

SQL fixtures cover generic SQL plus explicitly selected PostgreSQL, T-SQL and Snowflake
syntax cases; supported syntax is bounded by the fixtures, not by SQLGlot's full dialect list.
Positional GROUP BY dependencies resolve for generic SQL, PostgreSQL, DuckDB, Snowflake
and BigQuery. Other dialects and invalid positions retain explicit coverage gaps.
Parentheses around positions are preserved; normalized unary-plus grouping syntax
stays unresolved rather than being mistaken for a position.
DISTINCT records duplicate-selection inputs. DISTINCT ON records selectors and an unresolved
row-choice boundary. Duplicate-eliminating UNION, LIMIT/OFFSET and table sampling retain
explicit boundaries; UNION ALL retains separate value branches. dbt uses the same reachable
SQL scopes, excluding unused CTEs from column facts.
UPDATE/MERGE/DELETE value transformations, recursive SQL, EXCEPT/INTERSECT, named windows,
scalar/correlated value subqueries, unknown UDF semantics, lateral projection/QUALIFY alias
references, base-table positional column aliases, duplicate output names, query-level ordering
and unsupported wildcard layouts have coverage gaps.
SAS MERGE BY, multi-SET ownership, arrays, variable lists, loops, conditional retention,
automatic runtime variables and runtime/macro-expanded expressions remain unresolved.
SAS applies statement KEEP/DROP, statement RENAME, then output KEEP=/DROP= and RENAME=
options. Repeated selection statements or dataset options remain explicitly unresolved.
Existing table-level extraction can still recognize a construct that has no column mapping.

## Read the boundaries

The view distinguishes a known constant, a known derivation, no known dependency, an
unresolved scope and analysis that has not established transformation coverage. None of
these states proves live database behavior. Imported declarations remain inferred schema
evidence. Parser diagnostics remain visible alongside known results.

Every query uses one committed analysis revision and its identity settings. Older parser
caches require explicit reanalysis to refresh identity and schema mappings. Changed parsing
settings produce a settings-changed boundary until reanalysis. Reimported but unanalyzed code produces
an analysis-stale marker while the old steps retain their original source hashes. Multiple
writes to one physical column are alternatives with an unknown-order boundary; their
inputs are never chained into a claimed execution history. UNION branches within one
operation remain distinguishable. Cycles and depth/item/input limits terminate visibly.
Unresolved writes remain visible beside known derivations and stop chaining through uncertain
values. The service visits bounded column/effect states rather than enumerating every possible path;
omitted path-step records carry their own truncation marker.
A column used as both a value and a filter or join key retains both `value` and
`row_selection` impact paths; derivation records remain unique. Cycles retain their
boundary while newly discovered effect states can propagate within the traversal limits.

Columns shows unused declared columns only with current, complete direct-reference
coverage. Ambiguous references, parser diagnostics, failed sources, unexpanded wildcards
and stale analysis suppress the unused list while retaining known used columns.
Diagnostics without reliable asset attribution conservatively affect the workspace.
Agent direct-column reports expose the same `usage_coverage` completeness and reasons,
independently of display filters.

The UI defaults to depth 5 and caps depth at 15. Shared service/CLI/MCP queries support
depth 1–30, at most 20,000 derivations and bounded inputs/paths. Agent response character
budgets and continuation cursors apply in addition to traversal limits; continuation pages
cover the computed bounded trace and cannot extend a truncated traversal. Original expressions
and optional source snippets obey agent source permissions.

See [CLI](CLI_GUIDE.md), [MCP](MCP_INTEGRATION.md), [data model](DATA_MODEL.md),
[SQL coverage](SQL_PARSING.md), [SAS coverage](SAS_PARSING.md) and
[measured performance](PERFORMANCE.md) for the contracts and limits.

## Storage and recovery

Migration 5 adds column references, derivations, inputs and an analysis marker without
rewriting old facts. Parser cache 11 refreshes extraction on the next explicit analysis.
Reanalysis replaces the committed derivations transactionally; a parse error for an already
analyzed source retains the previous committed result. Cleanup previews include dependent
column records. Columns cleanup clears transformation coverage as well as direct usages;
analyze again to rebuild it. Whole-home backup/restore and integrity checks include the new
records. Version-4 backups can be restored and upgraded when opened. To downgrade, restore
a complete pre-upgrade home with the matching prior application version.

## Optional project AI extraction

The [AI project analysis](AI_ANALYSIS.md) workflow independently extracts direct usage and
scoped transformations from exact original file parts. Structural/evidence validation
checks source ownership, hashes, ranges and identities without requiring parser semantic
approval. Accepted facts remain inferred, preserving expression, branch/version, ordinal
and value versus row-context roles. Manual advisory tasks do not gain transformation
merge rights, and parser results do not fill AI omissions.

Unresolved derivations stop confident chaining; conflicting writers/order remain boundaries.
Hybrid/additional-review execution is retired. Processed ranges and schema-valid output do
not establish semantic completeness or live-model accuracy. dbt Python column derivations,
dynamic Jinja and unsupported compiled-to-original mappings remain partial. Current
protocol 5 qualification uses independent nonempty mock fixtures; live accuracy remains
separate evidence.

## Column graph and parser 21 follow-up

Columns offers Direct references and Lineage graph views. Graph boxes retain
column/derivation identity, UNION branches, scopes and SAS versions. Display caps
are separate from trace coverage. Source files load lazily from exact analyzed
hashes; the graph component receives no expression or source text. Re-run Analysis
after this parser upgrade.

Table aliases and intermediate output columns follow the selected SQL dialect's
quoted and unquoted identifier rules. Equivalent intermediate references retain
the producer's column identity so traces remain connected.

Intermediate set-operation LIMIT/OFFSET/sampling is marked incomplete. Unused CTE
UNION DISTINCT does not contaminate active projections or stop their traces.

PostgreSQL UPDATE support: single target; simultaneous SET of literals, NULL,
boolean, target columns and arithmetic (+, -, *, /, %); optional comparison,
AND/OR/NOT/IS predicates. Old inputs have statement-scoped prior-value identities.
Prior rows, unchanged columns, partial writes and writer order remain unresolved.
FROM, WITH, tuple assignment, DEFAULT, functions, subqueries, RETURNING, other
modifiers and other dialects remain unsupported.

PostgreSQL INSERT VALUES support: one literal row and explicit unique target
columns, including NULL/boolean/negative numbers. Exact target order and evidence
are retained. Existing rows and omitted-column defaults remain unresolved; a
literal insert never proves the entire table column constant. Multiple rows,
omitted lists, DEFAULT, expressions/functions, conflicts, RETURNING and subqueries
remain unsupported.

References: [PostgreSQL UPDATE](https://www.postgresql.org/docs/current/sql-update.html)
and [PostgreSQL INSERT](https://www.postgresql.org/docs/current/sql-insert.html).

Supported mutation operations also publish an unresolved partial-write scope boundary, so a known unassigned target column cannot appear to have complete lineage.
