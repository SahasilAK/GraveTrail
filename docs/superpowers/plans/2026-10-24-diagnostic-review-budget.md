# Diagnostic review budget implementation plan

Goal: diagnostic review preview and dispatch use confirmed model capacity and the full redacted provider body.

Scope: stay on `codex/resumable-ai-lineage`; preserve unrelated files. No schema, dependencies, scheduling or automatic merge changes.

- [x] Add failing diagnostic-budget regressions, including complete-body overhead and disclosure migration.
- [x] Extract assistance preparation in llm.py, reuse the existing allocator with fresh default AnalysisRequest values for reviews, and reprepare each authorized dispatch/fallback.
- [x] Share routed review previews through assistance_queue.py with Streamlit and CLI/MCP. Preserve the selected source span and expose blockers.
- [x] Verify affected manual, provider, token-budget, agent and UI tests; update focused documentation/maps.
- [ ] Live first_test LM Studio review: user will validate. Computer Use stopped because it could not safely confirm the browser URL. No live database access or merge was attempted.

Verification: 189 affected assistance/review, provider/connection, model-budget, agent API/CLI/MCP and UI tests passed. Three additional full-source privacy/fallback authorization regressions passed separately (192 distinct tests). Targeted Ruff and git diff --check passed. No migration, new dependency or project-analysis scheduler change.

## Follow-up: first_test small review blocked by workspace catalog

User reported the exact 974-character, 13-line MySQL banking fixture at 86,232 estimated input tokens against 71,501 allowed, with 30,643 reserved output. The initial fix kept every job-visible asset in each diagnostic prompt, unlike AI Analysis's source-referenced context selection. The live DuckDB file rejects a read-only connection; do not bypass its owner lock.

- [x] Reproduce the exact fixture and 107,520-token combined capacity in temporary storage, including the full banking catalog.
- [x] Scope diagnostic prompt names to lexical references in the exact selected source, following existing AI context identifier rules. Keep the full job-visible catalog for grounded validation. Expose selected/total catalog counts and scope; never clip relevant names or source to fit a budget.
- [x] Preserve other manual callers, routing, confirmed-capacity budgeting, privacy and explicit merge. Check preview/dispatch/client parity, quoted names, comments, irrelevant catalog growth, and genuine source/prompt overflows.
- [x] Run focused and affected gates. Report the exact-fixture offline result separately from the user's live validation.

Offline evidence: parsed all 2,114 SQL files plus six CSV manifests into a temporary Store. The original request estimated 86,501 input tokens (blocked); the corrected request estimates 4,747 / 71,501 tokens with the same 30,643 output reservation and all 974 source characters. One source-referenced name is established in the default parser's 2,084-name local catalog. The MySQL target is not yet known; it is not invented to expand validation authority. A mock provider observed the same body/budget as preview. The exact-estate regression passed, as did 203 other affected tests, targeted Ruff and diff whitespace checks. User retains live LM Studio validation; no live request, profile change, database unlock or merge.
