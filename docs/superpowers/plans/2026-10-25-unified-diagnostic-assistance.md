# Unified Diagnostics assistance implementation plan

**Goal:** Both Diagnostics panels and CLI/MCP requests share an offline, model-budgeted preparation and source-backed proposal workflow, with explicit transactional acceptance.

**Architecture:** Keep focused GroundedResponse wire compatibility. Extract host grounding and resource resolution into a domain module used at validation, merge and refresh. Reuse model allocation/request budgeting, context lexer, AssetResolver, existing llm_records JSON and Store transactions. No schema migration or project scheduler.

**Scope:** Existing branch and dirty files preserved. No live first_test database access, profile/dialect mutation, dependency changes, commits, push or PR. Supplied specification is the design authority; execute inline.

## Investigation and reuse

- llm.prepare_assistance already prepares the dispatched payload; diagnostic review opts into current budgeting while manual/service requests default to obsolete character sizing.
- ai_context_index.referenced_asset_names masks comments/literals and selects relevant catalog context independently of budget.
- ai_budget.allocate_analysis_profile/request_budget provide capacity, saved custom output and disclosure enforcement. Retain them and retry authorization.
- Project ExtractionEnvelope/PartExtraction offsets, multi-file context and scheduler are incompatible with focused GroundedResponse. Reuse source/hash/job principles and provenance, not its prompt or scheduler.
- Existing validate_response requires known assets and checks roles with regex; _merge_claims requires catalog IDs. restore_manual_ai_results repeats the same restriction after refresh.
- AssetResolver and ParseResult/AssetRef support scoped identities; llm_records details supports bounds, corrections, resource proposals and structured failures without migration. Store.transaction supports atomic assets/operations/edges writes.
- Existing result renderer is already shared. Extend it and extract shared budget presentation.

## Tasks (test first)

- [x] Add tests using the exact archive source and mocked provider through diagnostic review and manual assistance. Cover unique coordinate rebinding, ambiguity, selection boundaries, comments/literals, unsupported roles, new resources, identity conflicts and SAS temporary jobs.
- [x] Extract deterministic focused grounding: validate exact locations, uniquely rebind inside selection, preserve original coordinates, validate executable read/write/operation syntax independently of quote matching. Use configured dialect; bounded explicit syntax support may establish a proposal when whole-file parsing fails. Fail closed on unsupported constructs.
- [x] Resolve proposals with AssetResolver and current job-visible identities; reject collisions and ambiguous unqualified names. Persist host metadata separately from model schema.
- [x] Remove obsolete model_budget/review_budget branches and flags after checking all references. All focused tasks share source-relevant context and current saved-profile token allocation; advisory contracts stay advisory. Add offline manual budget preview and expose it through existing chunk preview service.
- [x] Include hash/job/range/dialect and relevant static operations/diagnostics in the redacted request. Revalidate source/privacy/profile/context before every attempt; same prepared body feeds count and dispatch.
- [x] Update all three lineage task prompts together, preserving advisory prompts and fenced JSON compatibility. Known assets are context, executable evidence establishes discoveries, metadata is untrusted.
- [x] Merge inside existing transaction: recheck saved bounds/hash/job/settings, resolve current identities, insert only host-validated resources and edges, retain inferred provenance. Repeat merges idempotent, rollback partial failure. Restore via same grounding/resolution on analysis, preserving inferred identity and deduplicating accepted claims.
- [x] Share result and budget display across panels. Show static context, proposed resources/edges, host corrections, unresolved symbols and safe structured failures. Explicit existing merge action remains required; no automatic diagnostic resolution.
- [x] Retain historical schema 1 lineage/advisory reads; historical lineage records without bounds use original stored claim coordinates and strict grounding. Never grant advisory merge rights.
- [x] Run focused regression suites, full first_test archive regression, relevant project AI/service/UI suites, full tests if feasible, Ruff and git diff --check. Update affected KNOWLEDGE maps and user guide. Record actual results and live steps for both panels.

## Acceptance and risks

Exact quote at reported 6–7 rebinds to 10–11 only if unique inside lines 1–13. A source-backed missing target can be accepted explicitly and survives normal analysis as inferred. Wrong roles, comments, fabricated names, runtime macros, ambiguous identities, stale source/job and redacted evidence cannot create facts. Preview is read-only. Full catalog is never transmitted. No claim of live LM Studio correctness until user validation.


## Implementation and verification ledger

- Shared focused_grounding handles host evidence corrections, configured SQL lexical state, SAS literal/comment/datalines/macro boundaries, executable roles and case/job resource identities. SAS dataset_ref extracts unchanged WORK/library normalization for reuse. Saved-result validation is shared at merge and refresh.
- Review findings were reproduced as failing tests and fixed: case-sensitive binding collision; nested SQL comments; uninvoked SAS macro and quoted/comment contents; SAS implicit WORK/configured mappings and repeated mapping on replay. Additional tests reject repeated same-line quotes and persistent/temporary declaration conflicts.
- Schema 3 host metadata uses existing llm_records JSON (selection, settings, corrections, original file/hash/line citations and proposed resources). Existing schema 1 reads remain; their strict saved coordinates cannot acquire new rebind permissions. Advisory schema 2 stays non-mergeable. No migration.
- Removed opt-in model_budget/review_budget flags, obsolete legacy character-fitting branches, catalog-only grounding/merge assumptions, duplicated budget rendering and obsolete unused REVIEW_CONTEXT_CHARS (repository reference search found only its declaration). Retained registered task prompts and validate_response compatibility API intentionally.
- Ordinary static refresh exits before identity replay if no current accepted manual AI records exist. AI-only resource metadata remains origin=ai_inferred after refresh, while deterministic support stays deterministic.
- Final combined affected suite: 331 passed in 102.93s; the later SQL/SAS eligibility regression also passed (focused discovery, budgets, queue, CLI/MCP, provider/privacy, advisory, UI, SQL/SAS parser/scope and cleanup suites). Latest full banking-estate replay: 1 passed in 185.97s, with the entire archive and reported 974-character/qwen3.5-4b budget.
- Additional fresh broad run (all test modules before focused assistance, excluding the separately checked banking estate, plus both Diagnostics panel tests): 636 passed in 294.19s.
- Full repository run: 1237 passed, 2 skipped, 4 failed in 644.11s. Two failures identified missing new CLI/MCP fingerprint options in reference tables and were fixed. Separate documentation/socket follow-up: 17 passed. Remaining palette assertion expects Ocean dark while the pre-existing user config selects Crimson Forge; preserve that config.
- No live first_test store, model/profile/dialect setting, or running provider was accessed or changed. No commits, push or PR.

## Live validation handoff

1. Open first_test, Analysis, Diagnostics using the existing LM Studio/qwen3.5-4b SQL task profile. Restart the existing app process to load the new backend modules; do not force-unlock storage.
2. Optional AI review: choose 09_vendor_dialects/mysql/mysql_004_treasury_treasury_positions.sql, set original lines 1-13, inspect selected profile/model, source and budget, then explicitly request review.
3. Check that the INSERT source/target proposal can include the statically missing target. If the model reports 6-7 with the exact supplied quote, verify the host records correction to 10-11. Fabricated/comment-only evidence should remain quarantined with a specific safe reason.
4. Inspect create/reuse resources and relationship preview, then explicitly merge. Confirm inferred provenance, one relationship after normal refresh, and no funding_deals comment lineage. Diagnostics are not automatically resolved.
5. Optional AI assistance: choose the same file/range and SQL lineage task; compare profile/budget, request and inspect the same result presentation, then explicitly merge. Repeat acceptance must not duplicate existing additions.
6. Do not treat mocked/offline success as live model validation. Unsupported syntax or ambiguous identities can still remain unresolved; configuring a dialect is an explicit user decision.


Final checks: 44 focused assistance tests passed in 18.21s after the last restrictions; Ruff and git diff --check passed. The final quote-role guard requires evidence itself to establish read/write syntax, in addition to selection/original-context checks. Shared dispatch and grounding preserve SQL/SAS eligibility (CSV strings cannot become code). Temporary XML/output files are removed after recording results; unrelated user work remains untouched.

Verification commands used:

```powershell
uv run pytest -q --tb=short --junitxml=.diagnostics-suite-results.xml
uv run pytest tests/test_first_test_review_budget.py -q --tb=short
uv run pytest tests/test_focused_assistance.py tests/test_diagnostic_review_budget.py tests/test_assistance_queue.py tests/test_parity_ai.py tests/test_llm.py tests/test_ai_results.py tests/test_connections.py tests/test_job_identity.py tests/test_llm_resources.py tests/test_ui.py tests/test_sas.py tests/test_sql.py tests/test_sas_project.py tests/test_parser_static_wrappers.py tests/test_cleanup.py tests/test_documentation.py tests/test_gateway_sockets.py -q --tb=short
uv run ruff check .
git diff --check
```
