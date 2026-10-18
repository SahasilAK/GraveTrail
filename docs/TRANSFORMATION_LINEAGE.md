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
UPDATE/MERGE/DELETE value transformations, recursive SQL, EXCEPT/INTERSECT, named windows,
scalar/correlated value subqueries, unknown UDF semantics, lateral projection/QUALIFY alias
references, base-table positional column aliases, duplicate output names, query-level ordering
and unsupported wildcard layouts have coverage gaps.
SAS MERGE BY, multi-SET ownership, arrays, variable lists, loops, conditional retention,
automatic runtime variables and runtime/macro-expanded expressions remain unresolved.
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
