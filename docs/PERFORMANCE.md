# Performance

Use `uv run python scripts/benchmark.py --files 500 --output plans/BENCHMARK_RESULTS.json`.
The committed JSON records environment versions, cold/warm import/analysis, focused traversal,
evidence coverage and labeled synthetic precision/recall. These metrics describe the generated
SQL-chain workload only; they are not a guarantee for arbitrary SQL/SAS projects.

Recorded Windows/Python 3.11.16 run (500 files, 501 assets, 500 edges): import 15.8705 s;
cold analysis 2.1065 s; cached refresh 0.8708 s with all 500 parses skipped; focused traversal
mean 0.0969 ms (21 nodes). Labeled synthetic precision/recall and evidence coverage were 100%.
Import time includes local immutable blob writes and transaction costs on this host.

Parser results cache by parser version, byte hash, relative path and parsing settings. Unchanged
parses are skipped, while facts are rebuilt transactionally to remove stale relationships.
1–8 configurable parsing workers bound parallel work. One analysis runs per Store at a time;
immutable snapshots allow concurrent import without changing the analysis input.

Database writes are batched. Workspace/file indexes support common filters. Graph caching uses
completed-run revision keys, a five-minute TTL and 32-entry cap. Source selectors fetch metadata
before lazily loading a selected file. Full raw inventory content is not copied into session state.
CSV metadata streams records and samples a configured0–100 rows (default25); it never loads a CSV DataFrame.

Defaults: 10,000 files, 20 MB/file, 100 MB compressed ZIP, 200 MB decompressed/import total,
200:1 ZIP entry ratio, 4,096 CSV columns and 1,000,000 characters/record (csv's field limit also
applies). Maximum graph display defaults to 150 nodes and 5 levels. Trees cap rendered nodes at
60 and nested depth at 8. Root paths cap returned and queued paths. Cycles use SCCs rather than
exponential simple-cycle enumeration. Temporary contraction has a 20,000-edge budget.

Parsing/exports and DuckDB rebuilds can still be expensive for very large scripts or dense graphs.
Analysis is synchronous in the local UI; callbacks support cooperative cancellation between
files, but do not preempt an individual parser. The Streamlit stop control interrupts a run.
Snapshot/parse-cache retention is manual; long-lived high-churn workspaces need storage monitoring.

## Column transformation measurement (2026-10-18)

Run `uv run python scripts/benchmark_transformations.py` to reproduce a disposable
synthetic fixture: 120 stages × 20 columns, each column reading two prior-stage columns,
plus the order-totals example. This Windows/Python 3.11 run stored 2,404 derivations;
analysis took **42.8948 s**. An upstream query at depth 30, limit 200 returned exactly
200 derivations/200 path-step records in **16.9428 s**, with **1,081,760 bytes** peak
Python allocations under tracemalloc and an explicit `item_limit` marker.
This parser-10 run predates the parser-11 identity/mapping corrections and overlapped
the full test suite and documentation build on the same host.
The allocator tracing excludes DuckDB/native/process memory and adds measurement overhead.
These are measured synthetic results, not a responsiveness guarantee for real projects.

Column references and input/target lookups are indexed by workspace and identity.
Queries bound derivations and scheduled/visited column/effect states, rather than
enumerating all possible dependency paths. Per-step inputs cap at the query limit;
source snippets and expression previews cap at 12,000 characters. UI queries cap at
200 derivations, while shared service/CLI/MCP limits permit up to 20,000 and depth 30.
Large selected limits can still be slow; agent response budgets apply separately.

## Automatic AI continuation qualification (2026-10-20)

`uv run --locked python scripts/benchmark_ai_analysis.py --scale-units 1000`
exercises simple synthetic SQL units through real adapter/mock HTTP, bounded
executions and durable store reopen. This Windows/Python 3.11 run used a Custom
100-attempt ceiling and automatic output/time allowances:

| Measurement | Observed |
| --- | ---: |
| Complete units processed | 1,000 |
| Explicit executions | 10 |
| Requests / unique requested units | 1,000 / 1,000 |
| Final publications | 1 |
| Largest unit checkpoint | 379 bytes |
| Peak traced Python allocations | 48,591,394 bytes (46.34 MiB) |
| Qualification elapsed time | 339.542 seconds |
| Live provider requests | 0 |

Every required unit was requested exactly once; no intermediate graph was published.
The harness enforces a 512 MiB traced-Python ceiling and 16 MiB per-record ceiling.
Tracing excludes DuckDB/native/process memory and adds overhead. Concurrent local
verification also used this host. These simple-unit lifecycle/storage measurements
do not qualify wide-query latency or live-model precision. Separate regressions
cover 100-column claims, compact canonical expansions above16MiB, aggregate file
snapshots above16MiB, partial outcomes and deadlines between extraction and review.
Progress journals omit per-unit preview lists and update only changed run fields;
completed continuation stages remain read-only. Static wire schemas are reused.

The semantic-paging/review-batch follow-up repeated this lifecycle qualification on
2026-10-20: **1,000 units, 10 executions,
1,000 unique requests, one final publication**, zero live calls.
Largest unit checkpoint: **727 bytes** including the
saved source partition specification. Peak traced Python allocations:
**53,952,971 bytes**; elapsed **485.127 seconds**
with tracing and the full test suite running concurrently. This is a bounded
lifecycle/storage check, not a speed comparison or live-model precision result;
native DuckDB/process memory is excluded. Separate real-adapter/mock HTTP checks
cover 36 wide-query outputs in one original writer and all 24 review candidates
across durable continuation without repeats.


## Resumable AI analysis

A 2026-10-21 synthetic mock-transport qualification processed 2,001 distinct units/physical requests across automatic windows in one Start with one publication: 171.007 seconds with tracemalloc, 60,722,523 peak Python bytes and 791 maximum unit-record bytes. This is local scheduling/storage evidence, not a provider latency or accuracy benchmark. Reproduce with `python scripts/benchmark_ai_analysis.py --scenario scale --units 2001 --files 7 --max-files-per-request 1 --max-parallel-requests 2 --output pipeline-scale.json`. The planner also has a 2,200-file/6,238-unit synthetic regression.


## Protocol 5 file extraction (2026-10-23)

New project builds use independent AI extraction from exact file parts, token-budgeted items envelopes, persisted file records, one frozen-context completion wave, bounded file consolidation and deterministic operation-graph publication. Static analysis and manual assistance remain independent. Older hybrid/review/window/project-resolution descriptions on this page are historical and do not define new project builds. See [AI analysis](AI_ANALYSIS.md) and [pipeline architecture](architecture/ai-analysis-pipeline.md).

Offline qualification uses nonempty independent SQL/SAS/dbt golden transport fixtures. The oracle scores table, column and file relationships separately and catches semantic omissions despite complete model JSON. Mock results do not establish live-model accuracy; live precision/recall and cost evaluation remain pending. Ordinary tests spend no provider credits.


Protocol-5 offline scale evidence (2026-10-23): SQL 1,002 files / 1,003 parts / 39 requests; SAS 1,002 / 1,003 / 38; dbt 1,002 / 1,003 / 42. All had full processed range coverage and exact deterministic golden table/column/file graphs after interruption/reopen. SQL/SAS retain duplicate-writer boundaries. These are mock transport checks, not live semantic accuracy. Peak measured Python allocations were approximately 106.5 / 57.4 / 97.2 MiB; elapsed times approximately 89 / 91 / 305 seconds with tracing enabled. Actual provider tokens/cost remain unknown.
