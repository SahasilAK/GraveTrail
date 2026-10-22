# Data model

DuckDB lives at `DATAFORGE_HOME/dataforge.duckdb`. Schema migrations are additive and execute
inside a transaction. Version 1 creates tables; version 2 adds statement source content hashes;
version 3 adds the compressed history recovery journal.
Version 4 adds temporary recovery; version 5 adds indexed column transformation facts.
Version 8 adds `dbt_projects`, `dbt_resources`, `dbt_relationships`,
`dbt_relation_bindings`, `dbt_evidence` and `dbt_project_snapshots`.
Logical dbt asset identity includes root/package/type/name/version; physical bindings
remain context-qualified metadata. Evidence records source hashes, offsets, origins and
optional JSON Pointers. Normalized snapshots retain historical source reachability.
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

## AI project analysis persistence

Migration 6 adds staged project analysis without deleting existing facts:

| Table | Responsibility |
| --- | --- |
| `ai_analysis_runs` | Workspace/run/mode, immutable manifest/configuration, stage/status/summary and compatible accepted results |
| `ai_analysis_units` | Original file/hash/character bounds, context identity, checkpoint status and linked LLM record |
| `ai_analysis_claims` | Minimal typed candidate payloads and accepted/rejected/unresolved decisions |
| `analysis_fact_support` | Typed fact provenance/support links |

Project network waits do not hold database transactions. Accepted facts and support publish with graph/column materialization after a freshness check; failure preserves the previous revision. Minimal accepted evidence is separate from opt-in full prompt/response history. Original operation evidence keys and sparse table pairs preserve same-line statements and prevent fabricated cross-pairs. See [AI project analysis](AI_ANALYSIS.md) for modes, validation and reuse boundaries.

## AI continuation snapshots (migration 7)

`ai_analysis_snapshots(run_id,workspace_id,file_id,part,content_hash,payload)` stores one bounded per-file header (`part=0`) plus operation parts. Operations reference exact spans in the immutable source blob. This replaces the aggregate `ai_analysis_runs.accepted_results` write limit; legacy JSON snapshots retain a fallback reader. The 16 MB per-record guard remains. Runs retain pinned request/configuration/protocol/publication identities and cumulative reservations. Unit stage checkpoints use compact host evidence/operation references; validated claims are per-claim rows. `awaiting_continuation` releases the active-run guard and retains the prior published graph.

Accepted claim payloads also retain compact source references with original encoding; detailed reports restore exact immutable quotes. Metadata-only reports omit payloads without reading source blobs. In-memory host operation metadata excludes duplicate fact arrays for wide projections.

AI source tasks also retain a bounded `unit_spec` in planned/staged unit rows. It pins original coordinates and optional projection bounds/ordinals without copying source text. Validated checkpoints retain reviewed candidate IDs after each review batch. Clean continuation reconstructs the same source plan and skips completed batches; partial task publication is not allowed. This uses the existing migration 6/7 tables and needs no additional migration.

Extraction protocol v4 expression references are transient model citations. The host resolves them to exact original expression text/coordinates before storing the existing compact canonical v2 payload; no new table or migration is required. Parser 14 / validator 4 and extraction prompt/schema hashes invalidate incompatible cached or paused work while preserving the previously published graph. Review remains protocol v2.


## Resumable AI analysis

Migration 9 adds `ai_analysis_requests`, `ai_analysis_attempts`, `ai_context_dependencies` and `ai_link_checkpoints`. They store request/item membership, independent dispatch outcomes/reservations, relevant source dependencies and staged link reports. They are included in cleanup, integrity and whole-home backup/restore. See [AI persistence and ownership](architecture/ai-analysis-pipeline.md#durable-state).

Adaptive source/context views extend unit_spec with an immutable source_focus range and indexed context interval. Validation checkpoints retain fragment identities, covered expression ranges, bounded inputs and reviewed component IDs. Compatible components are composed and validated against the complete original before becoming accepted facts. Large exact expression strings use checked _expression_source_span offsets in claim/checkpoint/snapshot JSON; legacy inline expressions remain readable. Typed support refresh hydrates those offsets, and detailed reports read each immutable source once. These additions reuse schema9 tables and require no migration.
