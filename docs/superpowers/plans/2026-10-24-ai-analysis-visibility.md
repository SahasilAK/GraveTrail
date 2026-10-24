# AI analysis visibility implementation plan

**Goal:** Expose measured live work and inspectable requests without changing lineage semantics.
**Architecture:** Query the existing run/request/attempt/unit ledger. Keep bounded activity in run summaries and payloads in a separate DuckDB table, captured by the existing adapter. Share rendering between active and saved runs.
**Spec:** User's supplied visibility request and docs/promts/2026-10-23-simplify-ai-lineage-plan.md.
**Constraints:** Current branch and combined working state; preserve .streamlit/config.toml; no dependencies or live/paid provider calls. Use `small` for local workspace checks. Mock transports for execution.

## Phase 1
- [ ] Add failing tests for early job identity, cancellation acknowledgement, live durable counts, changing totals, reuse, reopen and isolation.
- [ ] Add lightweight progress projection from existing records; record timestamps, bounded activity and reused checkpoint IDs.
- [ ] Bind jobs to runs before preparation; render shared counters/activity before the active-page stop. Preserve fast polling and terminal refresh.
- [ ] Run focused regressions and commit verified phase.

## Phase 2
- [ ] Add failing tests for actual transport capture, malformed/error bodies, redaction, retention/cleanup, historical missing content, lazy pagination and isolation.
- [ ] Add migration and separate bounded inspection artifacts; capture dispatched bodies/responses without headers or changing outgoing content. Integrate workspace/run cleanup and backup compatibility.
- [ ] Add lazy Inputs/Outputs inspectors with stable selection, pages and download; separate raw, decoded and validation/recovery outcomes.
- [ ] Run focused tests, full suite and lint; verify `small` offline UI, update user/results/knowledge documentation and commit.

## Review focus
Unknown usage must remain unknown; failed attempts are not failed files. Superseded parts must not count as unfinished. Resume must retain identity and reuse without new calls. A cancelled request may have an unknown provider outcome. Collapsed inspectors and polling must not hydrate source/response content.

## Execution record
The supplied request authorizes implementation without routine approval; execute inline in the current checkout. Baseline full suite started before edits. No applicable AGENTS.md exists in the workspace or its ancestors.
