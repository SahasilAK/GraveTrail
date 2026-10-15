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
3. **Progressive lineage trees and dependency-path exports.** Render only open branches,
   provide expand-to-depth/collapse controls, keep cycle/node limits, and export complete
   displayed paths with evidence and explicit bounded-search boundaries. Test and commit.
4. **Schema-aware direct column coverage.** Reuse trustworthy schemas; preserve unknown
   wildcard/ambiguous diagnostics. Do not treat transitive usage as direct usage.

## Remaining backlog beyond these slices

- Safe history/blob cleanup; portable source/history workspace bundles.
- Explicit job/session identity and broader target-vendor SQL/SAS fixtures.
- Integrated opt-in unresolved-assistance queues, task-specific result schemas,
  LLM concurrency/chunking controls, remaining parsing/visualization settings.
- Real large-project accuracy checks, Docker/remote CI execution, standalone HTML
  browser verification where file navigation is supported.

Each completed group needs regression tests, actual UI exercise, status/knowledge updates,
and a local Conventional Commit. New findings may adjust order; no full-completion claim
until mandatory requirements and their acceptance checks are accounted for.
