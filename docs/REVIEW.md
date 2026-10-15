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

Validation after fixes: 56 automated tests pass, Ruff clean. Injected post-write failure proves
DuckDB materialization rollback. No live provider test was judged without endpoint/credentials.
Packaging/docs/performance were still in progress during review and are verified separately.
