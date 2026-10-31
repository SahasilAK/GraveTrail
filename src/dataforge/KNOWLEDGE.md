# src/dataforge/

Offline lineage, persistence, authorized automation and optional provider analysis. Keep UI
imports out of this package. Current Store migration: **10**; parser/publication version: **21**;
project AI: **file extraction protocol 5**. Historical readers/migrations remain supported.

## Subfolders
- `agent/` — CLI/MCP adapters, permissions and jobs; [map](agent/KNOWLEDGE.md).
- `dbt/` — Safe project/artifact inventory, identities and evidence; [map](dbt/KNOWLEDGE.md).
- `parsers/` — Static SQL/SAS/CSV and transformations; [map](parsers/KNOWLEDGE.md).
- `tokenizer_assets/` — Packaged offline tokenizer data.

## Core analysis and storage
- `column_graph.py` — Bounded source-free column scenes, whole-derivation display caps and cycle-aware layout.
- `column_evidence.py` — Workspace/run-validated lazy expression and exact analyzed-source lookup.
- `services.column_usage_coverage` — Source-free freshness/diagnostic/wildcard coverage; unused names require complete direct usage.
- `models.py` — AssetRef, Usage, Operation, ParseResult, diagnostics, stable IDs, quote-aware column keys and safe statement splitting.
- `store.py` — Store owns serialized DuckDB access, additive migrations 1–10, workspaces/settings, original versions and transactions. One owning process per home.
- `ingestion.py` — Importer and path/ZIP limits; lexical authorization precedes resolved containment. Originals are immutable SHA-256 blobs; imported code never executes.
- `services.py` — analyze prepares static caches and publishes atomically; analysis_is_current checks inputs/settings and recorded publication version/run. Missing/old versions are stale for static and AI runs. column_report/column_names/compare_runs and export_lineage_excel serve committed facts.
- `asset_identity.py`, `schemas.py` — AssetResolver, job/name identities and typed DDL reconciliation; temporary/job scopes and immutable evidence survive. Ambiguous/changed schemas disable guessed expansion.
- `transformations.py` — materialize_columns, column_catalog and trace_columns; indexed scope/version/role identities, positional wildcards, bounded paths, unknown writers, cycles and reanalysis markers.
- `configuration.py`, `settings_service.py` — Typed settings, portability, section schemas/revisions and atomic patches; agents cannot escalate privileges.
- `reporting.py` — Offline dictionary/health/history/evidence reports and literal source matches; callers enforce source permission for every content search.

## Current project AI pipeline
- `analysis_service.py` — Shared UI/CLI/MCP loop: snapshot, plan, dispatch, validate/save, freeze completion context, consolidate and publish atomically. Run ceilings, cancellation and explicit unknown-attempt retry; failures preserve committed facts.
- `ai_analysis_models.py` — FilePart/PartExtraction/FileExtraction, resources/roles/citations and explicit supersession. Older models serve historical readers.
- `ai_context.py`, `ai_context_index.py` — Immutable selected sources and contiguous file/part plans against complete envelopes; scoped source/saved-AI definitions, quoted identities, dbt/SAS context, ambiguity/budget omissions and offline preparation progress. Lexical referenced_asset_names also bounds diagnostic catalogs.
- `ai_budget.py`, `model_capabilities.py` — Complete input/output/reasoning budgets, identity-bound capacities and optional pinned offline tokenization; unknown models use conservative byte estimates.
- `ai_batching.py`, `ai_wire.py` — Stable instructions/schema prefix, capacity-bound batches and strict compact extraction decoding. New project requests keep streaming disabled.
- `ai_rate_limits.py`, `ai_extraction_recovery.py` — Physical-attempt admission/backoff and exact source split/recovery; no separate workflow engine.
- `ai_validation.py` — Structural/source ownership/range/identity checks independent of static parser approval; legacy semantic functions remain for old records.
- `ai_composition.py` — Saved-detail consolidation, component validation and explicit supersession; original parts persist. Abandoned fragment orchestration is removed.
- `ai_linking.py` — NetworkX operation graph, scoped resources, parallel roles, future/ambiguous writers, cycles and publication conversion. link_file_extractions is current; tested link_stored_facts serves historical normalized checkpoints.
- `ai_analysis_store.py`, `ai_pipeline_store.py` — Durable run/unit/part/file facts, support rebinding, compatible accepted snapshots and interrupted-run recovery; request/physical-attempt journals and metering. Historical context/link tables stay in the schema; unused writers are removed.
- `ai_analysis_progress.py`, `ai_inspection.py` — Source-free durable counters/stages/clocks and bounded opt-in migration-10 transport/decoded artifacts; redaction, lazy reads, retention/cleanup. Reasoning is transient.
- `ai_reconciliation.py` — Historical normalized parser/AI comparisons; normalize_parser_facts remains used by benchmarks.
- `ai_semantic.py`, `ai_source_views.py`, `ai_citations.py` — Legacy source partitions/visibility and immutable citation identities; shared wire decoding remains supported.
- `project_analysis.py` — Policy-gated project preview/build/report/cancellation and profile-bound credentials.
- `services.prepare_analysis_results` — Tested compatibility preparation for historical publication fixtures/snapshots; protocol 5 does not invoke it.

## Focused assistance and privacy
- `llm.py`, `llm_resources.py` — Profile/Adapter protocols/discovery/chat, bounded request admission/chunks, request-local redaction and focused assistance; saved validation remains a compatibility API.
- `focused_grounding.py`, `assistance_queue.py` — Source/hash/job-pinned manual diagnostic assistance, exact grounding and explicit inferred merges; rendering stays offline.
- `connections.py`, `credentials.py` — Scoped session/environment/saved references and redaction. Explicit Windows keyring backend forces local-machine persistence; other OS stores fail closed pending qualification. Namespace binds home/workspace/profile/recipient; no source fallback or global saved-key cache. Disconnect retains saved keys; native writes only through explicit local UI save.
- `provider_service.py`, `ai_service.py` — Origin/reference-authorized profiles/routing, isolated credentials, preview/request/history and idempotent explicit merges. Fallbacks reauthorize their own credentials; profile edits invalidate bindings.
- `logging_config.py` — Safe event metadata allowlist; no raw source or credentials.

## Reports, rendering and maintenance
- `graph.py` — LineageGraph traversal, missing-endpoint evidence, temporary contraction and bounded source-to-target paths with explicit incomplete coverage.
- `exports.py`, `lineage_tree.py` — Shared escaped live/offline graph and lazy tree presentation; exact original-version evidence.
- `excel_exports.py` — Streaming literal-text XLSX paths/evidence with bounded time/text/bytes and cleanup on failure.
- `graph_images.py`, `image_worker.py`, `graph_image_service.py` — Inert SVG, bounded resvg workers and committed filtered graph snapshots with revision/coverage/safe filenames.
- `artifacts.py` — Selection/format allowlists, original-version artifacts and checked scoped base64 reads; source permission rechecked at retrieval.
- `theme_configuration.py` — Eleven native presets and shared UI/graph/site tokens, contrast and atomic TOML updates preserving layout. UI picker: ui/themes.py.
- `cleanup.py`, `maintenance.py` — Preview-bound cleanup/history, idle guards, validated job journals and mandatory full-home backups. Cleanup rebuilds stale nonunique column indexes through committed DROP/CREATE phases with identifier-only recovery metadata; Store startup resumes interrupted rebuilds. Corrected counts require a fresh preview. Column cleanup preserves table-edge supports; history/recovery and new-home restore remain bounded.
- `launcher.py`, `storage_locations.py` — Writable runtime homes, validated startup allowlists, bundled UI paths and lazy Streamlit startup; Windows mutex protects UI/CLI/MCP/worker lifetime.
- `cli.py`, `build.py`, `__init__.py` — CLI/distribution entry points and package version. GraveTrail and documented legacy dataforge commands/import/storage identifiers stay compatible.

## Invariants
Every published edge has exact statement/file/version evidence. Parser semantics changes require
a version bump; reanalysis must rebuild incompatible dbt caches too. External requests are opt-in.
AI semantic completeness remains explicitly unproven; unknown references stay visible. No database
tables are dropped because an old helper has no callers. Full-home backup/restore requires
unrestricted local authority. Source permission applies to every source-content search.
