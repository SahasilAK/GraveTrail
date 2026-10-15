# Performance

Use `uv run python scripts/benchmark.py --files 500 --output plans/BENCHMARK_RESULTS.json`.
The committed JSON records environment versions, cold/warm import/analysis, focused traversal,
evidence coverage and labeled synthetic precision/recall. These metrics describe the generated
SQL-chain workload only; they are not a guarantee for arbitrary SQL/SAS projects.

Recorded Windows/Python 3.11.16 run (500 files, 501 assets, 500 edges): import 12.532 s;
cold analysis 1.9221 s; cached refresh 0.6712 s with all 500 parses skipped; focused traversal
mean 0.0849 ms (21 nodes). Labeled synthetic precision/recall and evidence coverage were 100%.
Import time includes local immutable blob writes and transaction costs on this host.

Parser results cache by parser version, byte hash, relative path and parsing settings. Unchanged
parses are skipped, while facts are rebuilt transactionally to remove stale relationships.
1–8 configurable parsing workers bound parallel work. One analysis runs per Store at a time;
immutable snapshots allow concurrent import without changing the analysis input.

Database writes are batched. Workspace/file indexes support common filters. Graph caching uses
completed-run revision keys, a five-minute TTL and 32-entry cap. Source selectors fetch metadata
before lazily loading a selected file. Full raw inventory content is not copied into session state.
CSV metadata streams records and samples only 25 rows; it never loads a CSV DataFrame.

Defaults: 10,000 files, 20 MB/file, 100 MB compressed ZIP, 200 MB decompressed/import total,
200:1 ZIP entry ratio, 4,096 CSV columns and 1,000,000 characters/record (csv's field limit also
applies). Maximum graph display defaults to 150 nodes and 5 levels. Trees cap rendered nodes at
60 and nested depth at 8. Root paths cap returned and queued paths. Cycles use SCCs rather than
exponential simple-cycle enumeration. Temporary contraction has a 20,000-edge budget.

Parsing/exports and DuckDB rebuilds can still be expensive for very large scripts or dense graphs.
Analysis is synchronous in the local UI; callbacks support cooperative cancellation between
files, but do not preempt an individual parser. The Streamlit stop control interrupts a run.
Snapshot/parse-cache retention is manual; long-lived high-churn workspaces need storage monitoring.
