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

`scripts/verify_llm.py` is an explicit live test using synthetic SQL/SAS only. OmniRoute model
discovery, UI connection and separate grounded SQL/SAS responses have passed; automatic model
routes have also produced quarantined invalid output, so a full live check is not yet claimed
green. A listed fixed model was not callable. See plans/LLM_LIVE_RESULTS.json and the
implementation status rather than treating model-list membership as availability.
