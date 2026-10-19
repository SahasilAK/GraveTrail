# Lineage engine

`services.analyze` loads inventory metadata and a hash/config/path keyed parse cache. It parses
only changed input, then materializes a complete workspace graph in one transaction. A failed
materialization rolls back facts and leaves a failed run record; original source is unaffected.
Selected analysis reuses caches for unselected files; changed unselected files stay pending.

Operations have explicit input/output memberships. Asset-to-asset edges reference an operation,
statement, file and analysis run. `Store.edges` joins evidence code and exact line ranges.
Original bytes are available through `Store.original`; the UI shows original source separately
from extracted statement snippets. Step numbers are dependency ordering, not execution order.

Column transformations are an additive contract on `Operation.derivations`, persisted by
`transformations.materialize_columns` in the same analysis transaction. `column_catalog`
and `trace_columns` provide shared, indexed asset/column queries. The traversal keeps
bounded visited/scheduled column/effect states, not all-workspace paths. CTE scopes,
SAS assignment versions, branch evidence, value-versus-row effects and cycle/limit boundaries
survive each step. Multiple operation writers stop upstream chaining with an ambiguity
marker. Sources are loaded lazily and snippets/expressions are capped at 12,000 characters.
Parsing errors for previously analyzed sources abort refresh and retain committed facts.
See [column transformation coverage and query semantics](TRANSFORMATION_LINEAGE.md).

Identifiers preserve display spelling. Lookup defaults to case-insensitive canonical names;
case-sensitive matching can be configured. An unqualified reference links only when exactly
one qualified candidate exists; that link is inferred, with an alias record and lower confidence.
Ambiguity is a diagnostic and remains a separate node. CSV linking requires an explicit path.

`LineageGraph` groups parallel evidence on a directed NetworkX graph. Breadth-first traversal
has depth/node budgets. Strongly connected components report cycles without enumerating every
cycle. Temporary contraction combines evidence and intermediate names with a fanout budget.
Endpoints and self-cyclic temporary nodes are retained to avoid losing information.

`path_report` traverses the selected full/simplified graph with a bounded pending queue
(1–500 paths, 1–30 edges deep). Results mark root/terminal/depth/cycle boundaries and global
truncation; they do not pretend a depth cutoff is a true root. Ordered steps retain immutable
source hash, statement/file IDs, original line ranges and intermediate evidence references.
CSV flattens paths/steps/evidence; JSON retains the path hierarchy. Full source bodies are
not duplicated for every path. `root_paths` remains available for existing callers.

`ui.lineage_tree.render_tree` tracks native expander state and renders only open branches
in the active direction tab. Expand/collapse controls change a widget generation counter;
only control state, never a rendered tree or source content, lives in session state.

## Explicit AI builds

`analysis_service` stages immutable context, original-unit AI extraction, deterministic validation and operation-based reconciliation before publication. The `parser` path retains `services.analyze`; `hybrid` adds validated AI support to parser facts, while experimental `ai` excludes unmatched parser SQL/SAS facts. CSV metadata remains local. Accepted project operations use explicit sparse table pairs, avoiding an input × output cross-product. Shared original operation evidence keys deduplicate corroboration and preserve distinct statements/writers.

Atomic publication checks the source/context manifest, relevant settings and prior committed revision. Failed, stale, incomplete or cancelled work retains committed facts. Saved accepted project facts can rehydrate offline if hash/config/job identity remains compatible. Unresolved graph/column evidence remains inspectable and stops confident traversal; an independent accepted parallel support may still supply a traversable relationship. See [AI project analysis](AI_ANALYSIS.md).
