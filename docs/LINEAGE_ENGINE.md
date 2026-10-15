# Lineage engine

`services.analyze` loads inventory metadata and a hash/config/path keyed parse cache. It parses
only changed input, then materializes a complete workspace graph in one transaction. A failed
materialization rolls back facts and leaves a failed run record; original source is unaffected.
Selected analysis reuses caches for unselected files; changed unselected files stay pending.

Operations have explicit input/output memberships. Asset-to-asset edges reference an operation,
statement, file and analysis run. `Store.edges` joins evidence code and exact line ranges.
Original bytes are available through `Store.original`; the UI shows original source separately
from extracted statement snippets. Step numbers are dependency ordering, not execution order.

Identifiers preserve display spelling. Lookup defaults to case-insensitive canonical names;
case-sensitive matching can be configured. An unqualified reference links only when exactly
one qualified candidate exists; that link is inferred, with an alias record and lower confidence.
Ambiguity is a diagnostic and remains a separate node. CSV linking requires an explicit path.

`LineageGraph` groups parallel evidence on a directed NetworkX graph. Breadth-first traversal
has depth/node budgets. Strongly connected components report cycles without enumerating every
cycle. Temporary contraction combines evidence and intermediate names with a fanout budget.
Endpoints and self-cyclic temporary nodes are retained to avoid losing information.
