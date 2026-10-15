# Implementation review, 2026-10-15

An independent read-only reviewer inspected parsers, persistence, privacy and graph workflows.
The author added regression tests, reproduced each material finding, and fixed the following:

- Immutable inventory snapshots prevent concurrent imports from pairing new code with old hashes.
- Statement hashes pin source views and downloads to analyzed original bytes after reimport.
- CSV width is bounded before field-list allocation; malformed headers are file diagnostics.
- Quoted identifiers retain component boundaries (`"raw.orders"` differs from `raw.orders`).
- AI history retention prunes interaction bodies but retains minimal merged lineage evidence.
- Unused CTEs do not contribute dependencies or direct columns.
- SAS macro control blocks and unsupported name literals cannot fabricate unconditional edges.
- SAS DATALINES/CARDS payloads are skipped as data rather than parsed as code.
- LLM claims must bind reads and writes within one statement or a supported SAS block.
- Import stops reading after the total byte budget; ZIP symlink/ratio tests pass.

Validation after fixes and final regression expansion: 62 automated tests pass, Ruff clean. Injected post-write failure proves
DuckDB materialization rollback. No live provider test was judged without endpoint/credentials.
Packaging/docs/performance were still in progress during review and are verified separately.

## Continuation review — 2026-10-15

A fresh read-only reviewer checked gateway JSON, workspace configuration, lazy trees/path
exports and the new schema processing. Three material findings were independently reproduced:

- Unqualified ALTER declarations used a different identity from qualified lineage assets.
  Reconciliation now uses the same resolver; ambiguous DDL invalidates possible candidates.
- Snowflake SWAP invalidated only its first operand. SWAP/RENAME now invalidates both.
- Deep JSON could raise RecursionError outside quarantine. Both model content and HTTP
  envelopes now normalize decoding recursion failures into handled errors.

Failing regressions preceded fixes. The complete suite then passed 100 tests with Ruff clean.
Tests include unique/ambiguous unqualified changes, SWAP/RENAME, deep HTTP JSON and persisted
quarantine records. Live automatic model routes still occasionally return invalid output;
that is rejected and is not reported as a fully green live integration.

## History maintenance review — 2026-10-15

A separate read-only reviewer identified that file fsync followed by rename alone did not
guarantee durable directory publication before database removal on all supported platforms.
Recovery now has a compressed database journal committed atomically with the metadata removal.
The local JSON copy is additional recovery rather than the sole durability dependency.
Regression tests remove the published file, restart the Store and restore from the journal.
Physical power-loss behavior was not exercised. Other tests cover migration preservation,
workspace isolation, active-reference protection, bounded batches, integrity validation,
idempotent restore and injected archive/restore transaction failures. Actual Settings browser
verification archived and restored three analysis records while active imports stayed protected.

## Visualization review — 2026-10-15

Independent read-only review found that estimating SVG text width from character count could
let wide glyphs spill out of full-name nodes. Rendering now measures the actual text and fits
it to the available width. No material findings remained after that fix; extra temporary-home
checks verified unsaved preferences and selected source IDs across workspace switches.

Author browser verification also caught a ShadowRoot mount without `.style`; styling now
targets the contained graph element, with a failing-then-passing Node regression. AppTest
exposed stale asset IDs under key-based selectbox identity; absent asset/source choices are
cleared before constructing the widget. Graph appearance, source preferences, evidence and
offline graph JSON were checked after a server restart. Full suite: 120 tests, Ruff clean.
