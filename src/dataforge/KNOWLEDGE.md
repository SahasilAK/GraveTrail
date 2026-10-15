# src/dataforge/

Static facts, persistence, analysis and export APIs. Keep UI imports out of this package. Related tables and data flow are in docs/DATA_MODEL.md.

## Subfolders
- `parsers/` — [parsers/KNOWLEDGE.md](parsers/KNOWLEDGE.md).

## Files
- `__init__.py` — Package marker; no business behavior.
- `configuration.py` — ParsingSettings/PortableSettings validate bounded non-network configuration; WorkspaceIdentity validates names/descriptions; versioned export/import supports v1 and atomic v2 round trips.
- `exports.py` — Embedded graph_data/graph_html and shared SVG JS/CSS; path_rows flattens ordered paths/evidence; report_csv/html escape untrusted values; source_bundle preserves analyzed original bytes.
- `graph.py` — LineageGraph provides bounded search/focus, SCC cycles, temporary contraction, logical rows, root_paths and ordered path_report with evidence and explicit depth/cycle/truncation boundaries.
- `ingestion.py` — Importer and Limits/ImportReport validate ZIP/folder/browser sources; safe_relative/decode and bounded batch inventory writes. Original blobs are SHA-256 named.
- `llm.py` — Profile/Adapter implement protocols/discovery and explicit nonstreaming chat; response_object accepts one enclosing JSON fence only; assist/assist_task enforce privacy/routing, GroundedResponse/validate_response ground claims, merge_claims persists inferred facts.
- `logging_config.py` — JsonFormatter/configure_logging emit application events with an explicit safe metadata allowlist; no raw source/key fields.
- `models.py` — Parser contracts: stable_id, canonical, file_asset, AssetRef, Usage, Operation, Diagnostic, ParseResult; safe statement splitting including SAS inline data.
- `schemas.py` — collect_schemas reconciles typed DDL through the lineage identity resolver, retaining immutable declaration evidence; conflicting/incomplete/schema-changing declarations disable expansion without guessing execution order.
- `services.py` — analyze orchestrates bounded parsing/cache and atomic materialization; schema-backed plain wildcard expansion is inferred and re-materialized on schema refresh; column_report, compare_runs and retained AI provenance use stored facts. Parser version 4.
- `store.py` — Store owns locked DuckDB access, migrations v1/v2, validated workspace creation/editing, settings, source versions, immutable snapshots and transactional boundaries.

## Invariants
Every edge has exact statement/file/version evidence. UI never executes imported code. Cache changes require a parser-version bump. New migrations preserve facts. External AI is opt-in; unknown references remain diagnostics.
