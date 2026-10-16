# tests/

Unit, integration, security and AppTest regressions. Use temporary Store homes; no live LLM keys required. tests/fixtures supplies real deterministic input.

## Subfolders
- `fixtures/` — [fixtures/KNOWLEDGE.md](fixtures/KNOWLEDGE.md).

## Files
- `test_explorer_evidence.py` — Missing-asset warning/search regression; active tree tab filters source files independently of graph direction; explicit graph evidence selection overrides it.
- `test_inventory_controls.py` — CSV sample bounds/portability/cache refresh and immediate post-analysis inventory status counters.
- `test_storage_locations.py` — Explicit/bounded path choices, two-session switching/back with retained sources and failed-open preservation.
- `test_vendor_fixtures.py` — Exact labeled dependency/direct-column/temporary sets for six SQL dialects and SAS in LF/CRLF, original evidence and warm-cache preservation.
- `test_job_identity.py` — Cross-job temporary/schema/column isolation, global persistent paths, mixed-lifetime diagnostics, AI refresh, history/exports and Settings/chooser UI regressions.
- `test_temporary_cleanup.py` — Scope/age/count bounds, changed preview/journal failures, idle guard, recovery after restart/no overwrite, atomic publication failure, v3 migration and UI cleanup/restore. Windows symlink privilege may skip one test.
- `test_remaining_settings.py` — Extension/folder precedence, PROC SQL dialect, non-destructive graph filtering, safe log level, portable/UI preferences and selected cache-upgrade preservation.
- `test_llm_resources.py` — Chunk coordinates/statement/SAS context, concurrent admission/release, cancellation/no transmission, connection gate and explicit single-chunk UI request.
- `test_ai_results.py` — Task schemas, invented/ambiguous/transitive/comment/string attribution, historical advisory merge exclusion, saved offline UI results and stale-source warnings.
- `test_assistance_queue.py` — Current diagnostic eligibility/bounds, SQL/SAS focused context, isolation, privacy, quarantine/inferred merge and preview-hash race refusal using synthetic HTTP only.
- `test_exports.py` — Escaped reports/original ZIPs, path evidence/order, live/offline appearance parity and Node syntax/DocumentFragment mount regression.
- `test_graph.py` — Graph traversal plus missing-endpoint regression: evidence retention, valid search/rows and incomplete path propagation. Run with pytest; temporary runtime data only.
- `test_lineage_tree.py` — AppTest covers lazy compact branches, Expand all/Collapse all, inline files, both directions, optional evidence details, cycle stops and depth/entry limits.
- `test_hardening.py` — Behavioral regression tests for hardening. Run with pytest; temporary runtime data only.
- `test_ingestion.py` — Behavioral regression tests for ingestion. Run with pytest; temporary runtime data only.
- `test_llm.py` — Provider protocols, grounding/privacy, fenced JSON rejection boundaries, malformed HTTP envelopes and inferred merge retention. Temporary runtime data only.
- `test_logging.py` — Behavioral regression tests for logging. Run with pytest; temporary runtime data only.
- `test_maintenance.py` — History archive/restore bounds, workspace/reference protection, idempotence, tamper rejection, transaction rollback, v3 migration and journal recovery after lost file/restart.
- `test_sas.py` — Behavioral regression tests for sas. Run with pytest; temporary runtime data only.
- `test_schemas.py` — Typed DDL/wildcard eligibility, conflicts/changes/inheritance, cache refresh, disabled extraction, identical declarations, unqualified invalidations, SWAP/RENAME and no CSV name guessing.
- `test_sql.py` — Behavioral regression tests for sql. Run with pytest; temporary runtime data only.
- `test_store.py` — Behavioral regression tests for store. Run with pytest; temporary runtime data only.
- `test_themes.py` — Frozen original-eight palette/order preservation, exactly six additions; native mode/config/TOML preservation, atomic rollback and AA contrast across all fourteen themes.
- `test_ui.py` — Page/workspace/provider flows, complete fourteen-theme dropdown, schema/history, visualization/source defaults and workspace selection resets; diagnostic preview/stale-click refusal/synthetic request/explicit merge. Temporary data only.
- `test_workflow.py` — Behavioral regression tests for workflow. Run with pytest; temporary runtime data only.
- `test_workspace_configuration.py` — Workspace edits preserve identity/data; safe v1/v2 configuration portability, resource validation, isolation and injected-failure rollback.
