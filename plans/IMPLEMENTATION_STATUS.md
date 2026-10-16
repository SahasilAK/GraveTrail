# DataForge implementation status

Updated: 2026-10-16. Authority: docs/prompts/MASTER_PROMPT.md (1,597 lines).

## Current delivery state

Maintenance/deployment enhancement is implemented and locally verified; plan:
MAINTENANCE_DEPLOYMENT_PLAN.md. Delivered previewed dependency-aware cleanup, session-only
runtime credentials, checksummed backup/new-home restore, packaged Python UI/CLI/MCP,
non-root persistent Docker deployment, host-native executable/release tooling and the
17-part docs/SETUP_AND_DEPLOYMENT.md guide. All destructive verification used isolated homes.
Remaining gates: native Linux/macOS executables, hosted release CI and reliable OmniRoute
completion availability. auto/best-reasoning has completed connection/SQL and a fresh SAS
inspection; its latest workflow attempt fails with gateway HTTP503 candidate exhaustion.

SAS PROC SQL FORMAT= parsing is fixed with exact source evidence and parser cache8.
The supplied SAS project now matches all128 logical edges (144 physical evidence edges),
including pub.all_kpis through seven layers to all16 sources. Reanalyze existing workspaces
to refresh cached results; packaged images/executables built earlier require rebuilding.

Additional Agent & Automation Access feature is implemented and locally verified:
standalone CLI, token-efficient MCP, managed jobs and human Settings integration.
See AGENT_INTEGRATION_PLAN.md and AGENT_ACCEPTANCE.md for the current feature evidence.

Six-page working local application. Planned implementation slices and the final audit fixes
are implemented, with conservative static-analysis boundaries. See REQUIREMENT_MATRIX.md for
section-by-section acceptance. External release acceptance remains open; no universal parser
accuracy or production deployment certification is claimed.

## Delivered capabilities

- Secure nested ZIP/browser-folder/allowed-root imports, SQL/SAS/CSV selection, immutable
  complete originals and decoded inventory, diagnostics, status counts and CSV/JSON exports.
- SQL AST lineage/direct columns, reachable CTEs/subqueries/unions, common DML/views, explicit
  dialect precedence, SQL Server SELECT INTO/#/## and Teradata volatile CTAS fixture coverage.
- Dedicated SAS DATA/PROC rules, exact original evidence, static macros/library maps,
  PROC SQL FORMAT=/LENGTH=/CALCULATED/DATETIME(), explicit file links and unresolved dynamic
  diagnostics. Configurable CSV sampled metadata.
- Conservative cross-file resolution, supplied temporary job/session IDs, persistent shared
  identities, mixed-lifetime unresolved reads, declared-schema wildcard evidence and provenance.
- Atomic/incremental analysis, selected refresh, run comparison, rollback/source-version safety,
  cycle-safe graphs, bounded progressive trees, temporary contraction and path evidence.
- Exact asset selection, upstream/downstream/combined exploration, tree/source panels,
  searchable original code, direct columns/grouping, offline HTML/JSON/CSV/ZIP downloads.
- Optional provider protocols/task routing, bounded focused/chunked AI requests, privacy gates,
  strict grounded validation/quarantine, inferred merges and separately cited advisory results.
- Portable safe workspace settings, naming/descriptions, explicit startup-allowed per-session
  storage selection, recoverable history/staging cleanup, database migrations1–4 and safe logs.
- Fourteen preserved themes, graph/source defaults, dashboard/dictionary/impact/code search;
  documented architecture, module knowledge, setup, extension guides, tests and coherent commits.

## Current verification

- Latest SAS parser suite:288 passed,1 existing Windows symlink-privilege skip in54.07s;
  Ruff passes. Earlier maintenance suite266 passed; locked dependencies and Compose
  configuration passed. Clean Windows wheel and sdist installs,
  actual Windows standalone and Linux Docker pass CLI/import/lineage, stdio MCP and rendered
  HTTP/WebSocket UI checks. Docker additionally verifies UID10001 and volume persistence.
  Those distribution artifacts precede parser8 and were not rebuilt for this parser fix.
- Actual isolated running UI verified settings, advisory reopening, cleanup/restore, storage
  switch/back, vendor import/analysis, exact selectors, graph evidence and tree/source panels.
  Primary home, imported source data and active theme/configuration were preserved.
- Final500-file labeled synthetic chain:501 assets/500 edges, import15.8705s, cold2.1065s,
  warm0.8708s, all500 cached, focused traversal0.0969ms. Fixture precision/recall/evidence1.0;
  these are synthetic measurements, not a real-client accuracy guarantee.

## External gates and intentional boundaries

- User now requests OmniRoute auto/best-reasoning, superseding literal auto. Discovery966
  advertises the requested route but not literal auto. Connection JSON and grounded SQL
  assistance/merge passed earlier. Fresh SAS response is valid fenced JSON and passes strict
  schema/source grounding unchanged. A full-workflow probe then fails at connection with
  HTTP503, Maximum combo retry limit reached:28 attempted candidates, pool787,
  terminalReason=max_attempts_exceeded. No preprocessing change is justified. Prior SAS schema
  failure was not reproduced. Stopped live calls; full merge-refresh-restart remains open.
  Use OMNIROUTE_API_KEY without persisting its value;
  no fixed-model fallback or weakened quarantine. New advisory schemas remain mock-verified.
- Docker daemon29.2.1 is now available. The actual Linux image build, non-root runtime,
  rendered UI, persisted volume and stdio MCP checks pass. No registry push or hosted CI run.
- Self-contained HTML export/JS/downloads are verified. Direct file-browser interaction remains
  unverified because this browser environment blocked file navigation. No server workaround claim.
- Windows file-symlink test skips without creation privilege. Runtime path protections remain.
- Dynamic SQL/full procedures, runtime SAS macros/name literals/ranges/arrays and execution
  ordering remain conservative unsupported cases with diagnostics. Supplied jobs scope genuine
  temporary assets; runtime sessions are not discovered. No invented wildcard/transitive columns.
- Local single-user process; cooperative cancellation cannot preempt a parser or blocked HTTP
  read. Dense/large real projects need their own labeled accuracy/performance acceptance.
- Optional: SVG/PNG exports, general assistant, transitive column transformation lineage,
  background scheduled retention and multi-user authentication. Whole-home backups/blob GC are delivered.

## Resume instructions

Read AGENTS.md, REQUIREMENT_MATRIX.md and the latest entry below. Parser cache version8;
retain migration4 recovery journals and original blobs. DATAFORGE_HOME defaults to .dataforge;
DATAFORGE_ALLOWED_ROOTS controls host imports; DATAFORGE_STORAGE_LOCATIONS names additional
absolute session storage choices (maximum8 total). No data migration occurs on selection.

Commands: uv sync --locked --extra dev; uv run pytest -q; uv run ruff check .;
uv run streamlit run app.py --server.address 127.0.0.1.
Commit each tested coherent group. Preserve user .gitignore/theme edits and the master prompt.
Next work is external acceptance (auto routing, native Linux/macOS, CI/offline browser) or a new demonstrated
project-specific parser case, not restarting completed implementation slices.

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

## Historical session entry point — superseded by current Resume instructions

Task-specific AI contracts, bounded resources, and remaining settings are now implemented.
Resume with explicit job/session identity, broader vendor fixtures and requirement-by-requirement acceptance accounting.
Keep new work in tested commits; preserve all fourteen themes and active configuration.
Current parser cache version7. Previously analyzed cache-incompatible files reparse on selected
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


## Completion execution: allowed storage selection — 2026-10-16

- Closed audited master Settings gap with an explicit startup-allowed storage dropdown:
  DATAFORGE_HOME plus absolute DATAFORGE_STORAGE_LOCATIONS, maximum8. Selection is per
  browser session. Open/validate target before resetting workspace/widget state; other
  sessions keep existing stores. Failed opens keep the current workspace. No file migration.
- Unit/AppTest proves bounded/no-side-effect choices, unauthorized-path refusal, two sessions,
  switch-back retaining original source and failed-open preservation. Review found no issues.
- Actual isolated UI verification and final full-suite results follow below. Primary home and
  theme configuration remain untouched. Next: final requirement matrix/package/runtime gates.
- Final storage verification:207 tests passed,1 skipped in23.15s; Ruff clean. Actual isolated
  UI opened alternate-ui (new My workspace), then returned to Completion verification with
  its 10.26MB database and history intact. Screenshot .dataforge/verification/storage-location.png.


## Completion execution: inventory and investigation UI — 2026-10-16

- Audited master gaps: configurable CSV sampling (0–100 retained rows, default25; zero leaves
  types unknown), explicit inventory successful/partial/failed/pending counts and extension
  breakdown. Safe setting round trips and participates in parser cache keys. Full originals
  and complete bounded row counting are unaffected by the sample limit.
- Builder now reruns after completed analysis with a durable success notice so inventory and
  counters show current statuses immediately. Explorer dependency tabs/tree occupy the left
  panel beside source evidence on the right; shared graph remains above both panels.
- Failing behavior tests preceded fixes; full209 tests passed,1 skipped in final result below.
  Actual isolated Settings saved sample5. Final UI proof and full timing follow below.
- Audit also identified SAS DATA/PROC blocks joining statement snippets with artificial newlines;
  next fix exact original block evidence before final packaging and acceptance accounting.
- Final UI refinement verification:209 tests passed,1 skipped in23.28s; Ruff clean; independent
  review found no regressions. Running Explorer shows tree and exact SELECT_INTO source side
  by side; screenshot .dataforge/verification/tree-source-panels.png.


## Completion execution: exact SAS evidence — 2026-10-16

- Corrected rule-block statement evidence: original contiguous source slices preserve spacing,
  comments, blank lines and same-line block boundaries. Line-anchored offsets prevent skipped
  inline data containing identical tokens from redirecting evidence. No input code executes.
- Parser7 invalidates reconstructed cached snippets. Regression tests cover DATA, PROC and
  inline-data offsets; advisory grounding and labeled fixtures remain compatible. Independent
  review found no evidence/line-range issue (38 focused tests pass). Final full result follows.
- Next: final clean source install, package/runtime checks and acceptance matrix. Docker engine
  is unavailable; literal OmniRoute auto connection failure remains an external blocker.
- Final SAS verification:212 tests passed,1 skipped in24.56s; Ruff clean.
- Running isolated UI imported/formatted SAS, analyzed4 files (10 assets/7 edges), immediately
  showed4 successful/0 pending and displayed exact DATA evidence lines1–3 including blank
  line/spacing. Screenshot .dataforge/verification/exact-sas-evidence.png.


## Completion execution: active direction evidence — 2026-10-16

- Final accounting review caught a mandatory source-panel mismatch: the dependency tabs
  changed the tree, while source files followed the independent graph direction. Base evidence
  now follows the active tree tab; explicit graph asset/relationship selection overrides it.
  Source scope is labeled. Tab changes reset graph selection, and initial tab follows the
  saved direction default. No source facts are modified.
- Regression uses different upstream/downstream files while graph stays upstream, then proves
  explicit graph selection still wins. Existing default-visualization tests remain green.
- Actual isolated UI selected downstream for #stage while graph remained upstream; the tree
  showed mart.orders and source evidence changed to INSERT lines3–4. Screenshot:
  .dataforge/verification/downstream-source-scope.png. Final full test result follows.
- Final source-direction verification:220 tests passed,1 skipped in25.21s; Ruff clean; reviewer
  cleared the fix after11 focused tests.


## Final local acceptance — 2026-10-16

- Section-by-section master accounting is in REQUIREMENT_MATRIX.md. Completed implementation
  is bounded static analysis; external release gates remain explicit rather than marked green.
- Main checkout220 passed/1 skipped in25.21s; clean Python3.11.16 source-distribution environment
  installed all52 locked packages offline and passed220/1 skipped in25.06s. Ruff clean in both,
  uv lock --check clean. Windows symlink-creation test is the privilege-related skip.
- Seven labeled vendor/SAS examples exercised in LF and CRLF. Fixed a test-only LF assumption
  after proving that original CRLF snippets were correctly preserved;14 fixture cases pass.
- Wheel/sdist rebuilt under .dataforge/verification/final-dist. Source allowlist excludes runtime
  homes/databases. Installed wheel with --no-deps --reinstall, then Python -I verified parser7,
  imported site-packages location and bundled column/explanation schemas. No hidden editable
  source dependency in that check. Clean installed-wheel server uses separate home/port8503.
- Actual clean browser imported delivered scenario directory:7 accepted,2 documentation files
  skipped;9 assets/7 dependencies,6 success/1 expected macro-warning partial,0 pending. Explorer
  selected mart.customer_summary, rendered collapsed tree and both SAS evidence statements.
  Restart reopened the same persisted workspace. Current primary8501 health also returned200.
- Final synthetic500-file benchmark:15.8705s import,2.1065s cold,0.8708s warm,500 cache hits,
  traversal0.0969ms, precision/recall/evidence1.0 for the labeled chain only.
- Docker runtime unavailable (Linux engine pipe absent); no remote CI run. Direct offline file
  browser interaction unverified. Latest OmniRoute auto retry failed during discovery; no local listener on20128.
  No substitution or weakened grounding. See LLM_LIVE_RESULTS.json.
- All code groups were independently reviewed, tested, UI-exercised and locally committed.
  Remaining work is external acceptance or newly demonstrated project-specific coverage.


## Final continuation handoff — 2026-10-16

- User resumed continuation. Retried only literal auto at configured endpoint with existing
  named environment credential. Checker failed ProviderError in4.15s during discovery, before
  connection/source assistance. Confirmed no local TCP listener on20128; credential present.
  LLM_LIVE_RESULTS.json records this latest failure. Earlier964-model discovery is historical.
- App processes had stopped between turns. Restarted primary8501 with same data home; health200.
  Before restart, preserved counts:1 workspace,7 source files,9 assets,7 edges,2 analysis runs;
  schema4. Current execution session88647 owns the Streamlit server. No theme/config change.
- Current80 application/test/fixture files hash-match the final clean tested source artifact;
  therefore220-pass main/clean results still apply. Ruff remains clean. Final installed-wheel
  UI also reopened persisted data and showed3 direct columns/3 references from02_summary.sql.
- Final report and module knowledge updated; remaining incomplete gate is live auto-provider
  validation after gateway availability is restored, plus documented Docker/remoteCI/offline
  browser verification. No additional product code changes are pending.


## Reference-style lineage trees — 2026-10-16

- User-requested redesign gives upstream/downstream tabs full-width compact indented trees.
  Bold asset labels, inline via-script paths, left chevrons, theme-aware branch guides and
  Expand all/Collapse all replace boxed per-node evidence summaries and depth-entry controls.
  The existing traversal-depth slider bounds Expand all; levels indicate distance, not execution.
- Relationship metadata is available through Show relationship details; source evidence and
  exports remain below the trees. Existing direction/source selection behavior is preserved.
  Native branch widgets remain lazy and cycle/depth/entry-bounded. Imported labels are escaped.
- Verification: full suite222 passed/1 existing skipped in26.51s; Ruff clean. After final styling,
  four focused tree/source-scope tests pass. Actual isolated app on8504 exercised upstream and
  downstream, Expand all/Collapse all and descendant disappearance. Screenshot:
  .dataforge/verification/lineage-tree-redesign.png. Synthetic data stays in separate verification
  home; primary data/theme/master prompt untouched. Scoped CSS relies on Streamlit expander DOM.


## Missing asset metadata recovery — 2026-10-16

- Reproduced user KeyError(name): NetworkX implicitly creates attribute-less endpoints when
  relationships reference assets absent from the loaded asset list. Graph construction now
  retains those edges as unresolved diagnostics, excludes anonymous nodes and propagates
  incomplete state through focused/simplified/path views. Shared UI displays a rebuild warning.
- Deeper live cause: DuckDB1.5.6 optimized workspace WHERE queries returned zero rows despite
  matching rows existing. Disabling the optimizer returned7 files/9 assets/7 edges. ANALYZE and
  disabling index scans did not repair the discrepancy. Cause of the bad optimizer metadata
  is unknown; no dependency or global optimization settings were changed.
- Stopped the app for safe backup, exported all tables with optimization disabled, imported
  into a fresh database and verified every row of every table exactly against the backup.
  Normal optimized workspace queries then returned7/9/7. Installed the repaired database and
  restarted8501. Originals/blobs untouched. Recovery backup:
  .dataforge/verification/before-query-metadata-repair.duckdb; export/repaired copy retained.
- Automated:223 passed/1 existing skip in27.19s, plus added explorer missing-asset integration
  regression (2 explorer tests pass);8 graph/tree/source tests pass and Ruff clean.

- Final browser recovery verification: restarted8501 after session interruption; all9 asset choices
  present. Selected mart.customer_summary, expanded upstream through staging.customers to the
  CSV source, and verified graph/table/SAS original evidence render without exceptions. Screenshot:
  .dataforge/verification/lineage-recovery.png. App remains running. User tests/sample_data is untouched.


## Agent & Automation Access — 2026-10-16

- Delivered three vertical slices: shared automation services/CLI, official-SDK MCP/security,
  and Streamlit settings/documentation. Human UI and extraction logic remain intact. CLI/MCP
  delegate to existing Store, Importer, analyze, column_report, LineageGraph and exports.
- Typer console command supports workspaces/import/cached build/lineage/columns/evidence/
  code search/issues/impact/batch/jobs/exports; human/JSON/quiet/file output and meaningful
  errors. Read-only startup default; explicit writes/allowed roots/workspace scoping.
- MCP offers 16 typed async tools, resources and workflow prompt; stdio and authenticated
  Streamable HTTP. Successful responses carry one structured payload. Summary/standard/
  detailed disclosure, bounded pages/cursors/depth/items/chars and source-permission gates.
- Jobs persist atomic journals/results and independent heartbeats; crashes report interrupted.
  CLI detached workers survive the launching CLI and retry brief storage-ownership races.
  Journal polling remains responsive during importer transactions and honors UI revocation
  snapshots/output caps. Mutation auditing excludes arguments, credentials and code.
- Settings → Agent & Automation Access provides permissions/source/budget/read-audit controls,
  verified Codex/Claude configuration examples and actual local MCP handler test. CLI_GUIDE,
  MCP_INTEGRATION, AGENT_WORKFLOWS and TOKEN_OPTIMIZATION document the complete workflows.
- Fresh full suite:242 passed/1 existing skipped in43.81s;18 focused agent tests pass. Ruff,
  locked dependency validation, wheel/sdist builds and isolated installed-wheel CLI/MCP
  imports pass with Streamlit absent from sys.modules. Running isolated8505 Settings test
  succeeded on SQL fixture (86 files/92 registry assets/128 edges). Primary data/theme intact.
- Independent review's import progress, standard-expression disclosure, CLI polling and
  MCP responsiveness findings were reproduced and corrected. The actual SDK stdio and
  authenticated/unauthorized HTTP paths pass; no external LLM invocation was needed.
- Both supplied ZIPs imported with only their script extension. SQL matches all128 expected
  logical edges and traces pub.all_kpis through seven layers to all16 sources. SAS preserves
  16 WORK assets/48 physical32 collapsed edges but existing FORMAT= PROC SQL limitations
  leave96 missing logical edges and final published asset absent;68 diagnostics, no guesses.
  Both warm refreshes reuse86 caches. Static source only; no SQL/SAS execution claims.
- Measured10-row summary/detail payloads:SQL1509/64841 chars, supported SAS staging649/3529;
  approx97.7%/81.6% reduction, character/4 estimates only. Raw results in verification home.
- Explicit boundaries:one DuckDB owner per home; private bearer auth (no OAuth issuance),
  external TLS reverse proxy required; remote deployment/client configuration changes not
  performed. Optional REST omitted. Existing OmniRoute/Docker external gates remain unchanged.


## Maintenance, secure configuration and deployment — 2026-10-16

- Source inventory, lineage/columns, AI results, eligible history/jobs, reset/deletion, shared
  parser/data caches, orphan blobs and recognized application reset use service previews,
  dependency counts, logical size estimates, freshness tokens and typed confirmation. Optional
  full-home backup is selected by default in UI. Running/queued jobs and provider activity
  block cleanup; new provider requests are refused until maintenance releases the home.
- Database commits precede controlled file removal: interruption leaves safe unreferenced
  files reported for retry. Shared blobs, retained snapshots/history and other workspaces
  are protected. Full reset preserves backups, unknown files, schema, code and repository docs.
  Source cleanup invalidates the workspace graph/history; clear shared parser cache and
  orphan blobs separately when removing unreferenced source-derived copies.
- Integrity/schema/reference/blob checks, checkpoint, Windows-safe COPY FROM DATABASE
  snapshot backup and bounded SHA-256 restore to a NEW home. Unsafe archive paths, redirected
  runtime paths, hardlinks, stale previews and incomplete backups are refused. Backups are
  capped at512MB/50,000 files. Larger homes need an offline backup. No raw SQL/drop control.
- Masked runtime credentials stay session/context-local; no global environment mutation or
  persistent credential values. Explicit legacy environment references remain read-only.
  Adapter responses/logs scrub known credentials, including escaped JSON and arbitrary
  explicitly referenced environment names. Request admission spans source reads through
  persistence. Originals remain exact evidence and can contain user-authored source secrets.
- CLI workspace cleanup requires existing write policy, saved preview and typed name;
  restricted policies cannot make full-home backups. MCP adds read-only inspect/preview only.
  UI offers opt-in recoverable expired staging cleanup on page visits; no background scheduler.
- Installable UI/assets, shared OS data-home defaults, non-root locked Docker and owner-aware
  Compose; Python/native/Docker build targets, manifests/checksums, clean host PyInstaller
  bundles and tagged/manual Windows/Linux/macOS artifact CI without publishing/signing.
- Tests:266 passed/1 existing privilege skip in82.39s; Ruff, lock and Compose validation pass. Actual
  clean wheel AND sdist installations outside checkout, Windows executable, and Linux image
  pass import/lineage, stdio MCP and rendered UI; Docker verifies persistent volume/UID10001.
  Artifacts:dist/release (four manifest entries, ~115MB standalone ZIP). Build environments
  exclude inherited provider credentials; real wheel/sdist canary tests exclude secrets/DBs.
- Running isolated8511 UI displays SQL fixture86 files/92 assets/128 edges and calculated
  cleanup metrics. AppTest exercises backup/typed cleanup/rebuild and session credential
  connect/clear. Primary runtime data, source ZIPs, theme and .gitignore were preserved.
- Both supplied ZIPs rerun:SQL128 exact logical edges, seven layers/all16 roots; SAS existing
  FORMAT= limitations remain48 physical/32 collapsed edges,16 WORK assets and68 diagnostics.
  Warm cache86 scripts each.500-file benchmark:501 assets/500 edges, import17.6621s,
  cold2.4974s, warm0.89s, all500 cached, focused traversal0.0931ms; synthetic fixture only.
- Professional setup guide has all17 sections and55 verified local documentation links;
  README, AGENTS, architecture/security/implementation and affected knowledge maps updated.
- Remaining: hosted Actions and native Linux/macOS binaries unexecuted; unsigned bundles
  (no installers/notarization); backup limits above; local trusted-user UI without multi-user
  auth. OmniRoute auto attempt:discovery964 models, completion ProviderError after11.59s;
  no fixed route substituted. Python protocol mocks cover provider behavior.
- Independent review findings were reproduced before fixes:post-HTTP persistence race,
  JSON-escaped credential leak, arbitrary environment-reference leak, incomplete restore,
  and scoped whole-home backup authorization. Their focused regressions now pass.
- Final reset safety regression preserves theme assets when a data home overlaps a checkout
  and ignores non-UUID job filenames; twelve focused cleanup tests pass. No code/schema/docs
  directory is recursively removed by application reset.

## SAS PROC SQL FORMAT parsing — 2026-10-16

- Added an instance-local SQLGlot adapter for SELECT FORMAT= modifiers (named numeric,
  character, custom and width/precision forms), before/after aliases, literal LENGTH=,
  CALCULATED aliases and zero-argument SAS DATETIME(). No imported source is executed.
- Exact original statement/file/line evidence remains unchanged. Format names and derived
  aliases never become direct source columns. Malformed formats are diagnosed; missing or
  duplicate CALCULATED aliases remain unresolved. Configured dialect projection behavior
  is preserved, including T-SQL alias=expression. Ordinary SQL parsing remains unchanged.
- Parser cache8 reparses older cached results during analysis; regression proves parser7
  failed parses are replaced. Existing workspaces need Analyze all files without reimport.
  Current materialized results are preserved until analysis; no primary home was modified.
- Real supplied SAS ZIP:86 scripts,85 persistent assets plus16 WORK assets,144 physical
  evidence edges/128 collapsed logical edges exactly matching the manifest; pub.all_kpis
  reaches all16 sources across seven layers. SQL fixture remains128 exact edges/all16 roots.
  Both warm analyses reuse86 caches. SAS retains31 diagnostics:8 setup macro warnings,
  7 informational LIBNAME notices and16 inline-data notices; no parse errors remain.
- Verified isolated running8512 UI:101 SAS assets/144 dependencies, full-depth graph includes
  all16 src tables, pub.all_kpis exact selector and original Lines7–21 FORMAT=/DATETIME()
  source evidence. Screenshot:.dataforge/verification/sas-format-ui.png. Source ZIPs untouched.
- Final pytest:288 passed/1 existing Windows privilege skip in54.07s; Ruff and diff check pass.
  62 focused parser/settings tests pass. Reviewer findings (T-SQL alias semantics and keyword
  CALCULATED aliases) were reproduced before fixes and covered by new regressions.
- scripts/verify_agents.py now asserts exact edges/all-source traversal for BOTH fixtures.
  README, SAS guide, workflow/token evidence, acceptance and affected knowledge maps updated.
  Latest measurements:.dataforge/verification/sas-format-final.json; no LLM calls required.
- Remaining deployment gates above are unchanged. Existing wheel/executable/Docker artifacts
  were not rebuilt for this source parser fix; rebuild them to include parser8.

## OmniRoute best-reasoning diagnosis — 2026-10-16

- User explicitly switched the authorized test model from auto to auto/best-reasoning and
  requested stopping if repeated issues arise. Updated live-check default, guidance and setup
  documentation; endpoint remains http://localhost:20128/v1 with named OMNIROUTE_API_KEY.
- Discovery returns966 models and advertises auto/best-reasoning, not literal auto. The new
  route successfully returns connection JSON and a grounded SQL claim; inferred merge passes.
  This demonstrates working completion for those requests, not the cause of old auto failures.
- Existing synthetic live checker stops after SAS schema ValidationError (usage present),
  total94.03s. One additional isolated synthetic SAS call returns ProviderError; no usage or
  response is available for schema diagnosis. No additional live requests were attempted.
- Full live SQL/SAS merge-refresh-restart gate remains open. Preserved validation/quarantine,
  did not change prompts, substitute fixed routes, or modify existing user profiles/projects.
  Safe report:plans/LLM_LIVE_RESULTS.json; no source/headers/credential values/raw responses.
- Local verification:44 focused LLM/credential/advisory tests pass in6.16s, Ruff and script
  help pass. Previous full suite288 passed/1 privilege skip; no application logic/UI changed.
- Stopped network diagnosis per user request after repeated SAS failures. Further live tests
  need renewed user direction; no retry loops, scheduled checks or gateway changes were made.

## OmniRoute output inspection — 2026-10-16

- User renewed bounded diagnosis and requested inspecting actual output before choosing any
  preprocessing. One fresh synthetic SAS call returned HTTP200/finish_reason=stop in13.13s:
  fenced JSON containing a complete raw.b -> mart.y DATA claim, original lines1–3/quote,
  explanation and confidence. Existing fence processing, schema and grounding all validate it.
- The earlier SAS ValidationError was not reproduced; its original invalid response was not
  retained, so its exact failed field remains unknown. No guessed coercion/wrapper repair,
  prompt change or relaxed evidence checks were introduced.
- One original full-workflow probe then failed at connection after discovery966 in71.87s:
  HTTP503 service_unavailable, Maximum combo retry limit reached,28 attempted candidates,
  pool787, terminalReason=max_attempts_exceeded. This explains this ProviderError precisely:
  OmniRoute exhausted candidate attempts before usable completion output. Per-provider failure
  causes remain unknown. Output preprocessing cannot repair this gateway error.
- Kept auto/best-reasoning and named OMNIROUTE_API_KEY. Did not follow the gateway's suggestion
  to switch routes. Gateway/provider combo investigation remains external work; stopped further
  network requests under the user's bounded-troubleshooting instruction.
- Safe metadata:plans/LLM_LIVE_RESULTS.json. Redacted synthetic output/HTTP diagnostics only in
  ignored .dataforge/verification/omniroute-output-inspection.json and
  omniroute-workflow-outputs.json; no primary home, user profiles or application logic changed.
- Validation:44 focused LLM/credential/advisory tests pass in6.38s; Ruff passes. No additional
  preprocessing is supported by the captured response. Full live merge-refresh-restart gate
  remains open due intermittent gateway availability; docs/acceptance/knowledge updated.

## OmniRoute application retest — 2026-10-16

- User authorized the newly supplied key and renewed testing through the application.
  Restarted the stopped Streamlit server on8512 using the existing isolated
  .dataforge/verification/sas-format-fixtures home; primary user data was untouched.
- Saved an OmniRoute test profile pointing to http://localhost:20128/v1 with model
  auto/best-reasoning, timeout60s, retries0 and JSON output enabled. Registered the key
  through the UI's session-only runtime credential control; no credential value is stored
  in source, configuration, reports or databases. The runtime connection remains available
  in the current browser session and must be supplied again after restart.
- The UI's Test model connection passed (127 total tokens). SAS lineage assistance for
  02_extractions/017_customers_raw.sas, lines1–12, returned one validated CREATE claim:
  src.customers -> ext.customers_raw, exact quoted lines7–11 (2190 total tokens).
  Merge succeeded and refreshed lineage: “Merged 1 inferred relationships and refreshed
  lineage”. No ProviderError or schema validation failure occurred in these two requests.
- Proof: ignored .dataforge/verification/omniroute-app-success.png. Application code,
  prompts, parsing, output preprocessing and external gateway settings were unchanged.
  This bounded UI test passed; it does not establish long-term gateway availability.

## CLI and MCP parity planning — 2026-10-16

- Added CLI_MCP_UI_PARITY_PLAN.md at the user's request:46 coverage IDs across provider
  setup/runtime credentials, AI workflows, settings, workspace/configuration/history,
  visualization, reports, source/graph exports and maintenance. Nine ordered vertical
  slices specify shared modules, CLI/MCP interfaces, guards and verification gates.
- Explicitly retained AGENTS policy:shared cache/orphan/application cleanup is UI-only,
  MCP cleanup is read-only, secrets are never tool arguments or persisted, and agents
  cannot expand their own access. Discovery must report these restrictions honestly.
- This is documentation only; no new commands/tools are implemented and no live calls,
  data changes, credential changes or application configuration changes were performed.
  Implementation remains pending; existing test/build results above are unchanged.

## CLI/MCP parity execution — 2026-10-16

- Slice 1 foundation: versioned 46-ID paginated catalog (pending entries are explicit), independent config/network/application/admin startup grants, MCP refuses local-admin launches. Existing outputs preserved.
- RED: two new regressions failed for missing catalog/permissions. GREEN: 19 parity/agent CLI/service/MCP tests and agent Settings AppTest pass; Ruff clean. Running isolated8513 UI lists get_capabilities and actual local handler test succeeds.
- Slices2–9 remain pending. No primary home, source fixtures or master prompt changed.
- Ruling: work in the existing codex/agent-integration checkout requested by the user; no extra worktree or branch switch. Existing clean baseline preserved.

- Slice2: seven typed sections, schemas/defaults, atomic revision-checked patches, workspace identity/configuration CLI and actual MCP handlers. UI parsing/resources/visualization/privacy/agent access reuse validation.35 focused tests pass; running8513 resource Save succeeds. Widening external/full-source/history/access/budgets, disabling redaction/audit and enabling auto cleanup requires local administrator. No implicit analysis/network/cleanup.

- Slice2 full regression:296 passed/1 existing privilege skip in68.83s. Slice3 profiles/routing/reference bindings/models/test use independent config/network/origin/reference gates; MCP has no raw-secret input, CLI hidden per-operation prompt, per-workspace/profile RuntimeConnections cleared on close.35 focused provider/connection/LLM/UI tests pass; no process-environment mutation and DB canary absence verified. Provider/routing UI uses shared saves; running8513 offline profile form exercised. Live checks reserved for bounded final AI gate.

- Slice4 shared AI previews/review/request/result/activity/explicit idempotent merge plus CLI/MCP adapters implemented. Existing assist_task validates every fallback through launch origin/reference gates. Exact hash/job guards, source-gated detailed result reads, no secret job serialization.57 focused AI/LLM/advisory/queue/MCP tests pass; UI chunk/merge reuse shared helpers. Artifact advisory downloads and fixture-backed running-UI gate are tracked for slices6/9.
