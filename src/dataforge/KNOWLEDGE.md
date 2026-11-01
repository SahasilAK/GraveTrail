# src/dataforge/

Static facts, persistence, analysis and export APIs. Keep UI imports out of this package. Related tables and data flow are in docs/DATA_MODEL.md.

- `lineage_builder.py` — Authored table/column/link models, bounded sizes, validated folders, explicit catalog visibility and optional validated `#RRGGBB` table trace colors. Current-work revision checks and named `BuilderWork` snapshots retain colors/layout through editable JSON handoffs. `save_canvas_work` accepts optional auto-generated names and revision checks; Clear atomically snapshots the full design before resetting tables, folders and links. Links distinguish lineage from joins. Schema-only exports filter IDs/roles for JSON/YAML/SQL/CSV/XLSX; SQL preserves validated vendor types. `columns_from_rows` validates decimals and preserves unchanged imported types. Separate from analyzed evidence.
- `datatypes.py` — Offline suggestions for 22 system choices plus custom entry; `type_entry` splits decimal cells and `format_data_type` validates precision/scale with vendor rules. SAS DATA step NUMERIC remains unparameterized; official rule references are retained.
- `schema_imports.py` — Schema-only SQL DDL, explicit SAS LENGTH/PROC SQL, dbt YAML/manifest/catalog JSON, generic JSON, Informatica XML and CSV/TSV imports. Preserves system metadata; clears graph folder references and trace colors. Upload limits, inert content, DTD/alias rejection and partial-format warnings.

`transformations.py` — materialize_columns, column_catalog and trace_columns: indexed,
workspace/job/scoped column identities, revision-bound expressions/roles, bounded traversal,
unknown-writer alternatives and cycle/limit/coverage markers. `models.column_key` shares
quote-aware identity with schema reconciliation; downstream effects query full indexed roles
before display truncation. Plain INSERT wildcards map source positions to destination DDL. Operation.derivations cache
round-trips additively; parser11/migration5 preserve direct usage/table contracts. Cleanup,
integrity and full-home backup/restore include all four column tables and legacy v4 restores.

## Subfolders
- `dbt/` — Project/artifact inventory, logical identity, query adaptation and evidence. See [dbt/KNOWLEDGE.md](dbt/KNOWLEDGE.md).
- `agent/` — Shared automation requests, permissions, jobs, paging and MCP. See [agent/KNOWLEDGE.md](agent/KNOWLEDGE.md).
- `parsers/` — [parsers/KNOWLEDGE.md](parsers/KNOWLEDGE.md).

## Files
- `cleanup.py` — Dependency-aware preview/token/apply services, active-job guards, recognized-file allowlists and conservative shared-blob GC; typed confirmations and transaction-before-file-removal.
- `database_maintenance.py` — Schema/reference/blob integrity, checkpoint, Windows-safe DuckDB snapshots and bounded checksummed ZIP backup/restore to new directories only.
- `launcher.py` — Shared checkout/wheel/frozen UI startup; OS user homes, copy-once runtime theme, migrations and bundled-page path discovery. Streamlit imports remain lazy.
- `build.py` — Source-checkout build CLI: Python, Docker, host PyInstaller/all; sanitized subprocess environments, locked isolated executable build and safe integrity manifests/checksums.
- `cli.py` — Typer CLI and console entry point; JSON/human output, explicit write/import authorization, background workers, DB-free bounded status polling, MCP launcher. No Streamlit imports.
- `storage_locations.py` — Pure bounded startup storage allowlist and resolved selection validation; never creates or migrates directories.
- `asset_identity.py` — AssetResolver separates supplied temporary job/session namespaces, preserves global persistent outputs and rejects mixed-lifetime reads; shared labels/AI visibility helpers.
- `temporary_cleanup.py` — Scoped stale UUID.tmp preview, bounded journal-before-removal, full file identity checks, retained recovery and atomic no-overwrite restore. Uses maintenance idle lock and schema4.
- `llm_resources.py` — Immediate workspace/process request admission with release; offline bounded original-line SQL/SAS/macro/interactive-PROC chunks, never silent truncation.
- `ai_results.py` — ColumnResponse/ExplanationResponse v2 contracts; full-source operation matching, exact citations and direct-column attribution. Advisory results never merge lineage.
- `__init__.py` — Package marker; no business behavior.
- `assistance_queue.py` — diagnostic_queue caps current SQL/SAS warnings/errors at 100; diagnostic_context suggests stored statement or bounded nearby lines; request_review pins source hash through existing privacy-gated routed assistance.
- `configuration.py` — ParsingSettings/VisualizationSettings/PortableSettings validate bounded non-network preferences; WorkspaceIdentity validates names/descriptions; export/import supports v1 and atomic v2 round trips.
- `exports.py` — graph_data/graph_html share validated label/palette/edge appearance, SVG fullscreen and exact-name copy controls; live node focus is a separate double-click callback. COPY_JS reuses clipboard/fallback behavior; graph lifecycle cleans listeners/timers. Reports escape values; source_bundle preserves analyzed originals.
- `excel_exports.py` — lineage_xlsx renders streaming literal-text XLSX paths/steps and optional evidence, overlapping eight-dataset continuation segments, coverage/scope legend, typed cells, filters/frozen context and bounded text/evidence/time/bytes; owned temporary files are cleaned on failures.
- `graph.py` — LineageGraph retains missing-endpoint evidence in unresolved_edges, excludes anonymous nodes and propagates incomplete-view state; bounded paths preserve source-to-target order with optional relationship/evidence budgets and explicit raw-code opt-in. Excel contraction preserves parallel routes and caps evidence before multiplication.
- `ingestion.py` — Importer and Limits/ImportReport validate ZIP/folder/browser sources; safe_relative/decode and bounded batch inventory writes. Directory inputs are lexically normalized and checked against separator-bounded, case-normalized startup roots before filesystem resolution; resolved containment and child symlink guards remain. Original blobs are SHA-256 named.
- `llm.py` — Profile/Adapter implement protocols/discovery/nonstreaming chat with request-local sent-credential redaction across environment rotation; response_object accepts one enclosing JSON fence; assist/assist_task enforce privacy/routing and optional preview hash pinning; strict grounded claims/quarantine and inferred merge.
- `logging_config.py` — JsonFormatter/configure_logging emit application events with an explicit safe metadata allowlist; no raw source/key fields.
- `maintenance.py` — history_plan protects current references/latest completed runs; bounded archive_history journals recovery with removal, writes an extra checksummed file; restore_history inserts missing IDs atomically, preferring the DB journal.
- `models.py` — Parser contracts: stable_id, canonical, file_asset, AssetRef, Usage, Operation, Diagnostic, ParseResult; safe statement splitting including SAS inline data.
- `schemas.py` — collect_schemas reconciles typed DDL through the lineage identity resolver, retaining immutable declaration evidence; conflicting/incomplete/schema-changing declarations disable expansion without guessing execution order.
- `services.py` — analyze orchestrates bounded parsing/cache and atomic materialization; column_report/column_names/compare_runs use stored facts. analysis_is_current shares freshness checks; export_lineage_excel snapshots committed graph/settings/revision, validates bounded scope and generates workbooks for UI/CLI/MCP without analysis or AI. Parser version9 refreshes literal SQL bodies and known-value SAS macro expressions.
- `store.py` — Store owns locked DuckDB access, migrations v1–v4 (history and temporary recovery journals), validated workspace creation/editing, settings, source versions, immutable snapshots and transactional boundaries.

## Invariants
Every edge has exact statement/file/version evidence. UI never executes imported code. Cache changes require a parser-version bump. New migrations preserve facts. External AI is opt-in; unknown references remain diagnostics.
# Runtime credentials

`connections.py` owns session-local credentials, context scopes, explicit validated
`set_credential_environment` for process-only DATAFORGE_ entry, environment resolution retaining
names rather than secret copies, and JSON-escaped secret redaction. sanitize copies dict/list trees, allows shared
references, and raises ValueError for ancestor cycles or more than 64 nested containers;
Adapter converts these validation failures to ProviderError. Never cache a session manager
globally or persist it. `docs/SECURE_CONFIGURATION.md` describes limits and environment names.

AI admission now covers source reads through result commit; maintenance reserves the home
against new requests. Whole-home backups require unrestricted local authorization.

- `settings_service.py` — section schemas, content revisions, atomic validated patches, privilege tightening and bounded JSON input; UI uses local-human authority.

- `provider_service.py` — validated profile/routing CRUD, exact origin/reference authorization, per-profile runtime bindings and bounded model/test adapter operations.

- `ai_service.py` — offline chunks/diagnostic review, hash/job-pinned synchronous assistance with per-fallback authorization, durable metadata/detail/activity and idempotent inferred merge with refresh-failure reporting.

- `reporting.py` — shared dictionary/provenance, health, exact original-evidence integrity (preserving LF/CRLF), literal SQL/SAS matches and scoped history/inventory reports; all queries are offline.

- `artifacts.py` — explicit Selection/format allowlists, focused graph/tree/path/step queries, original-version artifacts and guarded scoped/checksummed base64 reads. Paths accept XLSX with optional evidence/excerpts, revision/count/warning/filename metadata and source authorization rechecked at retrieval.

- `theme_configuration.py` — Shared semantic UI/graph roles for nine palettes; unchanged Ocean dark/Ink dark native presets. Generates Pages palette CSS; contrast-derived link/button text; nested detection and atomic TOML updates preserve sidebar layout while replacing palette colors.

Provider runtime bindings include a saved-profile fingerprint: profile edits invalidate old credentials,
including edits by another adapter. Fallbacks resolve their own approved credentials. AI pins hash/job
again when constructing the request. Graph/path reports enrich stored edges with original evidence and
mark cycle boundaries incomplete. General cleanup cannot opt out of its full-home backup.

GraveTrail compatibility: internal dataforge imports and storage identifiers stay stable. build_python selects only current gravetrail/version artifacts, excluding stale previous-brand/version wheels. Native directory/executable/archive and Docker image names use gravetrail; launcher retains existing platform homes. Exports use GraveTrail titles. Application reset accepts new/legacy exact phrases without changing backup or preview guards.

Windows frozen UI/CLI/MCP/worker dispatch holds launcher.windows_instance's named mutex for its entire lifetime; Inno Setup blocks replacement/uninstall without terminating live owners. Existing storage-home selection remains unchanged.

Whole-home restore staging uses a gravetrail-restore- temporary prefix; persistent backup format IDs and recognized database filenames are unchanged.

Graph presentation in exports.py uses theme-aware surfaces, rounded node materials, visible focus and immediate press feedback; Enter/Space selects evidence and pointer cancellation releases panning. Live and offline graph still share the same rendering code and escaped evidence.

Graph images: graph_images.py serializes inert SVG from exports.graph_data paths/bounds and rasterizes with at most two timeout-bound resvg workers. image_worker.py is the private source/frozen entry. graph_image_service.py snapshots filtered facts in UI name order, bounds contraction evidence and returns revision, counts, coverage and safe filename; exposed by services.py. artifacts.py registers SVG/PNG with source authorization and cleans incomplete publications. Graph.focus marks depth boundaries.

- `ai_analysis_models.py` — Strict bounded v1 project extraction/review contracts, full-unit immutable citation identity and shared run/validation facts.
- `ai_context.py` — Offline immutable source/settings snapshots, complete statement/SAS block project plans without the manual 50-chunk guard; selected-source declaration catalog and memory-only physical-attempt budgets/cancellation/deadline.
- `ai_validation.py` — Exact full-source operation/citation and role checks; bounded static UPDATE/MERGE verification, semantic rejection/abstention and normalized claims. Never executes source.
- `ai_reconciliation.py` — Operation-scoped parser/AI comparison, sparse accepted table pairs and shared writers; hybrid preserves parser-only facts, AI mode omits them.
- `ai_analysis_store.py` — Migration6 runs/units/claims/support checkpoints, inherited declaration freshness, accepted per-file offline snapshots, support rebinding, interrupted-run recovery and bounded reports.
- `analysis_service.py` — Offline preview, physical-attempt budgeting, cache revalidation, optional bounded review and atomic freshness-checked publication. Failures preserve the previous graph.
- `project_analysis.py` — AgentService mixin for policy-gated project preview/build/report and job cancellation; exact profile-bound session credentials.

Current parser cache is14; migration6 adds project provenance without replacing legacy
direct/column tables. Operation evidence_key/table_pairs retain one original writer and
explicit accepted edges. Graph/column/artifact queries preserve unresolved boundaries and
original source-version scope. Full AI bodies remain history opt-in; retention removes them
from surviving referenced records while keeping minimal accepted provenance.

Automatic AI planning: `model_capabilities.py` allowlists selected-model capacity and binds recipient/model identity; `ai_budget.py` estimates complete envelopes and selects bounded executions; `ai_wire.py` hydrates strict v2 unit references before canonical validation. `analysis_service.py` pins resumable work, journals physical attempts, stages extraction/review separately and publishes once. `ai_analysis_store.py` keeps compact host checkpoints/per-claim rows and migration7 per-file/operation snapshots with legacy fallback. Observation timestamps/provenance do not change execution revision; capacity values do.

`preview_analysis(progress=...)` reports offline preparation stages as (stage, completed, total); `ai_context.py` supplies selected-file read/split/shared-context counts. Optional callbacks leave headless callers and analysis semantics unchanged. No source text or credentials enter progress messages.

Accepted claim quotes are compact source refs on disk and hydrate only for source-authorized reports; metadata reads do not read blobs. Wide-operation host detail excludes repeated usage/derivation arrays. Continued completed units remain read-only checkpoints.

- `ai_semantic.py` — Exact-source SELECT projection partitions, allowlisted query clauses and AST/token span verification, scoped parser expressions, static PROC SQL spans and one-writer publication merging.
Semantic continuation persists unit_spec in planned/staged rows and reviewed candidate IDs after each bounded review batch. Saved source/config/protocol pins are checked before hydration. Preview budgets paid stages and labels unknown review sizing provisional; eligible requests above 100 projections split for response cardinality. Root conditional focus instructions are hashed with the actual transmitted variant.

Validator3 is owned by ai_validation and imported by analysis_service. Both unit-cache and protocol pins include validator/parser versions (parser14). Upgrade invalidates paused work before another call; committed graphs remain available.

- `ai_citations.py` — Bounded cached source-only projection/assignment locations, static PROC SQL pages/SAS formats, immutable/dialect-bound IDs and focused visibility. Used by prompt construction and wire decoding; supplies no dependency answers.
Parser14/validator3 add exact projection/SAS assignment occurrence checks. Extraction wire3/prompt4 resolves optional expression references before canonical validation; review stays wire2/prompt3 and durable compact-v2 payloads remain compatible.

Profile timeout cap is3600seconds; current run deadlines still clamp HTTP waits. analysis_service emits source-free waiting/validation stages around extraction/review. Existing saved/default profiles are unchanged.

Build Python artifacts now include dependency-overrides.txt in manifest alongside wheel/sdist; native locked export stays authoritative. Exact Streamlit/Pillow exception and installer/removal policy live in SECURITY.md.
