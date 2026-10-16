# src/dataforge/

Static facts, persistence, analysis and export APIs. Keep UI imports out of this package. Related tables and data flow are in docs/DATA_MODEL.md.

## Subfolders
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
- `exports.py` — graph_data/graph_html share validated label/palette/edge appearance and fitted full names with live SVG JS/CSS; path_rows flattens paths/evidence; report_csv/html escape values; source_bundle preserves analyzed originals.
- `graph.py` — LineageGraph retains missing-endpoint evidence in unresolved_edges, excludes anonymous nodes and propagates incomplete-view state; provides bounded search/focus, SCC cycles, temporary contraction, logical rows, root_paths and ordered path_report with evidence and explicit depth/cycle/truncation boundaries.
- `ingestion.py` — Importer and Limits/ImportReport validate ZIP/folder/browser sources; safe_relative/decode and bounded batch inventory writes. Original blobs are SHA-256 named.
- `llm.py` — Profile/Adapter implement protocols/discovery/nonstreaming chat; response_object accepts one enclosing JSON fence; assist/assist_task enforce privacy/routing and optional preview hash pinning; strict grounded claims/quarantine and inferred merge.
- `logging_config.py` — JsonFormatter/configure_logging emit application events with an explicit safe metadata allowlist; no raw source/key fields.
- `maintenance.py` — history_plan protects current references/latest completed runs; bounded archive_history journals recovery with removal, writes an extra checksummed file; restore_history inserts missing IDs atomically, preferring the DB journal.
- `models.py` — Parser contracts: stable_id, canonical, file_asset, AssetRef, Usage, Operation, Diagnostic, ParseResult; safe statement splitting including SAS inline data.
- `schemas.py` — collect_schemas reconciles typed DDL through the lineage identity resolver, retaining immutable declaration evidence; conflicting/incomplete/schema-changing declarations disable expansion without guessing execution order.
- `services.py` — analyze orchestrates bounded parsing/cache and atomic materialization; schema-backed plain wildcard expansion is inferred and re-materialized on schema refresh; column_report, compare_runs and retained AI provenance use stored facts. Parser version 8 invalidates earlier SAS PROC SQL results.
- `store.py` — Store owns locked DuckDB access, migrations v1–v4 (history and temporary recovery journals), validated workspace creation/editing, settings, source versions, immutable snapshots and transactional boundaries.

## Invariants
Every edge has exact statement/file/version evidence. UI never executes imported code. Cache changes require a parser-version bump. New migrations preserve facts. External AI is opt-in; unknown references remain diagnostics.
# Runtime credentials

`connections.py` owns session-local credentials, context scopes, read-only environment
resolution and recursive/JSON-escaped secret redaction. Adapters and log formatting share it; never cache a session manager
globally or persist it. `docs/SECURE_CONFIGURATION.md` describes limits and environment names.

AI admission now covers source reads through result commit; maintenance reserves the home
against new requests. Whole-home backups require unrestricted local authorization.

- `settings_service.py` — section schemas, content revisions, atomic validated patches, privilege tightening and bounded JSON input; UI uses local-human authority.

- `provider_service.py` — validated profile/routing CRUD, exact origin/reference authorization, per-profile runtime bindings and bounded model/test adapter operations.
