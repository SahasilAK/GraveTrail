# DataForge implementation status

Updated: 2026-10-16. Authority: docs/prompts/MASTER_PROMPT.md (1,597 lines).

## Delivery state
Working six-page local application. All supported core workflows are implemented and tested.
This is conservative static analysis, not a SQL/SAS runtime or a universal language compiler.
The complete master specification is **not yet finished**. Stage completion in MASTER_PLAN
means the core was delivered; detailed remaining requirements are in CONTINUATION_PLAN.md.

## Implemented
- Foundation: Python 3.11+, Streamlit 1.66 navigation/light-dark themes, modular layers,
  safe structured logs, DuckDB migrations v1–v4, isolated persistent workspaces.
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
- Latest continuation: 127 tests pass in normal and separate clean Python 3.11 environments;
  Ruff and lock checks clean. Wheel and source distribution rebuilt successfully.
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
  A continuation Docker probe found the CLI installed but the Docker Desktop Linux engine
  unavailable (named pipe absent); container build/run remains unverified.
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
Read AGENTS.md and affected KNOWLEDGE.md before changes. Parser cache version is 6; increment
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
- Visualization defaults completed: typed workspace direction/temporary collapse, compact/
  full/hidden labels, semantic/neutral node palettes, edge width, source expansion and line
  numbers. Live graph and offline HTML/JSON share appearance; safe configuration includes it.
  Actual browser saved and reopened preferences after server restart; six exact accessible
  names remained with hidden labels, neutral fills and 4px edges. Node evidence and matching
  downloaded JSON passed. Full names use rendered SVG measurement to fit wider nodes.
  Fixed stale asset/source selectors on workspace/filter changes and ShadowRoot styling;
  added regressions. Independent reviewer reported no material remaining findings. 120 tests
  pass in normal and clean environments; Ruff, lock and wheel/sdist build pass. No new migration.
  Actual full-label graph and selected original evidence captured in
  `.dataforge/verification/visualization-defaults.png`.
- Unresolved review queue completed: up to 100 current SQL/SAS warning/error items, focused
  deterministic statement or bounded nearby context, adjustable preview and explicit routed
  request. CSV/info/pending sources are excluded. Preview hash pins through fallback/request
  capture; stale UI clicks and imports after queue lookup cannot transmit changed code unseen.
  Existing privacy/redaction/budgets/grounding/quarantine remain enforced. Separate merge stays
  inferred and does not mark parser diagnostics resolved. Shared durable result presentation
  holds record IDs in session state, including manual assistance. No new database migration.
  127 tests pass in normal and clean environments; Ruff/lock/build pass. Independent review
  found no material issues. Actual browser ZIP import/analysis and 1↔2-line preview passed;
  screenshot `.dataforge/verification/unresolved-review.png`. Request/quarantine/merge tests
  use synthetic HTTP, with no new live-pass claim or additional gateway requests.
  Rebuilt wheel installed into the clean environment; Python -I imported new queue/maintenance
  modules and validated bundled prompts independently of editable repository source.

## Next session entry point

Task-specific AI contracts, bounded resources, and remaining settings are now implemented.
Resume with explicit job/session identity, broader vendor fixtures and requirement-by-requirement acceptance accounting.
Keep new work in tested commits; preserve all fourteen themes and active configuration.
Current parser cache version6. Previously analyzed cache-incompatible files reparse on selected
refresh to retain coherent facts. OmniRoute tests must use model auto; its latest connection
check failed and discovery did not advertise that literal ID. Do not substitute fixed models
or repeat inference without new evidence. Docker/remote CI and independent local HTML remain
unverified; clean installation/packaging must be rerun after these new slices.

## Final runtime and packaging handoff — 2026-10-15

- Feature commits this resumption: `3d2aa54` history archive/recovery, `f2f51eb` visualization/
  source defaults, `4928e76` explicit diagnostic review queue. Earlier continuation commits
  remain in Git; no functionality was restarted and no push was requested.
- Normal application is running in a hidden background Python process on loopback
  `http://127.0.0.1:8501`, using the primary `.dataforge` home. Health endpoint returned 200;
  actual browser reopened the existing 7-file / 9-asset / 7-dependency workspace with its
  original analysis history. No verification fixture was imported into the primary home.
- Before startup/migration, primary application files/blobs were copied while stopped to
  `.dataforge/verification/primary-backup-20261015T134433Z`; the separate synthetic verification
  tree was excluded. The port8502 synthetic server was stopped. Verify current listener/process
  ownership before stopping or replacing a server in a future session.
- Background startup logs: `.dataforge/verification/app-8501.out.log` and `app-8501.err.log`.
  Credential values remain environment-only; the process inherited the named user variable.
- Built wheel contains new domain modules and bundled schemas; sdist contains new UI/tests.
  Archive contents exclude runtime/virtual-environment data. Installed wheel imports passed
  with Python -I in the clean environment. 127 tests passed in both environments; Ruff/lock
  checks clean. Docker CLI probe failed because its engine is unavailable; no container claim.
- Git is clean apart from the user's preexisting `.gitignore` edit, which remains uncommitted.

## User-requested theme options — 2026-10-15

- Added eight explicit native presets: Ocean, Forest, Amethyst and Graphite, each dark/light.
  Settings → Visualization → Theme preset → Apply theme. Dark choices set native dark base
  directly, including when the browser previously selected Light. Current config: Graphite dark.
- Presets update native app-wide deployment configuration, separate from workspace transfers.
  TOML-aware atomic replacement preserves server/browser settings, comments and layout/sidebar
  overrides. Added locked TOML Kit dependency to handle valid multiline/quoted TOML safely.
  Docker config directory ownership permits this operation as the existing nonroot app user;
  Docker remains unexecuted because the engine is unavailable.
- Native configuration watching is asynchronous; a bounded fragment waits for loaded values
  before success/rerun, with a refresh hint if startup overrides prevent convergence.
- Initial native paired-palette browser checks exposed appearance ambiguity and config reload
  lag, which led to explicit named mode choices and reload acknowledgement. The user then
  requested to validate the final dark appearances personally; no final browser inspection
  is claimed. Automated config, mode, contrast and AppTest checks cover the final behavior.
- Final automated result: 135 tests pass; Ruff and lock checks clean. Independent re-review
  found no material remaining findings. Final appearance validation is intentionally with
  the user; no additional browser interaction was performed after that request.
- The original master backlog remains unchanged by this focused theme request.

## Additive theme correction — 2026-10-15

- User clarified: preserve current themes and active appearance; add at most six choices.
  Appended Claude orange light/dark, Nord light, Rose light, Sand light and Mint light (14 total).
  Original eight names, colors and ordering remain byte-equivalent under canonical JSON;
  a frozen baseline hash regression protects them. No theme application logic was changed.
- No browser interaction or appearance validation was performed for this correction, as
  requested. The user will apply and validate. Existing active `.streamlit/config.toml` edits
  were not written by this task and are excluded from its commit.
- Verification: 136 tests passed; Ruff clean. All fourteen presets pass configuration
  round-trips and text/link/button contrast checks. Independent review found no issues.

## Running theme selector correction — 2026-10-15

- User screenshot showed the obsolete four-button selector despite the committed fourteen-
  option dropdown. The long-running server had not loaded the latest selector code.
- Restarted the verified app process on port 8501 from this checkout, retaining the primary
  DATAFORGE_HOME and named gateway environment variables. Active config SHA256 was identical
  before/after restart; no theme was applied or config written. Browser was not opened.
- Read-only live WebSocket session selected the Visualization section and confirmed the
  server emitted a selectbox with all fourteen exact names, including five dark choices.
  No Apply action was sent; the probe is ignored under .dataforge/verification/.
- AppTest now asserts the complete dropdown options/order, fourteen choices, and absence
  of the obsolete theme segmented control. User guide documents restart after stale upgrades.
- Verification: full suite 136 passed in 14.12s; Ruff clean. Live server emits all fourteen
  options. Appearance validation remains with the user; the restart did not change the theme.

## Completion execution: task-specific AI results — 2026-10-15

- Read supplied continuation request and complete master; existing code and themes preserved.
  Detailed remaining work is tracked in COMPLETION_PLAN.md.
- ColumnResponse/ExplanationResponse v2, generated schemas, task prompts and schema-inclusive
  prompt hashes replace shared lineage contracts for advisory tasks. Existing JSON AI records
  persist results without migration; saved results reopen offline without a provider profile.
- Columns must match complete original parser operations and explicit direct usage. Independent
  review exposed abbreviated JOIN/comment/string grounding bypasses and historical advisory
  merge restoration; all fixed with regressions. Non-lineage tasks cannot merge or restore edges.
- Shared UI shows AI-inferred column tables, cited advisory explanations, source-change warnings
  and JSON downloads. Saved source quotes/hashes remain separate from deterministic reports.
- Full153 tests passed in16.57s; Ruff clean. Actual isolated Streamlit Builder reopened a stored
  column result and displayed its inferred table/evidence controls. Synthetic HTTP results only;
  no new live-provider claim. Final request-result rerun adjustment receives final suite below.
- Next: bounded AI concurrency and explicit statement chunk previews, then settings/cleanup.
- Final slice verification after review fixes: 155 tests passed in17.25s; Ruff clean. SAS
  original formatting and immediate result rerender are covered.

## Completion execution: AI resource controls — 2026-10-15

- Added portable validated workspace AI concurrency1–4 and chunk-size500–100000 character
  controls. App-wide maximum8 applies to assistance and provider connection/discovery checks.
  Busy requests refuse without transmission; capacity releases on errors. Cooperative cancel
  stops new requests/retries/response processing, not a currently blocked HTTP read.
- Offline statement chunk previews preserve original line coordinates, SQL quoted semicolons,
  SAS DATA/macros and interactive PROC through QUIT. Whole oversized units fail explicitly;
  selection is limited to50 chunks and each request requires an explicit user click. No batch
  transmission, source truncation or weakening of context/privacy/hash checks.
- Actual isolated Settings UI saved concurrency2/chunk1500; screenshot under
  .dataforge/verification/ai-resource-settings.png. AppTest selects chunk2 and proves only its
  exact source/range is sent; previews make no request. Review findings fixed with regressions.
- Live OmniRoute fixed discovered model cx/gpt-5.6-luna-low passed discovery, connection,
  SQL/SAS grounding, explicit inferred merges, refresh and reopened persistence in19.87s.
  Synthetic sources only; report plans/LLM_LIVE_RESULTS.json. Prior unreliable-route failures
  remain historical evidence, not adapter success. New advisory schemas remain HTTP-test backed.
- Restarted primary8501 and isolated8502 after previous processes ended. Startup enables native
  runOnSave so code updates load; config hash preserved and no theme was applied. Runtime data
  stays under the same primary home. Next: remaining settings then safe temporary cleanup.
- Final AI-resource slice verification:166 tests passed in18.75s; Ruff clean.
- User then requested holding OmniRoute calls while it starts, and specified that all future
  OmniRoute testing must use model auto. No further gateway request was made after the hold.
  AGENTS.md and live-check command default record this policy. Fixed-route success above is
  historical evidence obtained before the new instruction, not a current route recommendation.

## Completion execution: remaining settings — 2026-10-15

- Added validated extension SQL dialect overrides (.sql and SAS PROC SQL), with default →
  extension → longest folder precedence. Parser cache version5; SAS rules remain static.
- Saved graph confidence/inferred-visibility preferences filter evidence before temporary
  contraction, with cache keys including filters. Facts/diagnostics remain retained. Graph
  exports reflect the visible filtered view. Diagnostic visibility and Analyze-button reuse/
  reparse mode now persist and travel in safe workspace configuration.
- Persistent app-wide logging level uses reserved __application__ settings scope, excluded
  from workspace exports. Safe structured event fields and privacy behavior remain intact.
- Fixed settings forms losing subsequent edits after saved defaults changed: success notice
  and rerun establish current widget identities. Regression covers valid then invalid saves.
- Review exposed selected refresh dropping unselected facts after parser/config cache
  invalidation. Previously analyzed incompatible files now reparse before atomic replacement;
  new unselected pending files remain pending. Regression simulates v4 → v5 and dialect changes.
- OmniRoute restarted per user. Model auto live check failed at connection (ProviderError),
  before source assistance; discovery lists964 IDs and auto/... routes but no literal auto.
  No fixed-model substitution or repeated inference attempts. Latest report records failure;
  earlier fixed-route success predates the user's auto-only policy. Gateway hold is lifted.
- Next required slice: safe application-owned stale temporary-file cleanup, then explicit
  job/session identity, vendor fixtures and final acceptance accounting/packaging verification.
- Final settings verification:171 tests passed in22.71s; Ruff clean. Actual isolated Settings
  saved extension dialect and inferred-visibility preferences with immediate success; screenshot
  .dataforge/verification/parsing-preferences.png. Primary theme/configuration was untouched.

## Completion execution: recoverable temporary cleanup — 2026-10-15

- Migration4 adds temporary_recovery journal. Preview only current workspace UUID.tmp history
  staging files aged24h or more; no recursion, sources, database files, JSON recovery archives,
  arbitrary names or other workspaces. Limits100 files/25MB per batch,10000 entries per scan.
- Explicit selection and fresh identity checks; busy-analysis guard. Recovery bytes/checksum
  commit before unlink. Restore is bounded/integrity checked and atomically publishes without
  overwriting existing files. Recovery remains retained, so no total disk-shrink claim.
- Windows DirEntry.stat lacks inode/link information; actual lstat identity is used. Changed
  previews and journal/publication failures are tested. Symlink-creation test skipped because
  this Windows account lacks permission; production symlink/reparse checks remain enforced.
- Full178 tests passed,1 skipped in19.13s; Ruff clean. Wheel/sdist built. Review found no issues.
  Actual isolated Settings selected/cleaned/restored a66-byte staging fixture with success;
  screenshot .dataforge/verification/temporary-recovery.png. No primary files were cleaned.
- Stopped verified primary process for a consistent pre-migration backup under
  .dataforge/verification/schema4-backup-20261015T235733. Primary schema3→4 preserved1 workspace,
  7 source files,9 assets,7 edges and2 analysis runs. Restarted primary8501; config hash identical.
- Next: explicit supplied job/session identity for temporary assets, vendor fixtures and final
  requirement accounting/clean package/UI/benchmark checks. Auto-only live gateway check remains
  failed as recorded; no fixed-model substitution or relaxed validation.


## Completion execution: explicit job/session identity — 2026-10-16

- Portable default job/session ID and longest-folder-prefix assignments separate genuine
  temporary datasets across supplied jobs. Persistent tables remain workspace-global. No
  runtime ordering, execution boundaries or macro values are inferred. Default workspace
  identities remain compatible unless a global persistent identity would collide.
- Extracted conservative identity resolution into asset_identity.py. Same-job temporary and
  persistent writes retain separate concrete outputs; ambiguous reads remain unresolved,
  diagnostic-backed and ineligible for wildcard expansion. Qualified schema candidates respect
  job visibility. AI context/merge/refresh use source job and reject changed assignments.
- Exact asset selectors, tree/graph labels, JSON/CSV lineage, collapsed intermediate names and
  run comparisons expose job IDs. Existing snapshots without job IDs remain readable.
- Independent review reproduced four scope failures (default-ID collisions, foreign schema
  candidates, external persistent reads and hidden persistent outputs). Added failing tests
  before fixing each; focused job/schema checks pass. Final full-suite result follows below.
- Actual isolated Settings saved default daily and one/two folder mappings with immediate
  success. Primary workspace/settings/themes untouched. Screenshot: job-session-settings.png
  under .dataforge/verification. Next: target-vendor fixtures and final acceptance accounting.
- Final job/session verification:190 tests passed,1 skipped in21.58s; Ruff clean.


## Completion execution: labeled vendor coverage — 2026-10-16

- Added real source fixtures and hand-labeled expected dependency, temporary and direct-column
  sets for SQL Server, PostgreSQL, Snowflake, BigQuery, Teradata, Oracle and SAS procedures.
  Exact graph sets prove no missing/extra fixture edges; immutable original source evidence
  and incremental reuse are checked. No universal dialect/real-client accuracy claim.
- Initially failing fixtures exposed missing SELECT INTO writes, SQL Server lost #/## prefixes,
  missing Teradata parenthesized CTAS inputs and volatile lifetime. Corrected AST extraction;
  parser cache6 invalidates previous semantics. Review also caught INTO set-query roots and
  qualified global temporary flags; regression tests precede both fixes.
- Actual isolated UI imported two vendor files, applied folder dialect/job assignments and
  analyzed successfully:8 assets/6 dependencies including its existing one-file fixture.
  Primary source data/configuration unchanged. Full-suite verification follows below.
- Next: final requirement matrix, remaining storage-location configuration gap and clean
  install/package/benchmark checks; retain explicit external verification blockers.
- Final vendor verification:204 tests passed,1 skipped in21.82s; Ruff clean. Actual UI
  selected #stage [job: tsql], clicked SELECT_INTO edge and displayed exact lines1–2. Proof:
  .dataforge/verification/vendor-lineage.png.
