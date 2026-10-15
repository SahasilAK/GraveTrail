# DataForge implementation status

Updated: 2026-10-15. Authority: docs/prompts/MASTER_PROMPT.md (1,597 lines).

## Delivery state
Working six-page local application. All supported core workflows are implemented and tested.
This is conservative static analysis, not a SQL/SAS runtime or a universal language compiler.
The complete master specification is **not yet finished**. Stage completion in MASTER_PLAN
means the core was delivered; detailed remaining requirements are in CONTINUATION_PLAN.md.

## Implemented
- Foundation: Python 3.11+, Streamlit 1.66 navigation/light-dark themes, modular layers,
  safe structured logs, DuckDB migrations v1–v3, isolated persistent workspaces.
- Secure nested ZIP/browser-folder/allowed-root import, selected extensions, hashes, byte-exact
  originals, complete decoded inventory, encoding/binary/duplicate diagnostics, batch writes,
  path/symlink/size/count/ratio safeguards and import history.
- SQLGlot read/write ASTs, aliases, reachable CTEs/subqueries/unions, temporary targets,
  quoted component identities, direct column contexts, exact statement evidence and diagnostics.
- SAS DATA and common PROC rules, PROC SQL, explicit CSV/file links, WORK, static macros/library
  maps, unresolved dynamic warnings, inline-data exclusion; bounded CSV schema/sample/row metadata.
- Atomic analysis replacement, run snapshots/comparison, immutable source-hash evidence,
  conservative cross-file linking, operation memberships, incremental cache, 1-8 parsing workers,
  revision-cached graphs, cycle-safe traversal and evidence-preserving temporary contraction.
- Explorer exact asset choice, upstream/downstream trees, combined/path/depth/node controls,
  interactive edge/node evidence, source viewer/search/copy and original-version downloads.
- Direct columns with grouping/filtering/context and wildcard uncertainty; CSV/JSON/HTML reports.
- Provider profiles, env-only keys, discovery/manual models, task routing, same-host transient
  fallback, privacy/context/redaction gates, versioned prompts/schema/hash, grounded validation,
  quarantine, inferred merge and source-change invalidation. AI retention preserves merged claims.
- Offline embedded HTML graph, JSON, original ZIP bundles; dictionary, code search and impact tools.
- Lockfile, tested wheel/sdist, clean install, CI configuration, Docker definition, required guides
  and folder knowledge maps. Original user .gitignore edits are preserved separately.

## Verification evidence
- Latest continuation: 110 tests pass in the normal environment; Ruff and lock checks clean.
  The initial 62-test release also passed in a separately created clean Python 3.11 environment.
- uv lock --check passes; wheel installed without editable source and imported with Python -I;
  bundled prompt/schema assets verified. Sdist/wheel exclude local runtime data.
- Clean-environment Streamlit server launched at http://127.0.0.1:8501; health endpoint 200.
- Actual browser: host directory and ZIP upload/import; skip/duplicate reporting; analysis creates
  9 assets / 7 dependencies; exact search; graph edge selection retains both WORK-stage evidence
  statements; source inspection; three direct columns; successful HTML graph download.
- Workspace reopening tested after restart in integration tests and the browser server.
- Browser-detected JS newline escaping defect fixed with a JavaScript syntax regression test.
- Independent read-only review findings fixed with regression tests: unused/DML CTEs, macro
  conditions, name literals/DATALINES, quoted names, cross-statement AI claims, immutable concurrent
  imports, CSV width/header/quote bounds and AI retention. See docs/REVIEW.md.
- Injected post-write failure proves transactional rollback and failed-run tracking.
- Labeled 500-file SQL chain: import 12.532 s, cold analysis 1.9221 s, warm refresh 0.6712 s,
  500 unchanged parses skipped; focused traversal mean 0.0849 ms. Fixture precision/recall and
  evidence coverage 100%. These are synthetic workload results, not general-language claims.

## Explicit limitations and unverified integrations
- OmniRoute at localhost:20128/v1 is reachable. Live discovery, connection (also through the
  actual Settings UI) and grounded SQL assistance passed. The initial complete SQL/SAS check
  failed before merge/restart; see LLM_LIVE_RESULTS.json. A separate SAS request validated,
  but the repeated full check rejected a non-JSON SQL response from the automatic model route.
  The adapter works; live model output is not consistently compliant. Other providers retain
  mock-backed verification only. Subscription sign-in is
  not repurposed. Databricks Genie remains a distinct unsupported query-agent integration.
- HTML downloaded and checked for embedded assets/no CDN and valid JS. Browser policy rejected
  file: navigation, so opening the independent local file is not browser-tested. No workaround
  browser/server was used to bypass that policy.
- Docker and remote CI matrix are configured but were not executed here.
- Dynamic SQL/procedures, runtime SAS macros, arbitrary name literals, ranges/arrays and full
  SAS variable compilation remain unsupported or conservative. See SQL_PARSING/SAS_PARSING docs.
- Temporary/WORK identities are workspace scoped. Runtime sessions and repeated-write execution
  order cannot be inferred. Separate unrelated jobs into different workspaces.
- Unknown wildcards do not invent columns. Resource budgets bound large imports and graphs.
  Analysis is synchronous with cooperative between-file cancellation; parsers are not preempted.
- Local single-user/single-process use; no public authentication or shared multiprocess DuckDB.
- Imports are additive. Unreferenced analysis/import history can be archived and restored in
  bounded manual batches. Recovery copies and source blobs remain retained; source GC,
  permanent purge and complete portable workspace backup remain follow-ups.

## Continuation
Run: uv sync --locked --extra dev; uv run streamlit run app.py; uv run pytest -q;
uv run ruff check .; uv run python scripts/benchmark.py --files 500 --output plans/BENCHMARK_RESULTS.json.
Read AGENTS.md and affected KNOWLEDGE.md before changes. Parser cache version is 4; increment
for semantic extraction changes. Runtime defaults to ignored .dataforge/. Host roots default
to tests/fixtures and require explicit DATAFORGE_ALLOWED_ROOTS configuration for real jobs.
Keep future work in tested Conventional Commits, as requested. No push was requested.
Follow-up priorities: target-vendor fixtures, explicit job/session identity, richer schema
discovery, source/blob lifecycle, portable backups and auth if expanding beyond local use.

## Continuation execution — 2026-10-15

- Re-read all 1,597 master lines, guidance, status, implementation and existing Git changes.
  Preserved the user's `.gitignore` changes; did not recreate completed modules.
- Added bounded single-fence JSON acceptance, explicit nonstreaming compatible requests and
  controlled errors for malformed provider envelopes. Added repeatable synthetic live checker.
- Verification: 67 tests pass; Ruff clean. Actual Settings connection test shows "Model
  connection validated" against OmniRoute with usage tokens. No secret values in repo files.
- Windows user environment contains OMNIROUTE_API_KEY and OMNIROUTE_BASE_URL at the user's
  explicit request. Future test shells must inherit/inject those variables; do not print them.
- Isolated synthetic UI verification home: `.dataforge/verification/live-ui`, loopback port8502.
- Next: workspace name/description editing and safe validated configuration round trips,
  then progressive trees/path export. See CONTINUATION_PLAN.md for the outstanding backlog.
- Workspace editing/configuration slice: validated name/description updates preserve IDs,
  inventory and analysis. Versioned v2 transfers parsing, bounded resource and graph settings;
  v1 compatibility retained. Credentials/profiles/privacy gates/opaque settings excluded.
  Configuration creation is transactional; malformed input creates no partial workspace.
  Full suite: 78 tests pass; Ruff clean. Added AppTest save/invalid-name/sidebar coverage.
  Actual browser: renamed workspace/description, exported JSON, uploaded it and created a new
  workspace successfully. Screenshot: `.dataforge/verification/workspace-settings.png`.
- Next active slice: lazy tree branches, expand/collapse controls and bounded dependency-path
  exports. Full portable source/history bundles and cleanup remain pending.
- Explorer continuation completed: active-tab-only lazy branches, expand-to-depth/collapse,
  configurable initial expansion, depth/visible-entry/cycle bounds. Ordered path CSV/JSON
  retains intermediate evidence references and explicit root/terminal/depth/cycle markers.
  Graph/path reports distinguish truncation from true roots. 82 tests pass; Ruff clean.
  Actual browser exercised lazy branch, expand to five levels, collapse and JSON download.
  Downloaded JSON asserted five ordered steps, exact original hashes and statement references.
- Next: schema-backed direct-column expansion and data dictionary schema provenance. Unknown
  or conflicting schemas must keep wildcard uncertainty. Portable history/cleanup remains later.
- Schema continuation implemented: consistent explicit typed SQL DDL supplies inferred plain
  wildcard columns, with original query plus declaration evidence and a parsing toggle.
  Conflicting/schema-changing declarations, LIKE/inheritance/properties/modifiers and unknown
  schemas retain wildcard uncertainty. Schema changes re-materialize cached query results;
  direct references remain separate from transitive usage. Dictionary labels SQL DDL types.
  Cache version4. 100 tests pass; Ruff clean after independent review fixes. Actual browser
  showed three inferred columns and original DDL evidence; declaration types/provenance visible
  in dictionary. Screenshot: `.dataforge/verification/schema-columns.png`.
- Independent review reproduced unqualified schema invalidation, second-operand SWAP and deep
  provider JSON quarantine defects. Regression tests cover each; schema reconciliation now
  uses the lineage identity resolver, ambiguous changes invalidate possible candidates, SWAP/
  RENAME invalidates both operands, and JSON nesting failures become controlled errors.
- Repeated 500-file benchmark with schema processing: import11.8012s, cold1.9592s,
  warm0.6950s (500 cache hits), focused traversal0.0907ms. Fixture precision/recall/evidence100%.
  Evidence file: `.dataforge/verification/benchmark-v4.json`; synthetic results only.
- Additional live routes: fixed `dva/claude-sonnet-4-6` was listed but not callable;
  `auto/best-coding` connected but produced an invalid SQL response that was quarantined.
  No further gateway retries or full live-pass claim. Other providers remain unverified live.
- Recoverable history slice completed: eligibility preview, bounded archive/restore controls,
  active-reference/latest-completed protection and idle-analysis guard. Migration3 adds a
  compressed recovery journal committed in the same transaction as metadata removal, plus an
  extra checksummed local JSON file. Restore is workspace-bound, atomic and idempotent.
  Independent review found a cross-platform file-publication durability gap; the database
  journal removes that dependency. Missing-file/restart, migration preservation, size bounds
  and injected archive/restore failures are tested; no physical power-loss test was performed.
  110 tests pass; Ruff and lock checks clean. Actual Settings browser archived/restored three
  analysis records while imports referenced by active inventory stayed protected. Screenshot:
  `.dataforge/verification/history-recovery.png`. Recovery is retained; no source GC or disk
  shrink claim. Next: controlled temporary-file cleanup and remaining storage portability.
