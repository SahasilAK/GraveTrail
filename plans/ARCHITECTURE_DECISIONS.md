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
  in skills. Use persistent status as execution ledger; no unsolicited commits or pushes.
