# Data model

DuckDB lives at `DATAFORGE_HOME/dataforge.duckdb`. Schema migrations are additive and execute
inside a transaction. Version 1 creates tables; version 2 adds statement source content hashes;
version 3 adds the compressed history recovery journal.
Version 4 adds temporary recovery; version 5 adds indexed column transformation facts.
Do not edit schema destructively or delete runtime data to resolve a migration error.

```mermaid
erDiagram
  workspaces ||--o{ source_files : inventories
  workspaces ||--o{ analysis_runs : analyzes
  ingestion_runs ||--o{ source_files : imports
  source_files ||--o{ statements : contains
  statements ||--o{ operations : describes
  operations ||--o{ operation_assets : reads_writes
  assets ||--o{ operation_assets : participates
  operations ||--o{ edges : produces
  assets ||--o{ column_usages : referenced_directly
  statements ||--o{ column_usages : proves
```

| Table | Responsibility |
|---|---|
| workspaces, settings | Independent named contexts and JSON settings |
| ingestion_runs | Source/import diagnostics, accepted/skipped/duplicate counters |
| source_files | Stable path IDs, full decoded text, byte hash, blob reference, encoding, status, metadata |
| parse_cache | Parser version + hash + path + config results; safely disposable |
| analysis_runs | Status, duration, counts, config and comparison snapshots |
| history_archives | Workspace-bound compressed recovery bodies, original byte size and creation time; committed atomically with history removal |
| assets, asset_aliases | Stable canonical identities, display names, kind, temporary flags and resolution notes |
| statements | Exact statement snippet, original line range, file ID and source version hash |
| operations, operation_assets | Explicit transformation nodes with many-to-many input/output memberships |
| edges | Derived input/output relationships with method, confidence, status and evidence keys |
| column_usages | Scope-local direct column references and expression context |
| column_references | Workspace/asset/column identity, quote-aware case rules, statement scope and derived variable version |
| column_derivations | One target per expression, category/status, branch/position, source operation and committed analysis revision |
| column_dependencies | Zero-to-many input columns or relation contexts with dependency roles |
| column_analysis | Last committed transformation revision/parser version; absence means reanalysis required |
| diagnostics | Parse failures, ambiguity and unresolved symbols with file/line |
| llm_profiles | Provider config and environment variable names, never credentials |
| llm_records, prompt_versions | AI provenance, validation outcomes, usage, prompt hashes and durable merged claims |

IDs derive from workspace/path, normalized asset identity or operation identity. UI services
filter by workspace. Original blobs may be shared by hash; workspace deletion leaves blobs
intact to avoid deleting content referenced elsewhere. There are no destructive FK cascades;
the materialization service owns cross-table transaction integrity.

History maintenance archives only unreferenced analysis/import records, preserving the latest
completed analysis, current edge/inventory references and running analyses. Recovery JSON has
a canonical SHA-256 integrity check; a compressed copy is journaled in the same DuckDB transaction
as removal. Local JSON files provide an additional recovery copy. Restore inserts missing IDs
transactionally without replacing current facts or existing history. Both copies are retained.

Migration4 adds temporary_recovery (workspace, file name, compressed bytes, original size,
SHA256 and created/restored timestamps). Bytes commit before stale staging-file removal.
Recovery journals are not metadata-transfer payloads and are deleted only with explicit
workspace deletion. This table never authorizes cleanup outside its application namespace.

Column IDs include exact resolved asset/job identity and a shared quote-aware column key.
Equivalent quoted and unquoted spellings share identity, while quoted case is preserved;
quoted literal names such as `"*"` remain distinct from wildcard/rowset markers. Declared
schemas retain original `column_identifiers` alongside unchanged name/type `columns` fields.
Intermediate scopes
and variable versions include immutable statement identity; they attach to an existing
asset without adding CTE tables to the table graph. Physical columns can have multiple
writer alternatives, which traversal does not combine into an assumed execution history.
Constants have a derivation with no value dependencies. Original expressions and the
statement content hash remain separate from display explanations. All column tables
participate in workspace cleanup and full-home recovery; integrity inspection checks their
asset, statement, input, derivation and analysis references. See
[transformation lineage](TRANSFORMATION_LINEAGE.md).
