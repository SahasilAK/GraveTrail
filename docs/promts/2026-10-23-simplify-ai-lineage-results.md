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
