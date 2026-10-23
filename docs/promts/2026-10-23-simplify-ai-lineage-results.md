# AI lineage refactoring results — 2026-10-23

Implemented on `codex/resumable-ai-lineage` from the combined committed and existing working state. No reset, push, paid provider request or unrelated source edit.

## Implementation

Independent actual-file extraction now uses one token-bounded items envelope and durable request loop. Valid source-backed AI facts do not need static semantic approval. Every original range and successful sibling is retained. A frozen source/AI index supplies one targeted completion wave; bounded file consolidation can supersede saved facts and operation fragments explicitly. Deterministic saved-result linking builds the versioned, scoped NetworkX operation graph used for publication and upstream traversal.

Static builds remain offline and independent. Single-family AI builds accept SQL, SAS or a dbt project. UI/CLI/MCP share simplified selection/token/recovery contracts. Existing DuckDB/history/migration-9 storage remains readable; incompatible paused protocols require a new build. Existing manual assistance and compatible unselected publication remain available.

The new path removes worker/message scheduling, adaptive width streaks, execution windows, allowance multiplication and generic resolution/review execution. Historical wire/citation/semantic readers remain because saved records still use them. Optional matching OpenAI tokenization uses a checksum-pinned bundled asset and does not download during preview.

## Verification

- Runtime: repository `.venv/Scripts/python.exe` (system Python lacked pytest).
- Eight specified focused command groups: see the final recorded result below.
- Full suite: final result recorded below.
- `python -m ruff check src ui tests scripts`: passed.
- `python scripts/docs/build.py`: passed strict MkDocs plus validation of 42 pages, 8 assets, rendered links/anchors and search.
- `uv build --wheel --out-dir <task scratch>`: passed; wheel inspection confirmed offline tokenizer and extraction/consolidation prompts.
- `python scripts/qualify_ai_context.py --files 1000 --family all`: passed with deterministic HTTP mock transport.

| Family | Source files | Parts | Requests | Table/column/file correct | Seconds | Peak Python MiB | Saved MiB |
| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| sql | 1002 | 1003 | 39 | 1002/2004/999 | 89.39 | 106.5 | 2.19 |
| sas | 1002 | 1003 | 38 | 1002/2004/999 | 91.24 | 57.4 | 2.19 |
| dbt | 1002 | 1003 | 42 | 1000/2000/999 | 304.69 | 97.2 | 2.26 |

All three scale runs accounted for every scheduled range, reused completed work after interruption/reopen, sent requests within configured input/output limits and matched their independent golden graph exactly. SQL/SAS also retained two explicit duplicate-writer boundaries. Input/output estimates, physical requests, source files and parts are reported separately. Provider-reported actual tokens and cost are unavailable for mock transport.

Offline semantic fixtures also compare smaller and larger batches, reversed order and later-discovered definitions. Omission fixtures for every family demonstrate that complete model JSON can still miss relationships. Mock precision/recall of 1.0 reflects fixture/transport/linker agreement, not live model quality.

## Review

A fresh reviewer identified consolidation operation retirement, scoped input identity collisions and invalid supersession poisoning resume. Reproducing regression tests failed before fixes and now pass. Additional regressions cover future same-file writers, final pinned-envelope fitting, durable elapsed ceilings, selected-build preservation and offline credential blocking. The first reviewer model was unavailable due an account usage limit; a fresh available-model fallback completed the review.

## Decisions and remaining limits

- Used the existing checkout, as explicitly requested, to preserve combined working edits. No separate worktree was created.
- Optional tokenization initially used only loaded encodings; the final implementation instead bundles the one tested matching o200k encoding. Unknown models/gateways and an absent optional package use conservative estimation. Incorrect model metadata can still underuse or overestimate advertised gateway capacity; administrators own manual limits.
- Live-model semantic evaluation remains pending, including same-model singleton-versus-batch precision/recall and cost per correct relationship. No provider credits were spent.
- Runtime range/evidence checks cannot detect every semantic omission. Oversized/dynamic/ambiguous/stateful semantics remain explicit limits after bounded completion/consolidation.
- SAS-to-SQL generation, optimization, GraphRAG, agent frameworks and additional databases were intentionally not implemented, as required.

## Final command results

- `.venv/Scripts/python.exe -m pytest -q`: **971 passed, 2 skipped**, 212.80 seconds, exit 0.
- Eight focused plan groups: **18 / 20 / 16 / 37 / 17 / 25 / 21 / 18 passed**, all exit 0 (groups intentionally overlap).
- The two skips were confirmed separately: Windows symlink creation privilege is unavailable for the ingestion escape and temporary-cleanup symlink tests.
- `.venv/Scripts/python.exe -m ruff check src ui tests scripts`: all checks passed.
- `.venv/Scripts/python.exe scripts/docs/build.py`: exit 0, 42 pages and 8 assets validated.
- `uv build --wheel`: exit 0; packaged tokenizer and extraction/consolidation resources verified by ZIP inspection.
- `git diff --check`: clean.

All implementation tasks and offline acceptance checks were completed. Live-model semantic qualification remains pending by explicit no-paid-calls policy.

## Local implementation commits

- `1cb18f1` — independent build selection and single-family validation.
- `7b38288` — model-bound token budgets.
- `0399060` — extraction protocol and bounded source-context index.
- `5eaf08d` — persisted extraction and bounded refinement work.
- `be2c09e` — durable extraction request loop.
- `df09e52` — scoped operation graph and saved-result publication.
- `18123e0` — simplified controls and historical read compatibility.
- `5ba6b5d` — final pipeline cleanup, recovery and review regressions.

The accompanying documentation commit records the approved plan, this evidence and refreshed folder knowledge maps. All commits remain local on `codex/resumable-ai-lineage`.

## Follow-up: four review findings — 2026-10-23

All four findings were confirmed against the current branch. Before implementation, the initial regression command returned **7 failed, 3 passed**: sensitive-mode folding/publication identity, a standalone in-place self-cycle, successive unversioned writer uncertainty, source-order reversal, dependency/order contradiction, shared-scope consolidation overflow and missing actual-context budgeting. The final tests are split into `tests/test_ai_linking_review.py` and `tests/test_ai_consolidation_review.py`, with additional compatibility and recovery coverage.

1. **Case policy:** propagate `case_sensitive` to graph normalization and use graph identities in publication. Quoted names, explicit identities, namespace/job scope and insensitive defaults remain covered.
2. **In-place reads/writes:** separate an unknown before-version from the output instead of reusing the output as external input. A supported earlier producer supplies the previous version; uniquely ordered same-file writes retain successive operation versions. Unknown before-versions remain unresolved, while genuine cross-operation cycles remain cycles.
3. **Execution order:** constrain the selected upstream slice with both dependency and established same-file source order before checking cycles, ambiguity and executable order. Identifier sorting does not establish execution evidence. Conflicting constraints yield no executable order; unrelated components stay excluded.
4. **Consolidation:** group fragments and writer/consumer dependencies, then pack independent intact components using the dispatch `pack_request` function, including actual path/settings and expected output checks. Work IDs include stable sorted input membership/content. No evidence, facts or necessary connected context is clipped. Cancellation after a completed group, store reopening and resume reuse completed groups without duplicate calls or lost operations. Existing supersession regression tests remain passing.

Verification (repository `.venv/Scripts/python.exe`; mocked transport only):

- `-m pytest tests/test_ai_linking_review.py tests/test_ai_consolidation_review.py -q`: **13 passed**.
- `-m pytest tests/test_ai_linking_review.py tests/test_ai_consolidation_review.py tests/test_ai_file_consolidation.py tests/test_ai_resumable_files.py tests/test_ai_operation_graph.py tests/test_ai_review_regressions.py tests/test_ai_linking.py tests/test_ai_full_build.py tests/test_dbt_ai_analysis.py tests/test_ai_analysis_persistence.py -q`: **52 passed**, 16.26 seconds, exit 0.
- `-m pytest -q`: **984 passed, 2 skipped**, 198.85 seconds, exit 0. The same two Windows symlink-privilege skips remain. The final deterministic cycle-list sorting and test-module organization were followed by the focused command above.
- `-m ruff check src ui tests scripts`: **all checks passed**.
- `git diff --check`: clean.

Local code commits: `761e1ab` (findings 1–3), `be379cb` (finding 4). Nothing pushed during this follow-up.

Documentation integration: `scripts/docs/build.py` passed its strict build and validation of 42 public pages, 8 assets, rendered links/anchors, search and publication inventory (236 search entries).

Remaining limits: an intact connected operation/dependency component that cannot fit either input or expected output remains explicitly unresolved with all original details retained. There is no recursive consolidation, pipeline redesign or new infrastructure. Runtime model semantics remain inferred; passing mock tests do not establish live-model accuracy. No paid/live provider calls were made. No requested finding remains unaddressed.

## Follow-up: column publication and explicit-version ownership — 2026-10-23

Both remaining findings were reproduced before fixes: the initial new regression run returned **7 failed, 1 passed**. Failures demonstrated input usages bound to an output version, scoped-name collisions, ambiguity published as inferred, and distinct writers claiming one explicit version without an unresolved boundary. Additional repeated-record publication coverage also failed before its fix.

- **Column identities:** publication resolves source usages and dependency inputs against read bindings, and targets against write bindings. Matching respects case/quoting, resource scope and explicit version information already present in the contract. Exact fact/ordinal bindings preserve correct dependency roles. Ambiguous ownership produces an explicit unresolved asset identity, status, diagnostics and partial publication metadata; it never falls back to dictionary insertion order. Scoped persisted column dependencies now honor an explicit resource identity before the legacy local-expression anchor.
- **Explicit-version ownership:** a resource/version retains all distinct producer IDs and the union of their evidence. Multiple logical writers claiming the same explicit version remain unresolved even with source order; consumers retain that conflicting resource boundary. Publication and linked/run coverage reflect the uncertainty. Repeated records for one logical operation merge evidence/details and publish once. Valid successive versions and the four preceding review fixes remain covered.

New coverage: `tests/test_ai_version_publication.py`, **12 tests**, including adapter and persisted column usages/dependencies for implicit/explicit in-place versions, scoped resources, sensitive names and ambiguous ownership; duplicate explicit versions within/across files and downstream consumers; repeated logical writers; store reopen and graph/publication rebuilding with no provider. A final case-insensitive explicit-read regression failed with only a `rowset` edge before correction, then passed with the original `value` and `row_filter` dependency roles preserved.

Verification uses repository `.venv/Scripts/python.exe`:

- `-m pytest tests/test_ai_version_publication.py -q`: **12 passed**, 3.11 seconds, exit 0.
- `-m pytest tests/test_ai_version_publication.py tests/test_ai_linking.py tests/test_ai_operation_graph.py tests/test_ai_linking_review.py tests/test_ai_saved_publication.py tests/test_ai_consolidation_review.py tests/test_ai_file_consolidation.py tests/test_ai_resumable_files.py tests/test_ai_review_regressions.py -q`: **49 passed**, 7.79 seconds, exit 0.
- `-m ruff check src ui tests scripts`: all checks passed.
- `scripts/docs/build.py`: strict build passed; 42 public pages, 8 assets, links/anchors/search and 236 search entries validated.
- `git diff --check`: clean.

Remaining limitations: `ExtractedUsage` has no version field. A usage may resolve through its operation's unique read binding, but multiple compatible read versions remain explicitly unresolved; no version is invented. Unsupported multi-writer interpretations remain unresolved. No dependency, framework, storage schema or pipeline redesign was introduced. These deterministic/offline results do not establish live-model accuracy; no paid/live provider calls were made.

Local implementation commit: `ac442b6` — preserve column and version ownership. No push was performed during this follow-up.

Final full-suite command: `.venv/Scripts/python.exe -m pytest -q` — **996 passed, 2 skipped**, 223.38 seconds, exit 0. This run includes the final case-insensitive role correction. The two skips remain the Windows symlink-privilege cases. All requested findings are addressed by reproducing regressions and persisted-output checks; the four preceding fixes remain covered. Lint and strict documentation integration also passed as recorded above.

## Follow-up: persisted column traversal and final publication counters — 2026-10-23

Both findings were verified before implementation. The regression command produced **5 failed, 1 passed**: three persisted producer/dependency ID mismatches (same-file, cross-file and scoped explicit-version chains) and two final-counter omissions. The passing clean-selected case protects exclusion of retained uncertain files.

- **Column traversal:** resolved `ai-project` resource references now key persisted columns by the resolved resource asset and case-aware column key. Resource identities already encode scope/version, so the current statement must not split those references. Static parser references, local expression/CTE scopes and unresolved resource identities keep the previous statement-local behavior. Tests compare actual producer target IDs to dependency IDs, traverse all three operations, and repeat traversal after reopening the store. Separate versions, resource scopes, case-sensitive columns and conflicting unresolved writers retain different IDs.
- **Final counters:** capture the analyzed files' publication metadata and unresolved column ownership identities before adding retained results. Sets deduplicate affected file IDs and graph/publication resource boundaries. `incomplete_files` is the unique affected-file count; `coverage_gaps` is that count plus distinct unresolved resource boundaries; `unresolved` includes those boundaries and the existing extraction messages. Public AI documentation clarifies these counters. Persisted report summaries retain the same final values after reopening. A successful commit still reports `complete=False` and does not prove model accuracy.

New coverage lives in `tests/test_ai_traversal_counters.py`: seven cases covering three persisted chains, selected-run publication-only/extraction-plus-publication/clean counters, and case/scope/unresolved identity separation. The run tests use deterministic HTTP mock responses; no live provider is involved.

Verification with repository `.venv/Scripts/python.exe`:

- `-m pytest tests/test_ai_traversal_counters.py -q`: **7 passed**, 3.54 seconds, exit 0.
- `-m pytest tests/test_ai_traversal_counters.py tests/test_ai_version_publication.py tests/test_ai_saved_publication.py tests/test_ai_linking_review.py tests/test_ai_operation_graph.py tests/test_ai_consolidation_review.py tests/test_ai_resumable_files.py tests/test_transformations.py tests/test_sql_transformations.py tests/test_sas_transformations.py tests/test_transformation_sas_integration.py tests/test_column_qol.py -q`: **150 passed**, 17.68 seconds, exit 0.
- `-m ruff check src ui tests scripts`: all checks passed.
- `git diff --check`: clean.

Limitations: previously materialized AI column rows require reanalysis/republication to acquire the corrected IDs; no automatic historical-data migration is introduced. Unresolved identities remain conservative boundaries. These tests demonstrate deterministic persistence/traversal and truthful bookkeeping, not live-model semantic accuracy. No paid/live provider calls, dependencies, framework, database or generation feature were introduced.

Final verification: `.venv/Scripts/python.exe -m pytest -q` — **1003 passed, 2 skipped**, 214.17 seconds, exit 0. Both skips remain the Windows symlink-privilege tests. `scripts/docs/build.py` passed strict validation of 42 public pages, 8 assets, local links/anchors, search and publication inventory (236 search entries). Lint and diff checks passed. No requested finding or validation remains incomplete.

Local implementation commit: `e585825` — link saved columns and count coverage. No push was performed.

## OmniRoute connection reliability follow-up

**Verified cause of the pause path:** the old scalar `Profile.timeout=30` applied to every HTTPX phase. Project analysis explicitly passed `retry_unknown_transports=False`; all `httpx.TransportError` subclasses were labelled unknown, so even a definitely pre-send connection failure paused for acknowledgement. The reported internal reason alone does not establish whether a real user's failure was a client read timeout, a gateway disconnect, proxy/protocol failure or another transport error. No live incident logs or provider calls were used to assert a specific network cause.

**Waiting and profile compatibility:** connect timeout is independently configurable (default 5 seconds, 0.05–60). Read inactivity uses `read_timeout` when set, otherwise the existing saved `timeout` (historical default 30); legacy `timeout` also remains the write timeout. The UI preserves fractional values and does not overwrite a saved timeout. Read inactivity is not a total deadline and should accommodate fallback plus generation. New OmniRoute creation defaults to read300/connect5/shared retries2/unknown retries2, unless explicit values are supplied. Existing profiles keep disabled automatic unknown recovery and their saved read fallback. Existing paused pins remain compatible with absent/default new fields. Changing profile options still invalidates a paused pin; configure before a new build or acknowledge retry without changing the pinned profile.

**One bounded recovery policy:** `retries` excludes the initial attempt. HTTP, pre-send, permitted unknown transport and item retries cannot exceed the shared allowance for an identical unfinished batch. `unknown_retries` is a subset cap, not an independent loop. Proxy/write/read/remote protocol failures remain potentially processed/billed; only connect/pool evidence is classified safe pre-send. Authentication and invalid provider responses do not enter a transient retry loop. Backoff remains cancellable. Automatic loops/restarts do not renew the allowance; explicit acknowledgement or continuation of known received-but-invalid work can renew bounded manual work, without resetting run-wide attempt/token/time limits. Completed parts are reused.

**Accounting, diagnostics and cancellation:** each dispatch receives a distinct persisted attempt and output reservation. Unknown attempts retain that status after later success; historical unknown/partial usage is recovered from the ledger even if a summary checkpoint lags. Received-but-uncheckpointed responses also consume uncertain recovery allowance. Diagnostics record only category, durable attempt/cycle numbers, elapsed time, effective timeouts, outcome, HTTP status and retry/exhaustion flags. They do not copy exceptions, credentials, headers or source. Project real sockets use monitored cancellable HTTPX I/O while buffering ordinary JSON; no model streaming/SSE is added. Guard checks run during silent waits and backoff, and the active app-side request closes before a retry. Closing it cannot prove upstream cancellation or zero billing. Messages describe this connection without claiming an unreported upstream provider switch or assuming gateway idempotency/status APIs.

**Regression evidence:** the initial gateway suite returned **10 failed** before implementation. Deterministic mocks and a local HTTP server now cover healthy delayed/simulated-fallback success on one gateway request, pre-send recovery, read timeout and partial disconnect, exhausted/disabled unknown retries, shared HTTP/transport budgets, authentication, cancellation/deadlines during waiting/backoff, run ceilings across restart, preserved unknown usage, no resend of completed batches and single publication. AppTest verifies new defaults, existing 83-second and fractional profile values, diagnostics and manual controls. There are **32 new collected cases** across `test_gateway_recovery.py` and `test_gateway_sockets.py`.

A fresh read-only review found a guard `ValueError` being misclassified as item failure and a fractional-timeout UI crash. Both were reproduced and fixed. Guard exceptions now escape response decoding; no automatic baseline reset occurs. A further failing regression proved that resetting after invalid model output allowed five sends under a three-attempt policy; the final shared budget stops at three. An intermediate full run had 1029 passed, 2 failed, 2 skipped; the completion-resume and UI-fixture failures were corrected, and final verification is recorded below.

Verification with repository `.venv/Scripts/python.exe`:

- `-m pytest tests/test_gateway_recovery.py tests/test_gateway_sockets.py tests/test_ai_resumable_files.py tests/test_ai_review_regressions.py tests/test_ai_analysis_transport.py tests/test_ai_analysis_ui.py tests/test_connections.py tests/test_provider_setup.py tests/test_ai_rate_limits.py -q --tb=short`: **97 passed**, 42.62 seconds, exit 0.
- `-m ruff check src ui tests scripts`: all checks passed.
- `scripts/docs/build.py`: strict build passed; 42 public pages, 8 assets, local links/anchors/search and 236 search entries validated.
- `git diff --check`: clean.

Remaining limitations: no real OmniRoute failover or live-model accuracy was measured. Local fallback timing is simulated, not evidence of any actual upstream switch. Unknown retries can duplicate upstream processing/charges; conservative reservations remain held. Request-local cancellation is not an upstream cancellation guarantee. New settings cannot recover a gateway that has exhausted its own candidates, and paused profile changes require a new build. No dependency, framework, database, schema migration or SQL-generation feature was introduced. No paid/live provider calls or pushes were made.

Final full-suite verification: `.venv/Scripts/python.exe -m pytest -q` — **1035 passed, 2 skipped**, 236.17 seconds, exit 0. Both skips remain unavailable Windows symlink privileges. All requested offline implementation and verification work is complete; real gateway behavior and live-model quality remain unmeasured.

Local implementation commit: `a75e81c` — bound gateway waiting and recovery. Documentation and verification are recorded in the accompanying documentation commit. No push was performed.


## Follow-up: optional wait-until-stopped � 2026-10-24

Added one opt-in profile setting, `wait_until_stopped`, and an admin checkbox. Cancellable AI requests use an unlimited HTTP read timeout while retaining bounded connection/write/pool timeouts. Existing profiles retain their previous timeout behavior. Setup/discovery calls without a cancellation callback remain bounded. Cancel and configured run ceilings still interrupt silent HTTP I/O; actual disconnections retain the existing bounded retry policy. Transport diagnostics now retain the exception class (never its potentially sensitive message), distinguishing an app read timeout from a disconnected gateway.

Socket regressions cover a response arriving beyond the configured inactivity timeout without a duplicate request, cancellation, run deadlines, and a real partial-response disconnect with retry. Profile tests cover round-trip and the bounded setup/discovery behavior.

Authorized live test: enabled the setting on the existing OmniRoute profile in `new_test`, using the running app's already-available credential and `auto/best-coding`. The workspace contained 2,114 SQL files (225 estimated initial requests). Previous gateway logs showed 499 outcomes around 30 seconds; the new first batch stayed open beyond that interval and successfully checkpointed 14 extracted parts, reporting 9,339 input / 12,503 output tokens, then began the next request. No secret or source content was copied into this document. This is transport/checkpoint functionality evidence, not a semantic accuracy evaluation or proof that the entire build completed.

Verification: full suite **1,042 passed, 2 skipped** in 297.39 seconds; the skips require Windows symlink privileges. The final bounded setup/discovery adjustment was independently checked by the final gateway/socket group (**39 passed** in 38.83 seconds). Provider/LLM/connection/resume group: **86 passed**. Ruff, diff checks, and strict documentation build passed. The user took over the ongoing live build after the first successful checkpoint; no full live-build completion is claimed.
