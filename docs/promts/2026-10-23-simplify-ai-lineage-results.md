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
