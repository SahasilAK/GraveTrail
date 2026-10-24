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


## Follow-up: optional wait-until-stopped — 2026-10-24

Added one opt-in profile setting, `wait_until_stopped`, and an admin checkbox. Cancellable AI requests use an unlimited HTTP read timeout while retaining bounded connection/write/pool timeouts. Existing profiles retain their previous timeout behavior. Setup/discovery calls without a cancellation callback remain bounded. Cancel and configured run ceilings still interrupt silent HTTP I/O; actual disconnections retain the existing bounded retry policy. Transport diagnostics now retain the exception class (never its potentially sensitive message), distinguishing an app read timeout from a disconnected gateway.

Socket regressions cover a response arriving beyond the configured inactivity timeout without a duplicate request, cancellation, run deadlines, and a real partial-response disconnect with retry. Profile tests cover round-trip and the bounded setup/discovery behavior.

Authorized live test: enabled the setting on the existing OmniRoute profile in `new_test`, using the running app's already-available credential and `auto/best-coding`. The workspace contained 2,114 SQL files (225 estimated initial requests). Previous gateway logs showed 499 outcomes around 30 seconds; the new first batch stayed open beyond that interval and successfully checkpointed 14 extracted parts, reporting 9,339 input / 12,503 output tokens, then began the next request. No secret or source content was copied into this document. This is transport/checkpoint functionality evidence, not a semantic accuracy evaluation or proof that the entire build completed.

Verification: full suite **1,042 passed, 2 skipped** in 297.39 seconds; the skips require Windows symlink privileges. The final bounded setup/discovery adjustment was independently checked by the final gateway/socket group (**39 passed** in 38.83 seconds). Provider/LLM/connection/resume group: **86 passed**. Ruff, diff checks, and strict documentation build passed. The user took over the ongoing live build after the first successful checkpoint; no full live-build completion is claimed.

## Progressive extraction recovery — 2026-10-24

Implemented from `02c8d6d` on the existing branch. The working tree was clean at entry;
the committed **Wait until stopped** changes were preserved. No source data, provider
configuration, credentials or routing was changed. No paid/live model calls or push.

### Confirmed causes and diagnostic limits

The coordinator previously aborted the whole build when any required part accumulated
two invalid results (`missing_or_invalid_required_extraction`). It collapsed decode
errors into `invalid_extraction_response` and source/internal validation errors into
one generic code. Thus the observed stop is an extraction/recovery decision, not
evidence of a read timeout. The live DuckDB file was locked by the running app when
opened read-only; it was not copied, unlocked or modified. The precise original
model-output defect in the reported 2,114-file / 14-saved-part run cannot be reconstructed
from available evidence. Missing IDs, malformed schema/citations, truncation and
provider normalization are tested possible causes, not asserted live-run causes.

The 8,192-token recommendation is not a runtime dispatch cap. Locked live records
prevented verifying whether it limited that run. It remains a conservative profile
recommendation; configured output allowance and advertised model capacity now appear
separately with actual request packing diagnostics. Gateway-wide advertised maxima
are not assumed valid for every routed model. The conservative UTF-8 fallback remains.

### Recovery behavior

- Valid siblings are durably saved; only unsuccessful items enter smaller corrective
  batches, eventually singletons. Safe host codes and bounded schema paths accompany
  retry. Unknown response IDs are recorded without copying their supplied value.
- Recovery state, failure/pass count, width and next eligible wall time live in the
  existing run summary. Fresh pending work proceeds first. Each HTTP/transport pass
  retains finite shared/subset allowances; another pass follows durable backoff
  (1–60 seconds). Restart does not reset pass history or run spending ceilings.
- Persistent required failures remain visibly waiting with Cancel available. There is
  no elapsed-time default cutoff, silent skip, fabricated `no_operations` or incomplete
  required-work publication. Unknown-outcome retry remains opt-in. Authentication,
  quota/credits, authorization, source/configuration, storage and explicit run ceilings
  remain blockers; irreducible corrective request sizes require a budget change.
- Truncated batches first reduce width. A singleton source part can subdivide once
  on a natural boundary or a sufficiently long contiguous range. Exact cores,
  bounded disclosed overlap, parent/child IDs and context persist across reopening.
  Repeatedly truncated children wait for repair instead of recursive halving.
- Initial/enrichment sizing reserves bounded corrective feedback through the actual
  request builder. Smaller eligible items can fill room after a non-fitting later
  candidate; the first eligible item retains priority. Diagnostics expose input,
  expected output, disclosure limits, utilization and reserved output.
- Completion/consolidation failures retain initial validated details. Consolidation
  groups from all files share one pending set. Membership freezes as references to
  saved operation hashes before requests; old started stages retain their original
  grouping, preventing repeated calls or supersession. Interrupted planning never
  checkpoints a partial group list. Restored source parts recover their exact pinned
  definition IDs, evidence and fingerprint despite changed fitting boundaries.
- Per-request journals retain safe stage/request/part IDs, failure code/path, attempt,
  recovery action, whitelisted finish/usage metadata and output budgets. Reports/UI
  show the latest 20 request records plus pending recovery; earlier records remain in
  the database. No raw rejected responses, arbitrary exception messages or source are
  added to diagnostics. Null, malformed, negative and partial token usage stays unknown.

### Regression evidence

The first eight regressions failed before implementation: six invalid-item recovery
variants, persistent cancellation/reopen, and packing around a non-fitting candidate.
Additional tests reproduced corrective feedback overflowing input (one failure),
consolidation blocking later files (one), changed resume ranges dropping pinned
definitions (one), invalid/partial usage incorrectly claiming known counts (three),
changed legacy consolidation groups repeating supersession (one), and an interrupted
planner freezing only some groups (one). Each received its targeted fix.

`test_ai_extraction_recovery.py` now has 24 mock cases covering these boundaries,
including missing/duplicate/unknown IDs, JSON/envelope/schema/citation failures,
saved siblings, shrinking batches, safe feedback, persistent backoff, cancellation,
reopen, explicit attempt/output ceilings, source-range/overlap preservation, bounded
splitting, enrichment retention, consolidation fairness and exactly one publication.
Existing abort-oriented tests now use explicit spending ceilings or cancellation at
backoff while retaining strict ledger/previous-graph/source-validation assertions.
A fresh read-only reviewer reproduced the context/group migration defects; the final
review found no further actionable issues and reran the three migration/planning tests.

### Verification and commits

All commands used repository `.venv/Scripts/python.exe`; all model transports were
mocked or local test HTTP servers.

- `-m pytest tests/test_ai_extraction_recovery.py -q --tb=short`:
  **24 passed**, 16.63 seconds, exit 0.
- `-m pytest tests/test_ai_extraction_recovery.py tests/test_ai_consolidation_review.py tests/test_ai_resumable_files.py tests/test_ai_review_regressions.py -q --tb=short`:
  **40 passed**, 20.44 seconds, exit 0.
- `-m pytest -q --tb=short` on the final implementation:
  **1,066 passed, 2 skipped**, 297.51 seconds, exit 0. Both skips are existing
  unavailable Windows symlink privileges. An earlier full run, before the final
  consolidation migration/planning follow-ups, passed 1,064 with the same two skips.
- `-m ruff check src ui tests scripts`: **All checks passed**, exit 0.
- `scripts/docs/build.py`: strict build passed; **42 public pages, 8 assets,
  rendered local links/anchors and 236 search entries** validated, exit 0.
- `git diff --check`: passed. The pre-existing single CP1252 em-dash byte in this
  results document was normalized to UTF-8 while preserving its text.

The final broad linking/publication/graph/transformation/gateway/UI group passed
**154 cases**, 80.03 seconds, exit 0:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_ai_extraction_recovery.py tests/test_ai_context_index.py tests/test_ai_context_completion.py tests/test_ai_consolidation_review.py tests/test_ai_resumable_files.py tests/test_gateway_recovery.py tests/test_gateway_sockets.py tests/test_ai_analysis_ui.py tests/test_ai_linking_review.py tests/test_ai_version_publication.py tests/test_ai_traversal_counters.py tests/test_ai_operation_graph.py tests/test_ai_saved_publication.py tests/test_transformations.py -q --tb=short
```

`scripts/qualify_ai_context.py --files 1000 --family all` completed with exact golden
table/column/file relationships and interruption/reopen reuse in all families:

| Family | Source files | Parts | Requests | Maximum sent input | Reserved output | Table/column/file correct | Seconds | Peak Python bytes |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| SQL | 1002 | 1003 | 38 | 47558 | 304000 | 1002/2004/999 | 104.328 | 114712904 |
| SAS | 1002 | 1003 | 38 | 28379 | 304000 | 1002/2004/999 | 81.156 | 61039836 |
| dbt | 1002 | 1003 | 42 | 57488 | 336000 | 1000/2000/999 | 411.938 | 104884584 |

All scheduled source coverage was processed. SQL/SAS retained two duplicate-writer
boundaries each. dbt retained two source-context uncertainty records (2/1002), with
zero missing/false-positive golden relationships. Mock provider tokens/cost remain
unavailable. This scale command started before the final frozen-membership follow-up;
the final full suite includes final-code per-family golden/reopen and targeted
legacy-group migration/planning coverage. No live semantic qualification is implied.

Local implementation commit: `9cb6027` — recover failed extraction work durably.
Documentation and this evidence are in the following documentation commit. No push.

### Remaining limits

These results qualify deterministic mocks/local HTTP sockets and the existing
publication stack. They do not establish live-model precision, recall, routing
reliability or token cost. The original live response defect and actual 8,192-token
bottleneck remain unverified. No full 2,114-file live retry was launched. Required
failures may continue incurring configured, authorized attempts until cancelled or
an explicit ceiling is reached; unknown reservations remain even after success.
Irreducible context groups retain existing explicit uncertainty/budget handling.
No new database, dependency, generic workflow layer, generation or optimization.

## Context-management implementation — 2026-10-24

This section records the latest approved amendment and supersedes the earlier
fixed-output recommendation and indefinite required-work recovery policy above.
Work started from clean HEAD `63dc6dd` on `codex/resumable-ai-lineage`, preserving
the branch's earlier identity, traversal, recovery and cancellation fixes. No push,
paid/live provider call, gateway route change or full live workspace retry occurred.

### Reproductions and changes

- The automatic recommendation used `min(8192, output_capacity)`. New allocation
  regressions initially failed because the model-share allocator did not exist;
  UI coverage then failed on the absent slider. `allocate_analysis_profile` now
  derives a run-only profile from a pinned 10–50% output share (default 30%). It
  reserves safety and applicable shared-context reasoning once, clamps output to
  the real output maximum, and gives input the remaining usable capacity subject
  to its own cap. Separate windows keep input independent and map the percentage
  to independent output capacity. Unknown shared context is blocked; optional
  unreported output limits remain explicit uncertainty. Dynamic routes require
  existing manual safe-capacity confirmation.
- The UI shows effective allowances, route/model capacities and provenance, clamp
  explanations and optional Advanced exact overrides. Explicit run output overrides
  precede saved Custom output allowances; otherwise Custom caps the slider.
  Automatic profiles use model-aware recommendations; saved profiles and source
  disclosure limits are unchanged. UI/CLI/MCP share the allocator. Run requests
  persist share/overrides; resume rejects allocation changes and preserves legacy
  checkpoint allocation/hash behavior.
- A new regression exposed that binding credentials to the derived profile lost
  an existing session credential (`Configured provider credential is unavailable`).
  Credential lookup now uses the original saved profile, while sizing and dispatch
  use derived allowances. The regression passes without persisting credentials.
- Full-envelope counting and the existing independent wire builder were reused.
  Provider wire regressions verify fresh current-batch messages/contents, stable
  instructions and provider-specific maximum-output parameters, with no preceding
  response, conversation/continuation ID or accumulating summary. Relevant indexed
  definitions remain available; no project-wide synthesis pass was added. Prefix
  caching remains compatible. Gateway-internal memory remains outside this proof.
- Existing packing already fits smaller eligible items after a budget miss and
  rotates failed work behind fresh work. It still requires both actual request
  input and estimated structured output to fit. Diagnostics now also expose file/
  part counts, input estimate/allowance, counting method and the output-estimate
  method alongside utilization and stopping reasons. The conservative unknown-model
  counter and crude output estimate (256 per item plus half its actual source or
  saved-detail UTF-8 bytes) are unchanged; there is no runtime ratio learning.
- New recovery regressions failed before the fix by reaching cancellation instead
  of partial publication. After three unsuccessful item passes, the coordinator
  now persists host-owned unresolved/partial records, continues other work and
  publishes available validated lineage with explicit incomplete coverage. It never
  fabricates `no_operations`. Valid siblings, ranges, definitions, evidence and
  operation identities remain saved. Unresolved initial work marks its file
  unprocessed; failed enrichment retains initial facts and missing-context evidence.
- A committed partial run can explicitly retry only unresolved work after reopening.
  Successful checkpoints, frozen groups and supersessions are reused; cumulative
  attempt/output accounting and unknown usage are retained. The prior-publication
  pin advances only to this run's own partial publication. Regression tests reject
  changed source/configuration or an intervening publication before dispatch.
- Deliberate stage rule: initial required failures defer freezing the one completion
  wave; initial/completion failures defer consolidation until repair. This avoids
  freezing incomplete inputs or adding recursive AI passes. Partial views may retain
  unconsolidated details. This rule is recorded in the approved plan and guides.
- Reports persist `unresolved_parts` (deferred required work items) and
  `unprocessed_files` (files with unresolved initial extraction), separately from
  existing semantic-coverage counters. A further regression reproduced a cancelled
  report claiming publication merely because work was deferred. The message now
  requires committed status and preserves the cancellation explanation otherwise.

### Regression coverage and review

`test_ai_budget_allocation.py` adds 24 cases: 70k/200k/1M allocations at 10/30/50%,
input/output clamps, shared/separate windows, safety/reasoning/full-envelope counts,
slider/Custom/Advanced precedence, dynamic manual confirmation, UI/CLI/MCP parity,
preview/dispatch agreement, independent provider payloads, bound session credentials,
missing capacities and legacy close/reopen reuse. The default shared examples are:

| Context | Safety | Maximum output | Effective input |
| ---: | ---: | ---: | ---: |
| 70,000 | 3,500 | 19,950 | 46,550 |
| 200,000 | 10,000 | 57,000 | 133,000 |
| 1,000,000 | 50,000 | 285,000 | 665,000 |

These examples assume no lower model/explicit cap or separate reasoning reserve.
`test_ai_partial_recovery.py` adds seven cases: bounded partial publication and
persisted counters, successful sibling reuse after close/reopen, failed completion
retention/retry, large-file ranges/retained facts/deferred consolidation, three
freshness blockers and the pre-publication recovery-message regression.

A fresh read-only reviewer found no Critical or Important findings. Its additional
deterministic SAS mock integration completed context supersession, failed one
consolidation group three times, published partial results, reopened the store and
retried exactly that group once. It verified stable frozen input hashes, reuse of
completed enrichment and cleared unresolved flags. No repository edits or live calls.

### Verification evidence

Commands use repository `.venv/Scripts/python.exe`; transports are deterministic
mocks or local test HTTP servers. The first full run reported **1,094 passed,
2 failed, 2 skipped**, 342.19 seconds. Both failures were documentation parity
checks for the newly exposed CLI/MCP budget fields; the reference tables were then
updated. The cancellation-message regression failed before its one-line guard fix;
its seven-case recovery file then passed in 11.19 seconds.

The broad focused regression command passed **241 cases**, 136.49 seconds, exit 0:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_ai_budget_allocation.py tests/test_ai_partial_recovery.py tests/test_ai_analysis_ui.py tests/test_ai_token_budget.py tests/test_ai_context_completion.py tests/test_ai_consolidation_review.py tests/test_ai_extraction_recovery.py tests/test_gateway_recovery.py tests/test_gateway_sockets.py tests/test_ai_linking_review.py tests/test_ai_operation_graph.py tests/test_ai_traversal_counters.py tests/test_transformations.py tests/test_sql_transformations.py tests/test_sas_transformations.py tests/test_ai_build_policy_interfaces.py tests/test_documentation.py -q --tb=short
```

Additional saved-publication, versions, split-file/consolidation, resume, access and
dbt checks passed **34 cases**, 20.02 seconds, exit 0:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_ai_version_publication.py tests/test_ai_saved_publication.py tests/test_ai_file_parts.py tests/test_ai_file_consolidation.py tests/test_ai_resumable_files.py tests/test_ai_analysis_access.py tests/test_dbt_ai_analysis.py -q --tb=short
```

Final full-suite command `-m pytest -q --tb=short` reported **1,096 passed,
1 failed, 2 skipped**, 552.92 seconds, exit 1. The remaining failure is
`test_palette_choices_preserve_ocean_and_ink_and_default_to_ocean`: it asserts the
working `.streamlit/config.toml` is Ocean dark, while the unrelated current working
configuration selects Crimson Forge. That edit was preserved and excluded from
the commits; no theme code or assertion was changed. The identical test passed
against `git show HEAD:.streamlit/config.toml` in an isolated temporary working
directory: **1 passed**, 0.09 seconds, exit 0. This isolates the configuration
failure; it does not turn the full-suite run into a passing run. The two skips are
the existing unavailable Windows symlink-creation privileges. No AI lineage,
publication, static-parser or recovery tests failed in the final full suite.

- `-m ruff check src ui tests scripts`: **All checks passed**, exit 0.
- `scripts/docs/build.py`: strict build passed; **42 public pages, 8 assets,
  all rendered local links/anchors and 236 search entries** validated, exit 0.
- `git diff --check` and staged diff checks: passed. Affected knowledge maps were
  refreshed using the incremental scan; no unrelated theme changes were staged.

The current-code large-context mock qualification passed:

```powershell
.venv/Scripts/python.exe scripts/qualify_ai_context.py --files 100 --family all --context-tokens 1000000 --output-tokens 285000
```

| Family | Source files/parts | Requests | Maximum sent input | Reserved output | Table/column/file correct | Seconds | Peak Python bytes | Saved bytes |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| SQL | 102/102 | 1 | 166,732 | 285,000 | 102/204/99 | 17.750 | 54,597,049 | 237,838 |
| SAS | 102/102 | 1 | 100,127 | 285,000 | 102/204/99 | 12.579 | 6,821,488 | 237,838 |
| dbt | 102/102 | 1 | 244,864 | 285,000 | 100/200/99 | 20.500 | 11,773,822 | 242,358 |

All scheduled ranges processed; expected relationship precision/recall and evidence
validity were 1.0 against the independent golden mocks. SQL/SAS retained two
duplicate-writer boundaries each. This one-request configuration did not exercise
mid-run interruption; targeted recovery tests and full-suite per-family fixtures
cover interruption/reopen. Provider token usage and cost are unavailable. Historical
1,000-file-per-family qualification above was not rerun for this amendment.

### Remaining limitations

Mock qualification demonstrates request construction, budgeting, persistence,
recovery and deterministic linking; it does not establish live-model precision,
recall, actual token use, latency, gateway fallback capacity or internal memory.
No live evaluation was authorized or performed. Conservative input/output estimates
can underuse capacity; large maximum output reservations can hit explicit run
ceilings sooner. Missing provider output limits remain unverified and explicitly
labelled. Irreducible context groups remain unresolved; a failed initial/completion
stage delays enrichment even for otherwise available saved facts. No dependencies,
framework, database, adaptive learning, SQL generation or optimization were added.
The complete working-state suite retains the unrelated theme-default failure
described above; it has not been hidden, skipped or weakened.

Local implementation commit: `09e42ad` — pin model budgets and bounded recovery.
The plan, user guides, knowledge maps and this evidence follow in the documentation
commit. No push was performed.

## Slider and Analyze progress follow-up — 2026-10-24

The user reported fixed 28,774 input / 8,192 output allowances and missing progress/
Cancel after Analyze. Regressions failed before implementation: one Analyze click
called the expensive preview three times, and explicit slider movement retained the
saved Custom output default. A hard model-cap case also lacked a clear plateau
explanation. All three initial regression cases failed before the fixes.

### Focused changes

- Moving the slider explicitly selects this run's output allowance through the
  existing request override; Advanced exact values and real model limits still
  take precedence. Saved profiles are untouched. At declared model limits, effective
  values can correctly plateau; the UI now explains this. The backend allocator,
  model-cap rules, source disclosure and resume pins remain unchanged.
- Successful offline previews are reused only in the same session with matching
  home, request, source inventory, settings/profile, current capacity metadata and
  credential availability. Invalid previews are not cached. Source reimport, settings,
  profile or request edits invalidate reuse. Execution still prepares and validates
  its own fresh inputs; the preview grants no source/network authority.
- The active progress fragment and Cancel render before inventory/preparation.
  Nonterminal jobs skip the build controls, so preparation cannot hide cancellation.
  Budget widgets persist while hidden and return after completion/cancellation.
  Tests exercise Analyze → active progress → Cancel → restored controls without
  another preview or an inventory read on the active path.

### Verification

Commands use `.venv/Scripts/python.exe`:

- `-m pytest tests/test_ai_analysis_ui.py tests/test_ai_budget_allocation.py tests/test_ai_preparation.py -q --tb=short`:
  **37 passed**, 105.11 seconds, exit 0 (before the additional cache-invalidation
  case and extended restored-control assertion).
- `-m pytest tests/test_ai_analysis_ui.py tests/test_ai_budget_allocation.py tests/test_ai_preparation.py tests/test_ai_analysis_jobs.py tests/test_ai_partial_recovery.py tests/test_gateway_recovery.py tests/test_gateway_sockets.py -q --tb=short`:
  **84 passed, 2 failed**, 240.86 seconds. Both failures are existing accelerated
  socket-deadline cases: their deadline expired before dispatch, leaving zero sends.
  The transport/backend implementation is unchanged by this UI patch.
- `-m pytest tests/test_ai_analysis_ui.py tests/test_navigation_redesign.py tests/test_ui.py tests/test_workflow.py -q --tb=short`:
  **27 passed**, 182.84 seconds, exit 0, including the final restored-control
  assertion and source/settings/profile/request cache invalidation.
- Isolated rerun of both `[False-deadline]` / `[True-deadline]` silent-socket cases:
  **2 failed**, 21.37 seconds; one exceeded the two-second wall-clock assertion
  (2.625 seconds), the other again expired before sending. Assertions were not
  changed or skipped. These timing-sensitive failures remain reported.
- `-m ruff check src ui tests scripts`: **All checks passed**, exit 0.
- `scripts/docs/build.py`: strict build passed, **42 public pages, 8 assets,
  rendered links/anchors and 236 search entries** validated, exit 0.
- `git diff --check`: passed. Knowledge maps refreshed incrementally. The unrelated
  `.streamlit/config.toml` edit remains excluded. Full suite was not repeated for
  this UI-only follow-up; the preceding full-suite result remains historical.

### Authorized LM Studio check and remaining limitation

The user explicitly authorized testing `http://127.0.0.1:1997/v1`, model
`qwen/qwen3.5-9b`, context 38,912, and instructed stopping on connection trouble.
Discovery succeeded and listed the requested model. An isolated synthetic SQL
workspace used that endpoint without changing existing workspaces/profiles. The
AppTest drove the actual UI and real background worker with retries disabled and
one physical attempt permitted:

- Initial allowances reproduced **28,774 input / 8,192 output**.
- Moving to 50% yielded **18,483 input / 18,483 output**, retaining the saved
  8,192 Custom profile default unchanged.
- Analyze displayed running progress with **Cancel visible in 1.25 seconds**.
- The single generation request returned **HTTP 400**. The run paused with
  `http_failure`, no graph was published, and usage remained unknown. Live calls
  stopped; the LM Studio server-log rejection reason was requested from the user.

This verifies the narrow live UI transition and endpoint discovery, not successful
live extraction, cancellation of a live generation, or model accuracy. No retry,
full 2,114-file analysis, route change or additional model call was made after the
400. Further provider diagnosis requires the server's error reason. All other
verification used deterministic mocks/local test sockets.
## AI analysis visibility — 2026-10-24

Phase 1 adds a lightweight projection of existing run, request, attempt and unit checkpoints, early worker/run association, bounded activity and shared live/final status rendering. Active polling stays before inventory/preparation. Cancellation remains visible until acknowledgement; source evidence hydration is deferred until expansion.

Phase 1 verification: `python -m pytest tests/test_ai_analysis_visibility.py tests/test_ai_analysis_ui.py tests/test_ai_partial_recovery.py tests/test_ai_extraction_recovery.py tests/test_ai_analysis_jobs.py tests/test_ai_resumable_files.py -q`: **49 passed in 20.94s**. Commit: `98b6f18`.

Phase 2 adds actual HTTPX body capture at the existing transport boundary, before normalization, through the same extraction/completion/consolidation/retry loop. Captured provider response, decoded structured results, validation failures and recovery decisions are separate. Inputs and Outputs render lazily by request/attempt ID, with 20-item lists, 16,000-character content pages and deferred full-retained-content download. No headers/URLs are retained; registered/request/environment credentials and sensitive JSON fields are redacted in a copy. Dispatch bodies are unchanged.

Privacy remains opt-in through `llm_history`. The separate migration-10 `ai_inspection_artifacts` table has 4 MiB/artifact, 64 MiB/run and min(workspace retention, seven days) limits. Startup/capture cleanup expires content and removes orphaned run artifacts; reads deny expired or disabled content immediately. Existing AI/workspace/source/lineage cleanup and backup/restore include the new table. Historical/disabled/oversized/non-UTF-8/expired bodies have explicit Not retained outcomes; no approximate payload is reconstructed. Saved validated checkpoints and publication remain independent of capture retention.

The initial full-suite baseline was **1114 passed, 2 skipped, 1 failed** in 271.13s. The preexisting failure is `tests/test_themes.py::test_palette_choices_preserve_ocean_and_ink_and_default_to_ocean`: the preserved user config selects Crimson Forge instead of Ocean dark. No assertions or config were changed to hide this failure. An intermediate run exposed migration compatibility failures; the schema-version assertion was updated to 10 and legacy backups without column migration 5 remain accepted. A later full suite reported **1133 passed, 2 skipped, 1 existing theme failure** in 280.55s; final verification follows below.

An independent read-only review identified source-bearing completion metadata in polling, a lock wait that could delay Cancel, and unexpected preparation failures leaving active runs. Each received a failing regression and fix; re-review found no additional actionable issues (**27 focused tests passed independently**). New regressions also cover actual async I/O through a mocked AsyncClient transport, including cancellation while waiting, unknown outcomes, early identity, growing totals, partial resume/reuse, historical missing artifacts, privacy/retention, malformed/error bodies, lazy selection and migration/backup cleanup. Live and final durable counters reconcile across store reopen.

Reused/refactored: existing jobs/heartbeat/cancel markers, durable run/request/attempt/unit ledger, recovery diagnostics and controls, provider adapter, safe redaction, source evidence, checkpoints and atomic publication. Replaced duplicate final-only metrics with shared status/diagnostic helpers; deferred previously eager source evidence. No new dependency, framework, pipeline semantics or resource/lineage identity change.

Manual UI verification selected the existing `small` workspace (86 SQL files), opened its saved cancelled report and historical input inspection. The running app's cached connection needed refreshing for migration 10. No new analysis or provider call was started. Existing LM Studio HTTP 400 remains unresolved and live-model accuracy remains unverified. All execution tests used mocks; no paid calls or pushes.

### Final visibility verification

All commands used the repository `.venv/Scripts/python.exe` on Windows:

```text
-m pytest tests/test_ai_analysis_visibility.py tests/test_ai_inspection.py tests/test_ai_inspection_ui.py tests/test_ai_analysis_ui.py tests/test_ai_analysis_jobs.py tests/test_ai_partial_recovery.py tests/test_ai_extraction_recovery.py tests/test_ai_resumable_files.py tests/test_ai_analysis_transport.py tests/test_dbt_store.py tests/test_dbt_maintenance.py tests/test_maintenance.py -q
92 passed in 46.30s

-m pytest -q
1 failed, 1136 passed, 2 skipped in 282.65s

-m ruff check src ui tests scripts
All checks passed!

scripts/docs/build.py
Strict build passed; 42 public pages, 8 assets, local links/anchors, search and publication inventory validated (239 search entries).
```

The sole final failure remains `tests/test_themes.py::test_palette_choices_preserve_ocean_and_ink_and_default_to_ocean` (Crimson Forge in the unchanged user configuration versus expected Ocean dark). No new failing tests remain. The database migration assertion now checks version 10 explicitly; no acceptance assertion was relaxed. No production artifact/package build or live-model evaluation was performed. Logical retention cannot erase existing backups or guarantee immediate physical database shrinkage. Elapsed time is the current worker execution; attempt/reservation totals survive resume.

