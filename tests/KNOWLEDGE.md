# tests/

Focused workflow and safety regressions. Tests use isolated temporary Store homes and offline provider fixtures. The current selection favors persisted user workflows, failure recovery and trust boundaries. Grammar, provider metadata and appearance variations have representative coverage.

The generated `docs/development/source-inventory.md` lists every current file and its declared helpers. Shared fixture functions remain in some test modules after the standalone microtests were removed. They are ordinary imports used by the retained tests.

## Retained regression areas

- `test_migration.py` covers SQL/SAS/dbt outputs, original evidence, schema assumptions, unsupported logic, scoped proposals, atomic revision checks, engineer review, comments, recovery and export integrity. Navigation is exercised in `test_navigation_redesign.py`.
- `test_workflow.py`, `test_vendor_fixtures.py`, `test_sas_project.py`, `test_transformations.py` and `test_transformation_sas_integration.py` cover persisted analysis, evidence, dependencies, incremental updates and column traces.
- `test_dbt_*.py` cover static project imports, unsafe paths/YAML/templates, artifacts, references, reimports and recovery. Imported dbt code is never executed.
- `test_ingestion.py`, `test_hardening.py`, `test_job_identity.py` and `test_schemas.py` cover intake limits, source versions, publication rollback, job isolation and schema uncertainty.
- `test_ai_full_build.py`, `test_ai_resumable_files.py`, `test_ai_response_replay.py` and `test_ai_extraction_recovery.py` cover independent SQL/SAS/dbt builds, durable attempts, interrupted work, unknown outcomes, bounded repair and replay.
- `test_focused_assistance.py`, `test_diagnostic_review_budget.py`, `test_first_test_review_budget.py`, `test_llm.py` and `test_gateway_*.py` cover scoped source disclosure, request budgets, provider protocols, stale requests and cancellation. `focused_test_profiles.py` supplies confirmed offline profiles.
- `test_local_credentials.py`, `test_connections.py`, `test_agent_*.py` and retained `test_parity_*.py` cover credential isolation/redaction, launch grants, cross-workspace access, source revocation and shared CLI/MCP workflows. Native credential stores are faked.
- `test_cleanup.py`, `test_data_management_cleanup.py`, `test_maintenance.py` and `test_temporary_cleanup.py` cover fresh previews, confirmations, required backups, rollback, interrupted recovery and protected paths.
- `test_lineage_builder.py`, retained graph/evidence tests and export tests cover atomic saved work, exact evidence, inert artifacts, literal spreadsheet cells, original bytes and authorization. AppTest exercises native controls. Node checks exercise browser JavaScript separately.
- `test_distribution.py`, `test_release.py`, `test_windows_installer.py`, `test_documentation.py` and `test_docs_inventory.py` cover packaging exclusions, checksums, release staging, platform ownership, publication boundaries and current documentation inventories.

## Running checks

Default pytest configuration adds `src/` and the repository root to `pythonpath`. Run `uv run pytest -q` and `uv run ruff check .`. Regenerate the source inventory after removing or consolidating test functions with `uv run python scripts/docs/inventory.py`.

CI runs on Python 3.12 on Windows and Ubuntu. Documentation inventory checking requires baseline Git history. Mocked responses establish deterministic behavior and safety, with live model semantic accuracy verified separately. Browser rendering and target installers require their own runtime qualification.
