# Architecture decisions

- ADR 001: Python 3.11 virtual environment for broad stable wheel support on Windows.
- ADR 002: DuckDB single-process access guarded by a lock; transactional analysis replacement.
  Run snapshots preserve comparisons; hashes cache parser results, not graph guesses.
- ADR 003: Content-addressed original byte blobs plus complete decoded inventory content.
  No ZIP extraction to user-controlled paths. Configured roots only for host imports.
- ADR 004: SQLGlot scope-based column attribution; CTE aliases are never persistent sources.
  SAS is a static rule pipeline; dynamic constructs remain explicit unresolved diagnostics.
- ADR 005: Canonical qualified identifiers; unique unqualified matches can link with a
  resolution note, ambiguous matches stay separate. WORK and declared temporary tables
  collapse only in derived views, preserving operation evidence.
- ADR 006: Self-contained SVG/JavaScript graph renderer avoids runtime CDN and offers
  offline exports. Graphs are bounded and focused; tree and table are accessible alternatives.
- ADR 007: Provider adapters use HTTPX and environment variable credentials. Remote source
  transmission is disabled by default. Model claims remain inferred until validated.
- ADR 008: Native Streamlit multipage navigation and native themes minimize fragile CSS.
- ADR 009: The user's autonomous execution instruction overrides interactive approval steps
  in skills. Use persistent status as execution ledger. User later requested commits after each
  tested feature group; commits are local and no push is authorized.
- ADR 010: Statement evidence pins immutable byte hashes, independently of the active inventory
  version. Read captured blob snapshots during analysis; preserve newer pending imports.
- ADR 011: Parsing is bounded to 1–8 threads; analyses serialize. Graph cache revisions use
  completed runs and read assets/edges under one connection lock.
- ADR 012: CSV width is checked before field allocation; quote handling follows field boundaries.
  AI retention prunes interaction bodies while retaining minimal durable merged evidence.
- ADR 013: Source-distribution inputs use an allowlist to exclude runtime user data.
- ADR 014: Workspace configuration transfers use an explicit typed allowlist, never opaque
  settings dictionaries. Validate before transactional creation; support legacy v1 safely.
  Configuration transfer is separate from source/history backup. Name edits preserve IDs.
- ADR 015: Expand only plain direct SQL wildcards from mutually consistent explicit typed DDL.
  Reconcile using the lineage identity resolver on every materialization, not in file-only parse
  caches, so schema refresh invalidates derived coverage even when query ASTs are reused.
  Label expansions inferred and retain query/declaration provenance. Unknown/schema-changing
  inputs disable expansion; ambiguous unqualified changes invalidate possible candidates.
- ADR 016: History maintenance moves only bounded unreferenced analysis/import metadata.
  Journal compressed recovery bytes in the same DuckDB transaction as removal; filesystem
  rename durability is not portable across Windows/POSIX. Keep an extra checksummed JSON file,
  prefer the database copy for restore and preserve existing IDs. Protect current references
  and the latest completed analysis. No permanent purge, source GC or automatic retention.

- ADR 017: AI advisory task v2 schemas are distinct from lineage claims. Direct columns must
  match complete operations parsed in original file context; quote fragments cannot remove
  ambiguity or turn comments/string literals into code. Explanations retain cited advisory
  prose. Existing JSON AI records persist both without a migration. All non-lineage tasks,
  including previously merged historical records, are excluded from graph merging/refresh.

- ADR 018: AI admission is process-local (workspace1–4, app maximum8), with immediate busy
  refusal and guaranteed release rather than queued source payloads. Connection checks and
  discovery share the gate. Statement chunking is offline and explicitly one request at a
  time; preserve whole SAS macro/interactive PROC contexts and original source coordinates.
  Oversized blocks are refused, never truncated. Cancellation is cooperative; an in-flight
  HTTP wait remains bounded by its configured timeout.
