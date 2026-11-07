# Column transformation lineage

Choose **Transformation lineage**, directly below **Columns** in Explore, to follow a
column's value through analyzed SQL or SAS. **Columns** retains the existing direct
usage report. A join/filter reference can influence which rows appear without supplying
the value of every output column.

## Trace a column

1. Import sources and run **Analysis**. Existing workspaces keep their table/direct-usage
   facts after upgrade. Run analysis with parser version 22 to refresh SAS coverage.
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
can still apply. Downstream paths distinguish values, row selection and pipeline controls.
Display input limits do not change those labels. Equivalent quoted and unquoted column names share an
identity under workspace case rules; quoted case and escaped identifier characters are retained.

## Tested static coverage

| Construct | Behavior |
| --- | --- |
| SQL projection, alias, expression, literal, CAST, CASE/IF | Named output derivations and distinct dependency roles |
| Aggregation/window | Argument columns, rowsets and partition/order roles |
| CTE/derived table | Statement-local intermediate columns, including chains of named projections and plain stars |
| INSERT SELECT | Explicit target lists or consistent imported target DDL map by position. Widths must agree after wildcard expansion |
| UNION, EXCEPT, INTERSECT | Known branch positions remain inspectable. EXCEPT and INTERSECT distinguish left-side values from membership inputs on both sides |
| Scalar subquery | A single projected value and qualified correlated predicates remain separate |
| Recursive CTE | Explicit `UNION ALL` anchor and direct step trace through a bounded scope cycle |
| Plain wildcard | Expand from named scoped outputs, imported DDL or a single complete query definition. Unknown layouts stay unresolved |
| Inline and generated values | Trace named literal VALUES and literal UNNEST outputs to inline data. Current date and time expressions show a runtime origin |
| SAS PROC SQL | Shared SQL contract, SAS library/WORK identity, and single arithmetic UPDATE assignments with simple IN-subquery row selection |
| SAS DATA | Inline INPUT, ordered assignments, SET passthrough and concatenation, simple IF/ELSE OUTPUT routing, bounded MERGE BY, and the documented hash and fixed-array forms |
| SAS procedures | Simple SORT, NWAY SUMMARY/MEANS sums and means, grouped RANK, PROC APPEND FORCE with complete layouts, and conditional numbered PROC TRANSPOSE outputs |

SQL fixtures cover generic SQL plus explicitly selected PostgreSQL, T-SQL, Snowflake and
[Databricks](SQL_PARSING.md#databricks-lineage) syntax. The following gaps apply outside the tested
Databricks forms described in the SQL guide.
UPDATE/MERGE value transformations, unsupported recursive shapes, named windows,
ambiguous correlations, complex EXISTS membership, unknown UDF semantics, lateral projection/QUALIFY alias
references, base-table positional column aliases, duplicate output names, query-level ordering
and unsupported wildcard layouts have coverage gaps.
Other SAS MERGE and multi-output forms, repeated SET statements, general arrays, variable lists, loops, conditional retention,
automatic runtime variables and runtime/macro-expanded expressions remain unresolved.
Existing table-level extraction can still recognize a construct that has no column mapping.

## How confidence and coverage work

In the Lineage tree, **Minimum evidence confidence** is the lowest stored
confidence among the records supporting the displayed relationship. The score
reflects how the evidence was established. It has no statistical calibration.

| Table relationship evidence | Stored confidence |
| --- | --- |
| Direct parser evidence with resolved identities | Uses the parser operation's value, which defaults to 1.00. |
| Inferred source or target identity | Capped at 0.85. |
| Accepted AI evidence | Capped at 0.80 and labeled inferred. |

Transformation lineage reports a trace state and counts coverage boundaries.
A trace is complete for the requested scope when analysis has established coverage,
there are no unresolved boundaries, and traversal finishes without truncation.
Unknown dependencies have no known denominator, so the view reports the reasons
for each gap alongside the known steps.

For example, consider a query that selects `o.id AS order_id` and `amount AS total`
from `orders o JOIN adjustments a ON o.id = a.id`. If both tables declare `amount`,
the parser can trace `order_id` to `orders.id`, but the trace for `total` keeps an
unresolved ownership boundary. Both table relationships can still have direct parser
evidence. Open **Coverage details** to see why the value trace could go no further.

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

## Optional project AI extraction

The [AI project analysis](AI_ANALYSIS.md) workflow can propose direct usage and scoped transformations, then validates them against complete original units. It uses a new accepted project path; legacy advisory/manual LLM operations do not gain transformation merge rights. AI additions remain inferred, preserving exact expressions, branch/version, ordinal and value versus row-context roles.

The initial extra structural verification is limited to fixture-backed static SQL UPDATE/MERGE assignments. Unsupported variants stay unresolved. Additional AI review cannot fill missing semantic proof. Unresolved derivations stop upstream/downstream chaining; unknown writer order remains a boundary even when one possible writer is accepted. Hybrid is the default AI comparison option; AI-generated mode is experimental and has no measured live accuracy claim.
