# Adaptive AI context implementation plan

> **For agentic workers:** Use superpowers:executing-plans, with test-driven development and a final independent review.

**Goal:** Automatically fit SQL/SAS/dbt analysis into bounded requests, preserve exact source evidence and saved progress, and expose optional per-build character controls and sortable sizing diagnostics.

**Architecture:** Separate disclosed-source allowance from full-envelope model token capacity. Compact host metadata and schemas, then recursively partition source/context work when required. Persist each partition as an immutable unit specification using existing checkpoints and combine validated facts through existing graph linking. Partial views never claim complete semantic coverage.

**Tech stack:** Existing Python, SQLGlot, DuckDB, Streamlit, shared CLI/MCP contracts; no new framework or static parser changes.

## Global constraints

- Static parser algorithms remain unchanged. Original bytes and source coordinates remain authoritative.
- No live provider requests or edits to the user's Test workspace during implementation qualification.
- Automatic planning respects model limits, disclosure permissions and finite lifetime allowances. A supplied per-build character allowance explicitly overrides saved character allowances only.
- Unknown context capacity stays unknown; no promise of universal model comprehension. Source partitions retain explicit partial coverage and cannot invent semantics.
- Keep resumable journals, cancellation, quota handling, atomic publication and compatible legacy responses.
- Extend the existing feature branch and PR; user already authorized implementation and PR updates.

## Review focus

- Tiny source with large fixed schema must run under the default 8,000 source-character allowance.
- Large single statements/blocks, Unicode, dbt context and shared declarations must partition without source loss or unbounded recursion.
- Partial source views must not accept out-of-view expression references or certify full coverage.
- Resume must reconstruct the identical partition and preserve completed checkpoints.
- UI must distinguish total request size, disclosed context and model token capacity; override must reach CLI/MCP/runtime.

## Tasks

1. [x] Add failing allowance/compact prompt regressions; implement source versus envelope sizing and optional `max_context_chars` contract across all callers.
2. [x] Add failing adaptive partition tests for SQL/SAS/dbt and giant indivisible source/context; implement exact-range partitioning, compact indexed context and bounded retrieval with persistent specifications.
3. [x] Add end-to-end evidence/coverage/resume regressions; integrate original-source validation and stored-fact composition for partitions.
4. [x] Add UI regression for the optional character override and sortable per-file/task sizing table; implement controls and diagnostics.
5. [ ] Qualify the actual 2,200 SQL fixtures through full preview and mock-provider execution, plus mixed/Unicode/larger-than-former-cap cases. Run affected and full gates, lint, docs and packaging checks as warranted.
6. [ ] Update public flow/recovery/architecture docs and knowledge maps; final independent review, address findings, commit and update PR.

## Implementation rulings and evidence

- Reuse the current branch and database schema: partitions are additive unit specifications in existing persisted JSON, not a parallel scheduler or new graph service.
- Character controls describe disclosed source/context. All model-capacity checks continue to include the complete prompt and output headroom.

- Exact expression components retain verified input subsets and source ranges. Complete range coverage plus full original semantic validation is required before composition; no whole-project or whole-expression final provider call is introduced.
- Review certificates belong to bounded components. Reuse recomposes after review, so newly rejected components invalidate earlier composed facts. A final composite is never sent whole for review.
- Output fitting considers expression slots as well as unique unqualified lexical names, preventing repeated UNION branches from overrunning response arrays without overpartitioning ordinary UPDATE assignments.
- Quoted identifiers retain spaces/escaped delimiters in visibility checks. Supported UPDATE/MERGE component validation shares a cached complete-source verifier.
- Large exact expressions persist as immutable offsets. A real17MiB regression passes checkpoint/snapshot rehydration; support refresh and one-source-read report regressions pass.
- Independent reviewer reproduced six correctness/performance gaps; all were addressed with targeted regressions. Final narrow storage re-review: no remaining actionable findings;14 persistence tests pass.
- Verification in progress: focused88 passed, later component/storage/scaling62 passed, strict42-page Pages build and lint/lock passed. Fresh installed wheel exercised301dependency composition, additional review and zero-network reuse. Final suite:963 passed/2 existing Windows skips in248.62seconds; actual2200fixture execution remains in progress.
