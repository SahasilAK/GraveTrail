# Testing

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
