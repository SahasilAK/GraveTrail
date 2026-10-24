# AI analysis visibility implementation plan

**Goal:** Expose measured live work and inspectable requests without changing lineage semantics.
**Architecture:** Query the existing run/request/attempt/unit ledger. Keep bounded activity in run summaries and payloads in a separate DuckDB table, captured by the existing adapter. Share rendering between active and saved runs.
**Spec:** User's supplied visibility request and docs/promts/2026-10-23-simplify-ai-lineage-plan.md.
**Constraints:** Current branch and combined working state; preserve .streamlit/config.toml; no dependencies or live/paid provider calls. Use `small` for local workspace checks. Mock transports for execution.

## Phase 1
- [x] Add failing tests for early job identity, cancellation acknowledgement, live durable counts, changing totals, reuse, reopen and isolation.
- [x] Add lightweight progress projection from existing records; record timestamps, bounded activity and reused checkpoint IDs.
- [x] Bind jobs to runs before preparation; render shared counters/activity before the active-page stop. Preserve fast polling and terminal refresh.
- [x] Run focused regressions and commit verified phase (`98b6f18`, 49 focused passed).

## Phase 2
- [x] Add failing tests for actual transport capture, malformed/error bodies, redaction, retention/cleanup, historical missing content, lazy pagination and isolation.
- [x] Add migration and separate bounded inspection artifacts; capture dispatched bodies/responses without headers or changing outgoing content. Integrate workspace/run cleanup and backup compatibility.
- [x] Add lazy Inputs/Outputs inspectors with stable selection, pages and download; separate raw, decoded and validation/recovery outcomes.
- [x] Run focused tests, full suite and lint; verify `small` offline UI, update user/results/knowledge documentation and commit.

## Review focus
Unknown usage must remain unknown; failed attempts are not failed files. Superseded parts must not count as unfinished. Resume must retain identity and reuse without new calls. A cancelled request may have an unknown provider outcome. Collapsed inspectors and polling must not hydrate source/response content.

## Execution record
The supplied request authorizes implementation without routine approval; execute inline in the current checkout. Baseline full suite started before edits. No applicable AGENTS.md exists in the workspace or its ancestors.

Ruling: Existing `llm_history` opt-in applies to all full inspection artifacts; use the shorter configured retention or seven days. Disabled/historical content stays explicitly unavailable. No user permission was widened.

Independent review findings received red/green regressions: SQL projects metadata without completion source context, active storage acquisition is nonblocking, unexpected preparation failures terminate associated runs. Mocked AsyncClient tests cover the production cancellation path. Re-review found no additional actionable issues (27 tests independently passed). Final focused group: 92 passed in 46.30s; strict docs build and lint pass. Final suite evidence is recorded in the companion results document.

Final full suite: 1136 passed, 2 skipped, 1 preexisting theme/config failure in 282.65s. The user config remains unchanged; no live/paid calls or push. Phase 2 is committed locally after this verification.
