# Durable AI Extraction and Response Recovery Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking. This document is a ready-to-use implementation prompt; creating it does not authorize starting implementation in the planning chat.

**Goal:** Preserve every validated extraction as it completes, reuse it on compatible resume, recover retained responses locally before sending more requests, show exactly what is durably saved, and display provider-supplied reasoning live when available.

**Architecture:** Extend the existing DuckDB run/request/attempt/part checkpoints. Schedule missing work by stable part identity, not by whether a request has a response. Keep optional full response retention separate from required validated extraction checkpoints; reuse existing inspection storage only when its privacy, integrity, and retention conditions permit replay.

**Tech Stack:** Existing Python, DuckDB, HTTPX, Pydantic, Streamlit, pytest, Ruff. No new dependencies or services.

**Spec:** The behavioral requirements below, together with `docs/promts/2026-10-23-simplify-ai-lineage-plan.md`. Read both before editing. This prompt deliberately extends the earlier visibility-only work to improve extraction recovery.

## Implementation prompt

Implement this plan on `codex/resumable-ai-lineage` from the current combined committed and uncommitted state. Read applicable repository instructions first. Preserve unrelated changes, especially `.streamlit/config.toml`. Use **`small_sql`** for workspace-level verification; this replaces the earlier workspace name `small`. Do not change its sources or erase its existing runs. Use temporary isolated stores for automated tests and synthetic provider responses associated with its source shapes for workspace verification.

The original objective is that cancelling and continuing an analysis does not discard usable extraction work. A request marked processed is currently only a handled response; it is not proof of a saved extraction. Make the storage guarantees and resume behavior match what the UI tells the user.

### Verified starting points; recheck before editing

- `analysis_service.py` persists plans and request/attempt records and saves validated parts through `save_part_extraction`.
- `ai_analysis_store.py` stores successful extraction checkpoints as completed `extraction5` units. Unresolved stubs are not successful checkpoints.
- `ai_pipeline_store.py::recover_pipeline` currently treats received-but-unprocessed requests as uncertain work; it does not replay retained responses.
- `analysis_service.py` rejects a response marked truncated before `decode_extractions`, so complete items in that response do not reach per-part validation.
- `ai_wire.py::decode_extractions` parses complete JSON and validates items independently; malformed JSON currently prevents all decoding.
- `ai_inspection.py` stores optional bounded request/response bodies. History is opt-in; artifacts can be redacted, missing, expired, or oversized. Inspection retention alone is not a durable extraction guarantee.
- Resume reuses compatible work within the same run. A new run is not a cross-run extraction cache.
- `llm.py::_stream` currently uses cancellable asynchronous I/O but buffers ordinary JSON to completion; it does not consume model SSE events incrementally. `ui/analysis_ai.py` currently updates the progress fragment every two seconds. Async transport alone does not provide live browser rendering.

## Global constraints

- No live or paid provider calls. The prior LM Studio HTTP 400 remains unresolved until the user explicitly confirms otherwise. Mock transport tests do not establish model accuracy.
- Do not stop, restart, clear caches for, or cancel an existing user analysis to execute tests. Do not contend with the running application's DuckDB lock by forcing access.
- Preserve extraction validation, source/evidence checks, consolidation semantics, resource identity, deterministic linking, atomic publication, retry ceilings, and conservative token accounting.
- Keep existing privacy defaults. Do not enable history, retain prohibited raw content, or silently introduce a second raw-response archive.
- Never claim exactly-once remote execution. A process can die after the provider receives a request but before a local response checkpoint commits.
- No broad refactor, cross-run incremental cache, new scheduler, or speculative general-purpose event system.
- Focused local commits only; do not push. Run failing regressions before fixes, then relevant checks. Report existing failures accurately without weakening tests.
- User-requested exception: do not add new automated tests for the live reasoning feature (Task 5). Existing checks and a manual check with synthetic stream data still apply. Keep the planned regression coverage for persistence and resume.

## Required behavior and storage contract

| Stage | Required durable state | Resume consequence |
| --- | --- | --- |
| Planning | Run, pinned source hashes/configuration, versioned file/part plan, work kind and dependencies | Reconstruct the same compatible work without rereading mutable inputs as if unchanged |
| Before dispatch | Request membership and work fingerprint, then attempt ID/reservation committed before transport | Know exactly which part versions were sent; a planned request is not evidence of dispatch |
| Response receipt | Existing outcome, usage, finish reason; explicit payload availability and replay eligibility | A received response may still need local validation; receipt never completes parts |
| Optional response checkpoint | Complete eligible provider response persisted under current history policy, bound to attempt and protocol/context identity | Replay locally after interruption before considering another provider call |
| Part validation | Each valid part committed immediately, with provenance linking the producing attempt and revision | Never resend that completed compatible part on resume |
| Response handling complete | Durable per-part outcomes and recovery state; request handling outcome committed last | Only missing/invalid work enters bounded recovery |
| Finalization | Existing completed file records and publication checkpoint | Build from saved facts; reopening results does not invoke a provider |

1. Persist the complete initial logical work plan before dispatch. Do not prebuild every future HTTP body: completion, consolidation, splits and retry batching depend on earlier results. Persist each additional work definition before sending it, including parent/child supersession.
2. Use the existing stable part identity plus existing compatibility checks for source, work kind, input/context revision and protocol/configuration. A file may have several parts; completing one must not skip the rest.
3. Keep request state separate from extraction outcome. Record counts/IDs of saved, missing, invalid and unresolved parts, with fixed diagnostic codes. Derive aggregates from durable state, not a second mutable counter system.
4. A successful checkpoint survives cancellation, process restart and reopening the store. Persist each validated part before checking cancellation between parts. If cancellation interrupts remaining validation, resume must reuse already committed parts and either replay eligible retained input to validation or report the lack of replay content.
5. A storage failure blocks further dispatch. Do not misclassify it as a bad model response and spend tokens retrying.
6. Resume means continue the selected compatible run. Start fresh explicitly creates a new run and may resend selected sources. Do not silently switch a stale run into a fresh one. Explain compatibility failures.

### Truncation and partial acceptance

- A truncation finish reason is a warning, not grounds for discarding independently complete valid items.
- For a fully parseable envelope, apply existing identity, schema, source/evidence and stage-specific checks to each item even if the finish reason is truncation. Save valid items; retry only the rest.
- For syntactically cut-off JSON, permit only a conservative bounded decoder of complete top-level `items` entries. Use JSON token/decoder boundaries that honor strings, escapes and nesting. Do not use regex extraction, repair missing brackets, invent fields, or accept fragments of an item.
- Fail closed on ambiguous envelope structure, unsupported wrapper formats, duplicate keys/identities, unknown IDs or conflicting records. Known valid siblings may survive only where their identity is unambiguous under the existing contract. If a trailing incomplete item could duplicate an earlier accepted ID and cannot be disambiguated, reject the ambiguous salvage rather than guessing.
- Validate all salvaged entries with the normal validators, including completion-revision and consolidation checks. Preserve truncation and partial coverage diagnostics. Never convert missing work to `no_operations`.
- Maintain existing bounded batch reduction, splitting, retry and unresolved behavior for remaining work only. Record split children before dispatch and exclude superseded parents from pending work.

### Retained response replay and privacy

- Reuse the current raw output artifact where it is complete, unredacted, within retention, intact and scoped to the exact attempt/work context. A decoded inspection artifact alone is not proof of validated extraction.
- Separate replay eligibility from inspection availability. Add version/fingerprint/integrity metadata as needed; historical artifacts without sufficient provenance are inspection-only.
- Extract a pure provider-envelope decoding path shared by live handling and replay; replay must perform no network call, reservation, usage increment or new attempt creation.
- Persist payload and its eligibility marker consistently before advertising `Response saved; validation pending`. If persistence fails, stop safely and do not claim the response is recoverable.
- Recheck the current privacy setting and retention at replay time. Do not replay altered/redacted content as the original. Never bypass redaction by keeping a secret second copy.
- With history disabled or an unavailable payload, validated parts remain resumable, but a crash before their validation can require resending unfinished parts under existing unknown-outcome controls. Display this limitation explicitly. Do not promise that every received response can be recovered.
- Bound storage and integrate any new metadata/schema with existing migration, backup, restore and cleanup paths. Payload expiration never deletes successfully validated part checkpoints.

## Review focus

1. Crash between receipt, the first part save and request finalization: committed parts reused and replay idempotent (Tasks 1 and 3).
2. Truncated strings, nested JSON, duplicate IDs and incomplete trailing items: no fabricated extraction or premature completion (Task 2).
3. Changed source/context, split children and completion revisions: no stale reuse or accidental file-wide skipping (Tasks 1 and 3).
4. History disabled, redacted, expired or oversized payloads: honest replay availability with no privacy bypass (Task 3).
5. Cancellation and UI refresh during persistence/replay: no duplicate dispatch, payload loading or false saved counters (Tasks 1 and 4).

## Task 1: Pin durable part outcomes and resume invariants

**Files:** `src/dataforge/analysis_service.py`, `src/dataforge/ai_analysis_store.py`, `src/dataforge/ai_pipeline_store.py`; tests in `tests/test_ai_resumable_files.py`, `tests/test_ai_partial_recovery.py`.

**Interface:** Preserve `save_part_extraction` and existing run/unit readers. Extend checkpoint provenance using existing record/details structures where possible. Treat completed compatible unit records as the authority for pending selection. Request outcomes reference those records rather than duplicating extraction bodies.

- [ ] Write regressions: a mock batch of three parts saves two valid parts, leaves the third missing, then cancellation/store reopen/resume sends only the third. Assert exact dispatched part IDs, saved records and unchanged prior graph before publication.
- [ ] Add interruption tests after each successful save and before request-finalization commit; repeated recovery never duplicates facts. Add storage-write failure test asserting no further provider dispatch. Add stale source/configuration and split-parent tests proving invalid reuse is rejected.
- [ ] Run these tests and record actual failures; retain already passing invariants as regression coverage.
- [ ] Make the minimal persistence/order/provenance changes needed. Reconcile pending work against completed checkpoints before every batch, including retry batches. Commit request-handling outcome only after part/recovery writes succeed.
- [ ] Run `.venv/Scripts/python.exe -m pytest tests/test_ai_resumable_files.py tests/test_ai_partial_recovery.py -q`; require passing focused tests and commit verified changes.

## Task 2: Preserve independently valid items from partial responses

**Files:** `src/dataforge/ai_wire.py`, `src/dataforge/analysis_service.py`; tests in `tests/test_ai_wire.py`, `tests/test_ai_extraction_recovery.py`.

**Interface:** Extend `decode_extractions(payload, expected_parts, *, diagnostics=None, allow_truncated=False)` while preserving the existing `(valid, errors)` return shape and strict default. The service enables truncation recovery only for an actually flagged truncated response. Normal schema/evidence validation remains outside the syntactic decoder as today.

- [ ] Write regressions for a parseable truncated-flag batch containing two valid items and one missing item; assert two saved checkpoints and only the missing ID dispatched again.
- [ ] Add cut-off JSON tests with complete items followed by an incomplete item, nested structures, escaped quotes/braces, incomplete strings, duplicate IDs/keys, unknown IDs and invalid evidence. Assert conservative acceptance/rejection and exact recovery membership. Include completion and consolidation paths.
- [ ] Run focused tests to establish failures before changing decoding.
- [ ] Remove blanket pre-decode truncation rejection. Implement bounded conservative complete-item recovery and propagate both valid results and truncation diagnostics through existing validation/persistence. Do not relax item validation or completion claims.
- [ ] Run `.venv/Scripts/python.exe -m pytest tests/test_ai_wire.py tests/test_ai_extraction_recovery.py tests/test_ai_partial_recovery.py -q`; commit verified changes.

## Task 3: Replay eligible received responses before resending

**Files:** `src/dataforge/llm.py`, `src/dataforge/ai_inspection.py`, `src/dataforge/ai_pipeline_store.py`, `src/dataforge/analysis_service.py`; relevant existing migration/lifecycle modules only if schema changes are necessary. Create `tests/test_ai_response_replay.py`; extend `tests/test_ai_inspection.py`.

**Interface:** Factor the current provider-envelope decoder into a pure helper shared by transport and replay. Add `load_replayable_response(store, workspace, run_id, attempt_id, *, expected_fingerprint)` in `ai_inspection.py`, returning eligible response content or an explicit unavailable reason, never an implicit empty success. Preserve current transport observer behavior for callers that do not use replay.

- [ ] Write crash/reopen tests at response receipt before validation, after the first saved part and after final handling. Eligible replay must save remaining valid work with zero new transport calls and unchanged attempt/token totals; a second replay must be a no-op for already saved parts.
- [ ] Add unavailable-content tests for history off, subsequent privacy disablement, expired, redacted, oversized, missing, corrupt, historical and wrong workspace/run/context artifacts. Assert no unsafe replay or silent automatic unknown retry.
- [ ] Establish failing tests. Implement eligibility metadata, consistent save ordering, pure decoding and replay before network scheduling. Route replay through the same stage-specific validators, part saves and recovery finalization as live responses.
- [ ] Verify cancellation during replay, response persistence failure, and cleanup/backup/restore behavior. Validated checkpoints survive raw artifact deletion. No new retention defaults or credentials in persisted metadata.
- [ ] Run `.venv/Scripts/python.exe -m pytest tests/test_ai_response_replay.py tests/test_ai_inspection.py tests/test_ai_analysis_transport.py tests/test_ai_resumable_files.py -q`; commit verified changes.

## Task 4: Show saved work separately from handled requests

**Files:** `src/dataforge/ai_analysis_progress.py`, `ui/analysis_ai.py`, `ui/analysis_inspection.py` and existing shared status rendering helpers. Tests: `tests/test_ai_analysis_visibility.py`, `tests/test_ai_analysis_ui.py`, `tests/test_ai_inspection_ui.py`.

**Interface:** Extend the existing lightweight progress projection and shared active/final renderers. Use durable checkpoint/outcome metadata; never load raw payloads to calculate counters.

- [ ] Add failing UI/projection regressions for received=2, handled=2, saved parts=0 with truncation recovery. The user must see that no reusable extraction was saved and why.
- [ ] Replace the ambiguous request label `Processed` with `Responses handled`. Keep `Responses received` distinct from `Validated parts saved`, `Saved parts reused`, and `Parts needing recovery`. Show `Responses saved; validation pending` only for eligible durable response checkpoints. Show a clear unavailable-replay reason where relevant.
- [ ] For each handled request show saved/expected parts and validation/recovery outcome. Define reused as a subset of saved compatible work so totals are not double-counted. Do not label unresolved stubs as saved successful extraction.
- [ ] Show Resume/Continue as reuse of the selected run; clearly label Start fresh as a new run. Preserve existing stale/unknown recovery controls. Do not create cross-run caching.
- [ ] Verify active polling, cancellation and expansion do not dispatch requests or hydrate response bodies. Verify final/live counts reconcile after store reopen, including replay and splits.
- [ ] Run `.venv/Scripts/python.exe -m pytest tests/test_ai_analysis_visibility.py tests/test_ai_analysis_ui.py tests/test_ai_inspection_ui.py -q`; commit verified changes.

## Task 5: Show optional live provider reasoning

**Files:** `src/dataforge/llm.py`, `src/dataforge/analysis_service.py`, `src/dataforge/agent/jobs.py`, `ui/analysis_ai.py`; reuse `src/dataforge/ai_inspection.py` for existing privacy/capture integration. Add a focused UI helper only if needed to preserve scroll position without broadening the architecture.

**Scope:** Implement the LM Studio OpenAI-compatible streaming path first, for the user's Qwen3.5-4B setup. Do not assume that its installed model template exposes reasoning or automatically enable thinking. Other providers retain existing behavior unless already compatible with the same verified event format. No extra provider request is allowed to obtain, summarize or fabricate reasoning.

**Interface:** Add an optional reasoning observer at the adapter boundary, delivering only provider-exposed reasoning deltas to a thread-safe, bounded job buffer keyed by workspace, run and attempt. Keep final answer content separate and preserve `Adapter.complete`'s existing return contract. Buffer snapshots are lightweight transient UI state, not extraction checkpoints or a per-token database log.

- [ ] Request `stream: true` for the supported LM Studio analysis path and consume SSE incrementally inside the existing cancellable I/O lifecycle. Handle event boundaries across network chunks, final finish reason, usage-only events and stream termination. Accumulate final answer content for the existing decoder; reasoning must never enter extraction JSON. Keep size limits, timeout/error handling and conservative unknown-outcome accounting. Do not automatically resend a failed streaming request as non-streaming: it may already have consumed tokens.
- [ ] Read reasoning only from the supported provider's explicit reasoning events/fields. Verify the installed protocol through available configuration/docs or synthetic fixtures without initiating a prohibited live generation. Do not label ordinary answer content as thinking or invent a fallback explanation. If reasoning is absent, normal extraction must still complete.
- [ ] Feed deltas into the current attempt's buffer; coalesce updates and cap retained display text at 64 KiB of UTF-8, trimming safely at character boundaries. Label when older displayed text was removed. Do not serialize the buffer into durable job progress on every token. Clear it on new attempts/job disposal and prevent cross-workspace or cross-run leakage. Apply existing credential redaction before exposing text, including secrets split across chunks; hold incomplete tails as needed.
- [ ] Render a `Model thinking` expander with a **300px fixed-height scrollable body only when non-whitespace reasoning actually exists**. Otherwise display exactly **`No thinking/reasoning available`** as a small caption, without an empty scrolling box or simulated thinking text. This includes unsupported providers, no reasoning yet and completed responses that supplied none. Replace the caption with the expander if reasoning later arrives. Keep request waiting/activity status separate.
- [ ] Use a narrowly scoped Streamlit fragment to deliver buffered updates approximately every 500ms while the job is active, without a whole-page rerun or blocking Cancel. This is incremental panel refresh, not a claim of zero-polling browser push; do not add a new SSE server or WebSocket service. Preserve expansion and scroll state across updates. Auto-follow only while already at the bottom; scrolling up pauses follow. Provide `Jump to latest`. Use a small UI helper if necessary to meet these scroll requirements, without new dependencies.
- [ ] Show the current attempt identity and distinguish streaming, finished and interrupted reasoning. Collapsing the panel must not cancel or resend the request. Stop periodic updates after termination. Render content as escaped text, never executable HTML. Live reasoning does not count as validated or saved extraction.
- [ ] Integrate streaming with Task 3: retained wire output must be labeled as SSE rather than a JSON response. Its replay decoder reconstructs the same final response and requires the protocol's terminal evidence before marking the stream complete. A disconnected stream remains incomplete/unknown; displayed reasoning cannot make it eligible for successful replay. Apply existing privacy, redaction and retention limits to captured wire data; do not introduce a separate permanent reasoning archive. Preserve finish reason and reported usage without counting every chunk as an attempt or response.
- [ ] Add no new automated tests for this feature, as requested. Run relevant existing transport, cancellation, inspection and UI checks. Manually inspect the panel with synthetic incremental reasoning, absent reasoning, scrolling, collapse/expand and cancellation using `small_sql` in an isolated setup. Keep the prohibition on new live calls until the earlier LM Studio issue is explicitly cleared; disclose any unverified live-model behavior.
- [ ] Document the 500ms fragment updates, transient bounded display, absence fallback and model/template dependency. Streaming already-generated reasoning adds no generation tokens; enabling thinking separately can increase tokens and latency. Commit the focused verified change locally.

**Reference documentation:** [LM Studio streaming events](https://lmstudio.ai/docs/developer/rest/streaming-events), [LM Studio Chat Completions](https://lmstudio.ai/docs/developer/openai-compat/chat-completions), [Qwen3.5-4B model card](https://huggingface.co/Qwen/Qwen3.5-4B). Native LM Studio events and OpenAI-compatible SSE are different protocols: follow the endpoint actually used, not an assumed mixture.

## Task 6: Verify the complete contract and document limits

- [ ] Use **`small_sql`** for a controlled mocked scenario: persist the part plan, receive a batch with valid and unfinished work, cancel after successful saves, reopen/resume and prove by recorded dispatch IDs that saved parts are not sent again. Separately prove eligible response replay uses zero provider calls. Do not perform this by disturbing an existing live run; use an isolated test store if necessary and disclose the method.
- [ ] Exercise start-fresh separately and confirm it is intentionally a new run. Verify final lineage matches an uninterrupted mock run for identical validated facts, with no duplicate facts or coverage inflation.
- [ ] Run the combined focused test set, then `.venv/Scripts/python.exe -m pytest -q`, `.venv/Scripts/python.exe -m ruff check src ui tests scripts`, and `.venv/Scripts/python.exe scripts/docs/build.py`. Record exact results. The previously observed theme test failure involved user `.streamlit/config.toml`; recheck and report, never overwrite the configuration to hide it.
- [ ] Update `docs/AI_ANALYSIS.md`, `docs/LLM_INTEGRATION.md`, `docs/TESTING.md`, `docs/user-guide/ai-analysis-controls-and-recovery.md`, relevant KNOWLEDGE maps and `docs/promts/2026-10-23-simplify-ai-lineage-results.md`. Include the save-stage table, counter meanings, Resume versus Start fresh, and privacy/crash limitations.
- [ ] Finish with local commit IDs, exact validation results, the `small_sql` verification method and remaining limitations. Explicitly distinguish metadata saved, raw response retained and validated extraction saved.

## Acceptance examples

- **Three requested, two validated:** two checkpoints survive cancellation; Continue sends only the third compatible part.
- **Two responses handled, zero validated parts:** the UI says zero reusable parts and shows the rejection/recovery reason; request receipt does not imply success.
- **Truncated batch with independently valid complete items:** save those items under the conservative decoder rules; retry only unfinished/invalid work.
- **Crash after an eligible response was durably retained:** Resume validates it locally with no new attempt and no double-counted tokens.
- **History disabled and crash before validation:** previously validated parts remain reusable; unvalidated response content is unavailable and the UI makes no no-resend guarantee for that work.
- **Start fresh:** new run and new extraction are intentional; compatible Resume is the path for reusing saved work.
- **Provider emits reasoning:** text appears incrementally in the collapsible 300px panel; scrolling up stays put while generation continues, and Cancel remains responsive.
- **Provider emits no reasoning:** display exactly `No thinking/reasoning available`; no empty reasoning box, invented thinking or extra model call. Extraction continues normally.
- **Reasoning appears but the stream disconnects:** keep the extraction outcome incomplete/unknown under existing controls; visible thinking is never proof that a response or extraction was saved.
