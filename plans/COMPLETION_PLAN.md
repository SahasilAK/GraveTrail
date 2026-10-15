# Remaining specification implementation plan

Goal: complete the remaining master requirements without replacing the working application.
Authority: `docs/prompts/MASTER_PROMPT.md`, supplied continuation request and AGENTS.md.
Execute inline, test first, commit each coherent feature group. Autonomy overrides skill
approval pauses (ADR 009). Preserve the fourteen themes and the user's active configuration.

## 1. Task-specific AI results
- [x] Add `ai_results.py` contracts for column usages and cited explanation items. Reuse
  existing parser attribution to reject unknown, ambiguous or transitive column claims.
- [x] Route response schema/prompt version by task in `llm.py`; store validated results in
  existing AI records. Reject non-lineage merges, including historical records.
- [x] Render inferred column tables and cited advisory explanations in shared result UI.
- [x] Regression tests: fabricated names/columns, wrong quotes/ranges, cross-statement and
  derived-table attribution, stale source, persistence/reopen, no graph mutation, UI.
- [x] Full pytest/Ruff, running UI exercise, docs/knowledge/status update and commit.

## 2. Bounded AI resources
- [x] Add validated concurrency and statement-aware context chunk settings. Explicit preview
  and one user-triggered request per chunk; preserve hashes, source positions and privacy.
- [x] Test concurrent requests, context limits, oversized statements, cancellation and no
  implicit transmission. Wire settings/config transfer and UI, verify and commit.

## 3. Remaining settings
- [x] Reconcile extension dialect, confidence/unresolved display, reanalysis and safe logging
  controls with existing services; implement actual behavior with compatible defaults.
- [x] Test precedence, cache invalidation, persistence, portability and privacy. Commit.

## 4. Temporary cleanup
- [x] Bound preview/cleanup to explicitly application-owned stale temporary files. Protect
  symlinks, active operations, originals, databases and retained recovery journals.
- [x] Test path races, age/size/count bounds and active guards; actual UI and commit.

## 5. Session identity and coverage
- [x] Explicit supplied job/session boundaries for temporary identities, compatibility and
  provenance preservation. Do not infer temporal execution semantics.
- [x] Add target-vendor fixture cases and resolve demonstrated defects. Commit tested groups.

## 6. Acceptance and delivery
- [x] Audited CSV sample setting, inventory summary/refresh and tree/source panel layout.
- [ ] Preserve exact original SAS block snippets rather than reconstructed token joins.
- [x] Close audited storage-location selection gap: explicit startup-allowed locations,
  session-scoped selection, no data migration, isolated/reopened stores and safe failures.
- [ ] Requirement-by-requirement accounting with code/tests and external verification status.
- [ ] Clean install, package, UI workflows, benchmark, standalone HTML, Docker/CI where available.
- [ ] Stable live OmniRoute synthetic grounding/merge/persistence check using named env secrets.
  No repeated unreliable automatic routes or relaxed validation. Record exact external blockers.

Each task uses failing behavioral tests, implementation, full suite, focused UI checks,
self-review and documentation. Do not mark a checkbox without its evidence; if execution
limits intervene, leave the precise next action in IMPLEMENTATION_STATUS.md.
