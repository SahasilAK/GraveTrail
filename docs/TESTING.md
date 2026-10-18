# Testing

## Current acceptance summary — 2026-10-18

This table distinguishes delivered behavior, dated environment evidence and still-open gates.
Earlier numerical results below are historical; a later source change does not refresh a
previously tested distribution artifact. Optional local `plans/` records are not shipped or
published; this tracked summary is the public acceptance reference.

| Area | Latest evidence | Remaining gate |
| --- | --- | --- |
| Source application | Parser cache 10 adds SQL/SAS column derivations, migration 5, bounded shared queries and a dedicated UI; full source verification is recorded below | No claim of universal SQL/SAS coverage |
| SQL/SAS sample ZIPs | Each has 85 persistent tables, 128 logical edges, seven layers/all 16 roots; SAS adds 16 WORK assets/144 physical edges | Real client projects and large dense graphs need separate accuracy/performance acceptance |
| CLI/MCP | Complete documented interfaces and actual SDK transport/permission regressions; fixture parity includes original bytes, evidence and warm caches | One DuckDB process owns each home |
| OmniRoute | Bounded 2026-10-17 live discovery, connection, SQL/SAS validation, inferred merge, refresh and reopen passed with `auto/best-reasoning` | Historical gateway failures are superseded; future availability and other live providers are not established |
| Windows wheel/executable | 2026-10-18 parser-8 artifacts passed outside-checkout CLI/import/lineage, actual stdio MCP, health and rendered UI smoke | Rebuild and smoke artifacts containing parser 10 before release |
| Linux Docker | 2026-10-17 GraveTrail image passed non-root CLI/import/lineage/UI/MCP and volume persistence | 2026-10-18 fresh Docker checks were blocked by daemon availability; no parser-9 container result claimed |
| Native Linux/macOS and hosted release | Build/publish workflow implemented | Target-native downloaded-artifact and current hosted release acceptance remain unrecorded here |
| Standalone HTML | Self-contained assets, escaping, JavaScript checks and real UI download passed; 2026-10-18 source-generated `file://` graph with 501 nodes/500 edges passed fullscreen, keyboard copy and evidence checks without external requests | Current packaged artifacts were not rebuilt for the QOL changes |

Whole-home backup/restore and guarded blob cleanup are delivered features. Scheduled retention,
SVG/PNG export and multi-user collaboration remain optional. Bounded column transformations
are now implemented for the [documented SQL/SAS subset](TRANSFORMATION_LINEAGE.md).

Column transformation verification on 2026-10-18: **545 passed, 2 existing Windows
symlink permission skips** in 111.01 seconds; Ruff and the lock check pass. Strict Pages
validation passes all **37 public pages**, 8 assets, rendered local links/anchors and search.
New fixtures cover projection/role separation, constants, CTE/INSERT/UNION and unsupported
SQL boundaries; ordered SAS variables and function/option boundaries; job isolation;
schema-based inference; revision/settings changes; converging cycles and all output limits;
failed reanalysis; migration-4 restore/upgrade, cleanup and integrity. AppTest and a real
Chromium session verify the dedicated page, readable inspector, original expressions/lines,
coverage and export controls without browser errors. CLI, shared MCP handlers and the real
SDK stdio transport return matching scoped transformations and enforce source permissions.
Independent review findings have regression tests and no confirmed blockers remain.

An earlier run concurrent with the benchmark/docs build reached the existing 10-second
MCP startup deadline (544 passed, 1 timeout, 2 skips). Both transport checks passed alone,
then the complete suite passed with no concurrent benchmark/build. The
[synthetic column benchmark](PERFORMANCE.md#column-transformation-measurement-2026-10-18)
records measured time, Python allocation scope and explicit traversal limits. These checks
do not establish live SQL/SAS execution compatibility or refresh native release artifacts.

Initial parser-9 source verification on 2026-10-18: **402 passed, 1 existing Windows symlink
privilege skip** in 68.31 seconds. Ruff and the lock check pass. Fresh isolated SQL/SAS ZIP
acceptance through CLI/service/actual MCP preserves exact originals, expected logical/physical
edges, all seven layers/16 roots and 86 warm cache hits per project. The running isolated UI
rebuilt all three new fixtures, validated zero invalid evidence records, and displayed the
procedure upstream chain and original source on graph selection. No imported code or external
provider was executed. Release artifacts were not rebuilt for this source change.

The subsequent CodeQL ReDoS follow-up passes **411 tests, 1 existing skip** in 63.74 seconds.
Routine-header whitespace/comments now scan forward without an ambiguous repeated regex,
honoring each dialect's nested-comment rules. A subprocess regression with 100,000 spaces
after a comment exceeded its 10-second bound before the fix and passes afterward; ordinary
SQL evidence and CREATE/ALTER procedure guards are preserved. Fresh SQL/SAS ZIP parity and
the running isolated UI pass, including zero invalid evidence records for the padded SQL.
Parser cache version 9 is unchanged because the fix preserves intended parsing behavior.

Lineage/Columns QOL source verification on 2026-10-18: **441 passed, 2 Windows symlink
permission skips** in 72.42 seconds; Ruff passes. AppTest covers disconnected All beyond
focused caps, direction-specific evidence, exact focus beyond search limits, shared selection,
Back/Forward branching and Tree-tab/control restoration. Column tests preserve unknown schema
and wildcard coverage, distinguish unused from filtered-out names and accept comma terms.
An isolated real Chromium session passed All, fullscreen enter/exit, exact node copy,
double-click focus, Back/Forward, directional source files, individual/list/unused column
copy and comma filtering with no browser errors. A separate source-generated standalone graph
passed 501-node rendering and keyboard interactions without external requests. These checks
do not establish performance for every large/dense graph or refresh packaged-release evidence.

## Test commands and historical evidence

`uv run pytest -q` runs unit, integration, security and Streamlit AppTest checks. `uv run ruff
check .` checks lint/imports. Node.js, when installed, adds a JavaScript syntax check; the app
itself requires no Node runtime. Tests construct isolated temporary DuckDB homes and use real
source fixtures, not a hardcoded graph.

Required scenarios are covered: explicit CSV→SAS WORK→staging→SQL mart flow, ambiguous orders
names, CTE resolution, direct versus transitive columns, unresolved macros, cycles, no provider,
and malformed/hallucinated provider output. Tests also cover original bytes, restart, extension
filters, path traversal, ZIP symlinks/ratios, CSV width/header failure, rollback, concurrent import,
source-hash evidence, quoted names, unused CTEs, SAS inline data and retention of merged claims.

AppTest renders every page and exercises ambiguous choices, profile forms and settings sections.
Actual browser checks are separate because Python AppTest cannot execute custom graph JavaScript.
Browser testing found and fixed a JS string-escaping defect; a syntax regression now covers it.
Node also checks mounting an empty graph through a DocumentFragment-shaped container without
an element style property. Real-browser tests verify rendering and interactions separately.
Provider tests use HTTPX MockTransport with real protocol payload validation. They do not prove
live account permissions/model availability. Do not call them a live integration test.

The CI matrix is configured for Windows/Linux and Python 3.11/3.12. Only the current local
environment results are claimed until remote CI actually executes. Docker is optional and
unverified unless a container build/run is explicitly recorded in implementation status.

Continuation checks include safe fenced JSON and malformed/deep provider envelopes, transactional
v1/v2 configuration round trips, workspace editing, closed-tree rendering/expand/collapse,
bounded ordered path exports, schema conflict/change/refresh handling and declaration evidence.
AppTest exercises schema-expanded columns, DDL source viewing and dictionary provenance.
Actual browser tests also downloaded and checked five-step path JSON/CSV with original hashes.

`scripts/verify_llm.py` is an explicit live test using synthetic SQL/SAS only. The bounded
2026-10-17 OmniRoute gate passed discovery, connection, SQL/SAS grounded claims, explicit
inferred merges, refresh and owner reopen using `auto/best-reasoning` at
`http://localhost:20128/v1` with the existing `OMNIROUTE_API_KEY` reference. Earlier runs
recorded invalid output and gateway failures. A dated pass is not an availability guarantee;
model-list membership does not establish callability. See the current implementation status.

History tests cover archive/restore protection, v3 migration, bounded payloads, rollback and
database recovery after filename loss/restart. Visualization checks cover strict preferences,
safe configuration round trips, graph export parity, source expansion and workspace selection
resets. Actual browser verification saved preferences, restarted the server, checked hidden
labels with accessible full names, neutral fills and edge width, selected node evidence and
downloaded matching graph JSON. Both normal and clean Python 3.11 environments pass 120 tests.

Diagnostic review regressions cover SQL statement focus, bounded queue and SAS nearby context,
informational/CSV/pending exclusion, isolation, privacy, invalid-output quarantine, explicit
inferred merge and source changes after queue lookup. AppTest also presses a stale request
button after reimport/reanalysis and proves zero network calls; a fresh request then validates
and merges via synthetic HTTP transport. UI state holds a record ID. Actual browser uploaded
synthetic unresolved SQL, analyzed it and adjusted the focused line preview without provider use.
Latest complete result: 127 tests pass in both normal and clean Python 3.11 environments;
Ruff, lock checks and wheel/source builds pass.


Local completion records, when supplied, live in the ignored plans directory.
Regression tests cover task-specific advisory grounding, AI
admission/chunks, settings/cache preservation, recoverable staging cleanup, supplied job scope,
seven labeled vendor/SAS cases in LF and CRLF, storage isolation, inventory refresh and exact
SAS evidence. Historical test counts above describe earlier stages. A Windows wheel and Linux
Docker build/run passed in earlier local verification; artifacts have not been rebuilt for
every subsequent source change. Hosted release CI and native Linux/macOS executable acceptance
remain separate gates. Standalone offline HTML interaction through a file-browser URL remains
unexecuted. See [build verification](BUILD_AND_RELEASE.md) and current dated acceptance.


## Agent integration acceptance

Run the four `tests/test_agent_*.py` modules for standalone CLI/MCP parity, actual SDK
stdio/HTTP, permissions/budgets, persisted/background jobs, source boundaries and Settings
AppTest. Run `scripts/verify_agents.py` with an isolated --home and --output for both supplied
SQL/SAS ZIPs and representative token estimates. It executes no imported source and records
exact SAS FORMAT-modifier evidence and the remaining static-analysis diagnostics. Retain the generated report locally for review.

## CLI/MCP UI parity verification

Run `uv run pytest tests/test_parity_*.py` and the full `uv run pytest`. The keyed 46-ID fixture is checked against actual CLI help and MCP schemas; new network/mutation tools must reject a read-only launch. Provider mocks are repeatable and require no keys. `uv run python scripts/verify_parity.py --home NEW_ISOLATED_HOME --output NEW_REPORT.json` exercises both supplied ZIPs through CLI/service/actual MCP and owner reopen, including every original byte/hash, exact logical edges, seven layers/all16 roots and warm cache reuse. Never point destructive tests at an existing user home. Record running UI/live/transport evidence and unexecuted gates in the local report.
