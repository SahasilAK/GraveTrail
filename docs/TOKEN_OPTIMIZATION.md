# Token-efficient local analysis

GraveTrail resolves names and computes lineage with the local stored graph, rather
than asking an agent to load scripts and rebuild dependencies. Hash-based parsing
cache and persisted evidence are reused. Queries never reparse or call an LLM.

Summary responses expose stable asset IDs/names/kinds, temporary status, freshness,
unresolved counts and aggregate extraction status/confidence. Standard adds
relationship references and positions. Detailed explicitly adds original statement
text or column expressions. Metadata/code search returns file references only.
Use a dedicated evidence request for a relevant statement or small line range.

Successful MCP responses contain structured data once, without duplicating it in
a text content block. Defaults: 50 rows, 12,000 serialized Unicode characters,
15 traversal hops and 2,000 dependencies. Hard maxima: 500 rows, 100,000 characters,
30 hops and 20,000 dependencies, further restricted by workspace settings. These
are character budgets, not byte or guaranteed model-token counts. SDK framing/tool
schemas are outside application page budgets. Network requests also cap at 64 KB.

Continuation cursors pin query scope and the analyzed/input revision. A page that
hits a budget returns `next_cursor` and `complete=false`. Depth/item caps and stale
metadata also produce incomplete state. A single oversized record produces an
explicit budget error. Batches enforce aggregate item/character budgets and list
unprocessed assets. Graph computation rejects more than 20,000 assets/100,000
evidence edges; simplification preserves evidence and intermediate names.

## Representative measurements

Measured on the supplied archives with static analysis, 2026-10-16. Comparison uses
the same selected asset and 10-row page limit at a 100,000-character workspace cap.
Both fixtures use the final published asset after PROC SQL modifier support.

| Fixture / asset | Summary characters | Detailed characters | Approx. summary tokens | Approx. detailed tokens |
| --- | ---: | ---: | ---: | ---: |
| SQL / `pub.all_kpis` | 1,509 | 64,841 | 378 | 16,211 |
| SAS / `pub.all_kpis` | 1,509 | 45,454 | 378 | 11,364 |

Approximate tokens are `ceil(characters / 4)`, not a model-specific tokenizer or
billing claim. Summary reduced these payloads by about 97.7% and 96.7% respectively.
These intentionally evidence-heavy examples do not imply universal savings.
IDs/cursors contribute to output size, so future measurements may differ slightly.

`scripts/verify_agents.py` reproduces the measurement and compares logical edge
sets with each bundled manifest. Both match all 128 expected logical edges and reach
all 16 sources. Both warm analyses reuse all 86 script caches.
See [AGENT_WORKFLOWS.md](AGENT_WORKFLOWS.md) for fixture interpretation and limits.
