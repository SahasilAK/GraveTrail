# tests/

Unit, persisted-workflow, protocol/security, AppTest and distribution/documentation regressions. Use temporary isolated Store homes and mocks; ordinary tests require no live provider keys. Full per-file inventory/key helpers are in docs/development/source-inventory.md, generated from AST without executing tests.

## Subfolders
- `fixtures/` — deterministic input/expected evidence including scenario, vendor/dialect, dbt and AI cases; [map](fixtures/KNOWLEDGE.md).
- `sample_data/` — supplied SQL/SAS and synthetic dbt project ZIPs and gold/manifest boundaries; [map](sample_data/KNOWLEDGE.md).

## Test areas and shared helpers
- `test_workflow.py`, `test_ingestion.py`, `test_inventory_controls.py`, `test_vendor_fixtures.py` — safe intake, complete persisted analysis, incremental cache/reimport/isolation, original evidence and fixture oracles.
- `test_sql.py`, `test_sas.py`, `test_sas_project.py`, `test_parser_static_wrappers.py`, `test_schemas.py`, `test_job_identity.py` — static grammar, literal-versus-runtime boundaries, original coordinates, schemas/wildcards and temporary/job identities.
- `test_sql_transformations.py`, `test_sas_transformations.py`, `test_transformations.py`, `test_transformation_sas_integration.py`, `test_transformation_access.py` — distinct value/role derivations, scoped/versioned identity, unknown writers, migrations and UI/CLI/MCP disclosure/traversal parity.
- `test_graph.py`, `test_lineage_qol.py`, `test_lineage_tree.py`, `test_column_qol.py`, `test_explorer_evidence.py` — bounded graph/tree paths, unresolved endpoints, evidence retention, exact selection/history and direct-column UI meaning.
- `test_dbt_*.py` — safe YAML/project/artifact import, resources/refs/packages/versions, original/generated evidence, static/AI context, persistence/settings/maintenance, policy and UI/automation.
- `test_ai_independent_extraction.py`, `test_ai_file_parts.py`, `test_ai_file_consolidation.py`, `test_ai_operation_graph.py`, `test_ai_context_index.py`, `test_ai_context_completion.py` — current independent source-provenance/structural checks without static semantic approval, file/context/consolidation contracts and deterministic linking.
- `test_ai_resumable_files.py`, `test_ai_response_replay.py`, `test_ai_partial_recovery.py`, `test_ai_extraction_recovery.py`, `test_ai_pipeline_store.py`, `test_ai_pipeline_review_regressions.py` — durable attempts/parts/context, compatible reuse, unknown outcomes, repair/partial retry and interrupted recovery.
- Other `test_ai_*.py` — request/schema/budget/protocol/privacy, exact-source and legacy compatibility, atomic publication, jobs/progress/accounting/inspection/UI and qualification regression coverage. Inspect the actual test/path before inferring a current control from a historical test filename.
- `test_llm.py`, `test_model_capabilities.py`, `test_llm_resources.py`, `test_connections.py`, `test_provider_setup.py` — provider wire/discovery/capacity, request admission, scoped credentials/redaction and endpoint-first UI.
- `test_focused_assistance.py`, `test_assistance_queue.py`, `test_diagnostic_review_budget.py`, `test_first_test_review_budget.py`, `test_ai_results.py` — focused manual grounding/advisory/merge and complete redacted budget equality; separate from current independent project semantics.
- `focused_test_profiles.py` — explicit offline confirmed-capacity/disclosure factory; no production preflight bypass. `legacy_ai_fixtures.py` — compatibility fixture helper, not the current extraction protocol.
- `test_agent_service.py`, `test_agent_cli.py`, `test_agent_mcp.py`, `test_agent_settings.py`, `test_parity_*.py`, `test_gateway_*.py` — shared policy/action/transport/reference parity, real SDK stdio/HTTP, permissions/source/revocation/paging and single-owner job polling.
- `test_store.py`, `test_storage_locations.py`, `test_workspace_configuration.py`, `test_remaining_settings.py` — additive persistence/source versions, allowed homes and scoped/revisioned settings.
- `test_cleanup.py`, `test_maintenance.py`, `test_temporary_cleanup.py`, `test_dbt_maintenance.py` — preview freshness, active-job/shared-blob protection, required backup, retained journals and new-home restore.
- `test_exports.py`, `test_excel_exports.py`, `test_excel_artifacts.py`, `test_graph_images.py`, `test_image_artifacts.py` — inert report/graph/image/XLSX bytes, original hashes, scope/limits, source authorization and cleanup. Node tests exercise JS syntax/mount behavior separately from AppTest.
- `test_ui.py`, `test_navigation_redesign.py`, `test_themes.py`, `test_site_themes.py` — native page/state/laziness/theme controls; AppTest does not execute browser graph JavaScript.
- `test_distribution.py`, `test_release.py`, `test_windows_installer.py`, `test_pillow_compatibility.py` — package/source exclusions, aliases/bundled assets, version/staging/trust/platform and compatibility contracts; release tests also require baseline Git history in the reusable native test gate. Target artifact smoke still requires the target runtime.
- `test_documentation.py` — actual Typer/MCP reference completeness, publication allowlist/exact HTML digest/CSP, links/prefix/output inventory and legacy route/heading preservation.
- `test_docs_inventory.py` — complete first-party selection, import-free AST extraction, freshness/no-write drift and valid pinned/new-file source links.
- `test_archive_qualification.py`, `test_qualification_semantics.py` — archive/gold/scorer boundaries; missing independent column gold or live tests remain explicit limits.

Default pytest configuration adds src/ and repository root to pythonpath. CI runs Ruff/pytest on Python3.12 Windows/Ubuntu; docs inventory checking requires full baseline history. Do not claim live semantic accuracy, browser offline behavior or hosted deployment from mocked/source-only checks. Historical test names/fixtures remain compatibility evidence rather than current feature promises.
