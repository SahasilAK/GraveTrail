# Continuation plan — 2026-10-15

The original six implementation stages delivered the core workflow, not every detailed
master requirement. Preserve that implementation. The user's autonomous execution and
per-feature tested commits still apply; preserve the unrelated `.gitignore` edit.

## Current execution order

1. **Live OmniRoute compatibility and repeatable verification.** Use the user-provided
   loopback endpoint and an environment variable credential. Discovery works. A live model
   returned fenced JSON despite JSON mode. Accept exactly one optional JSON code fence,
   retain strict schema/evidence validation, and reject surrounding prose or malformed data.
   Verify connection, grounded SQL/SAS assistance, merge, and persistence with synthetic
   sources only. Record model and outcomes, never the credential. Commit after tests.
   Compatibility and checker implemented; 67 tests/Ruff pass, live Settings connection and
   separate SQL/SAS grounding pass. Full run remains red because `auto/best-fast` sometimes
   returns non-JSON; retain quarantine. Pin a reliable configured model before re-running.
2. **Workspace editing and configuration portability.** Reuse existing workspaces/settings.
   Add validated name/description editing; export/import all supported safe configuration
   with one validated schema and transactional creation. Do not import network endpoints,
   credentials, source-transmission permissions, or opaque arbitrary settings. Keep v1
   configuration compatibility. Exercise through Settings and commit after tests.
   Implemented validated identity editing and safe v1/v2 round trips including resource/graph
   settings. 78 tests and Ruff pass; actual browser rename/export/upload/import passed.
3. **Progressive lineage trees and dependency-path exports.** Render only open branches,
   provide expand-to-depth/collapse controls, keep cycle/node limits, and export complete
   displayed paths with evidence and explicit bounded-search boundaries. Test and commit.
   Implemented. 82 tests/Ruff pass; actual browser branch expansion, expand/collapse and
   downloaded five-step JSON checked for ordered steps, source hashes and statement IDs.
4. **Schema-aware direct column coverage.** Reuse trustworthy schemas; preserve unknown
   wildcard/ambiguous diagnostics. Do not treat transitive usage as direct usage.
   Implemented typed SQL DDL reconciliation, inferred plain wildcard expansion, dual query/DDL
   provenance and a parsing switch. 100 tests/Ruff pass after review fixes; real column/schema/
   dictionary browser checks passed. Parser cache version4.

5. **Recoverable history maintenance.** Add a bounded preview/archive/restore workflow in
   Storage and workspaces for old analysis/import records. Protect the latest completed run,
   records referenced by active edges/inventory, and running analyses. Archive before any
   transactional removal; restore without overwriting newer records. Keep originals, current
   lineage and AI provenance untouched. Use fixed table allowlists, workspace/path checks,
   archive integrity/size limits and an idle-analysis guard. Test rollback/isolation/restart
   and exercise the actual UI before committing. No permanent deletion or blob GC in this slice.
   Implemented with migration3 transactional compressed recovery journal plus JSON copy;
   missing-file restart recovery and failure rollback tested. 110 tests/Ruff/lock checks pass.
   Actual Settings browser archived and restored three records; active imports protected.
6. **Persistent visualization and source-view defaults.** Reuse Settings, Explorer, graph
   renderer and configuration schema. Save workspace defaults for direction, temporary-step
   collapse, compact/full/hidden labels, semantic/neutral node palette, edge width, complete/
   relevant-first source and code line numbers. Validate with a typed allowlist; share graph
   appearance between the live component and offline exports. Keep exact names accessible
   through tooltips and evidence regardless of label density. Apply saved defaults to Explorer
   controls per workspace without carrying widget choices between workspaces. No new renderer,
   custom CSS input, source changes or lineage-semantic changes. Test saved/reopened/portable
   preferences, actual rendered graph/export data and lazy source display, then browser-check.
   Implemented. 120 tests pass in normal and clean Python 3.11 environments; Ruff/lock/build
   checks pass. Actual browser saved preferences and verified persistence after restart,
   hidden labels/accessible names, neutral fills, 4px edges, evidence and downloaded JSON.
   Independent review cleared state/config/evidence handling after actual-text fitting fix.
7. **Unresolved diagnostic review queue.** Derive up to 100 warning/error items from current
   analyzed SQL/SAS inventory; exclude CSV, informational and pending/reimported files. Show
   the diagnostic and suggest its containing stored statement or a bounded nearby range.
   Let the user adjust the exact preview before requesting one routed assistance call.
   Pin the preview hash through the provider request; changed files require refreshing.
   Reuse existing privacy/context/redaction/grounding/quarantine and explicit inferred merge.
   Keep only record IDs in UI state; read durable responses from existing AI history. No
   automatic provider calls, hidden batch processing, new persistence or guessed dependencies.
   Verify isolation, context scope, stale-source refusal, privacy, quarantine/merge and UI.
   Implemented. Independent reviewer found no material issues; 33 focused tests pass. Actual
   browser ZIP import/analysis and adjustable focused preview passed without provider use.
   Synthetic HTTP/AppTest verifies request/quarantine, stale-click refusal and inferred merge.
   Complete suite: 127 tests pass in normal and clean Python 3.11 environments; Ruff/lock/build
   pass. No new live gateway call. Screenshot `.dataforge/verification/unresolved-review.png`.

## Remaining backlog beyond these slices

User-requested theme slice: add eight explicit Ocean/Forest/Amethyst/Graphite dark/light
presets in Settings Visualization. Dark choices set native appearance directly rather than
depending on the browser's Light/Dark menu. Preserve unrelated config, use atomic TOML-aware
updates and bounded native reload acknowledgement. User will validate final appearance;
no further browser inspection after that instruction.

Follow-up theme correction: preserve all eight existing definitions/order and the user's
active configuration. Append only six choices: Claude orange light/dark, Nord light, Rose
light, Sand light and Mint light. No changes to theme application logic or default selection;
user validates appearance. Keep the user's `.streamlit/config.toml` edit out of the commit.

- Next: task-specific column/explanation result schemas beyond the shared grounded-lineage
  schema. Extend prompt/schema versioning, deterministic quote/column validation and advisory
  presentation; do not merge explanations or column suggestions as table relationships.
- LLM concurrency/chunking controls, remaining parsing/confidence settings and logging verbosity.
- Controlled stale temporary-file cleanup. Retained history archives are recoverable; there
  is no permanent purge. Source/blob GC and full portable source/history workspace bundles
  are optional operational improvements; master-required safe metadata transfer is delivered.
- Explicit job/session identity and broader target-vendor SQL/SAS fixtures.
- Real large-project accuracy checks, Docker/remote CI execution, standalone HTML
  browser verification where file navigation is supported.

Each completed group needs regression tests, actual UI exercise, status/knowledge updates,
and a local Conventional Commit. New findings may adjust order; no full-completion claim
until mandatory requirements and their acceptance checks are accounted for.

Task-specific advisory slice implemented in completion execution: v2 contracts, complete-operation
source grounding, offline saved result selection and hard exclusion from lineage merges/refresh.
See COMPLETION_PLAN.md and latest IMPLEMENTATION_STATUS entry. Next: AI resource controls.

AI resource controls implemented: bounded admission, offline complete-statement chunk previews,
one explicit request per chunk, portable settings and cooperative cancellation. Fixed-route
synthetic live SQL/SAS merge/refresh/reopen passed. Next: remaining settings and cleanup.

Current live-test constraint: OmniRoute model must be auto (user instruction). User has restarted OmniRoute. Literal auto connection check failed; preserve quarantine and
record the endpoint model-availability limitation. No fixed-model substitution.

Remaining settings implemented: extension dialect/PROC SQL precedence, confidence/inferred graph
filters, diagnostic display and reparse defaults, safe app-wide logging. Parser cache version5.
Selected refresh reparses previously analyzed incompatible files rather than dropping facts.
Next: temporary cleanup, job/session boundaries, vendor fixtures and final acceptance.

Safe staging cleanup completed with migration4 recovery journal, explicit selection, bounded
preview/identity checks and no-overwrite restore. Sources and history JSON stay protected.
Next: explicit job/session scope and vendor fixtures, then final acceptance/verification.

2026-10-16: explicit supplied job/session identity implemented with regression and UI checks;
next vendor fixtures and final acceptance/package accounting. See IMPLEMENTATION_STATUS.
