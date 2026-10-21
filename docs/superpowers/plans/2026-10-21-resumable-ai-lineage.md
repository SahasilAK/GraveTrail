# Resumable AI Lineage Build Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This planning request authorizes the plan only; no product implementation has started. Preserve the user's chosen execution method when one is supplied.

**Goal:** Deliver one resumable, quota-aware AI/hybrid build for SQL, SAS and dbt, automatically extracting, saving, connecting and publishing evidence-backed table and column lineage.

**Architecture:** Extend existing immutable source units, validation, persistence and publication. Prepare language/project context, pack compatible pending units into bounded requests, admit them through a durable scheduler, checkpoint each item, then link stored facts and run bounded resolution before atomic publication. All interfaces share one service; static parser algorithms remain unchanged.

**Tech Stack:** Existing Python 3.11+, Pydantic, httpx, DuckDB, SQLGlot, NetworkX, Streamlit, Typer, MCP SDK and pytest. No new runtime framework, graph database, vector store or dbt execution dependency.

**Spec:** [Resumable AI lineage requirements and design](../specs/2026-10-21-resumable-ai-lineage-design.md). Read both files before execution. The requirement IDs below refer to that document.

## Global Constraints

- SQL, SAS **and dbt AI/hybrid support are required** in this delivery. The user's later clarification supersedes earlier discussion of deferring dbt.
- Do not modify static parser algorithms in `src/dataforge/parsers/` or the existing dbt parser modules. Shared-service integration may select/compare their unchanged outputs.
- Existing parser-only/default behavior, manual AI assistance, source originals and published graphs remain compatible.
- Imported SQL/SAS/Jinja/Python/hooks are untrusted data and never execute. Do not invoke dbt compile/run or download packages.
- Proper source/project prompt context and strict structured extraction are central; prompts alone do not replace host validation, persistence and linking.
- AI additions remain inferred under current confidence/display policy. AI confidence or reviewer agreement cannot grant semantic validity or complete coverage.
- Preserve full-envelope model/privacy checks, source permissions, endpoint authorization and credential redaction per physical dispatch; no credentials/raw provider headers in persistent state.
- One DuckDB owner per runtime home. Coordinator owns persistence; provider workers must not share mutable store/transaction/execution context.
- Keep existing workspace concurrency range 1–4, process admission cap 8 and background-job cap 2. New custom parallelism is further constrained by these limits.
- Existing per-execution ceilings remain 2,000 physical attempts, 2,000,000 reserved output tokens and 14,400 cooperative seconds; separate request timeout and whole-project authorization.
- Proposed first-release batch policy: custom files 1–100, maximum 8 items per batch, Auto starts at 1 and grows 1/2/4/8 after three clean batches; size/truncation failure halves the pending batch.
- At most one repair dispatch per extraction unit and two targeted resolution rounds per initial unit; adapter retries remain separately bounded and counted. Freeze a finite whole-project allowance before Start.
- Opening the app, preview, status polling and graph browsing never send project source. Process restart requires explicit Resume and fresh runtime grants; normal execution rollover within an active authorized build is automatic.
- Unknown dispatched outcomes are not automatically retried without supported idempotency/reconciliation or explicit `retry_unknown`. No exactly-once billing claim.
- Failed, cancelled, stale or incomplete required-unit builds retain the previous published graph. Partial semantic coverage must be explicit; unsupported claims remain unresolved.
- Keep plan/spec internal and out of MkDocs nav/search. Public workflow documentation is Task 13 and describes shipped behavior only.
- Numerical policy defaults are proposed design choices for review, not values selected by the user. This plan must be reviewed before implementation.

## Review Focus

1. A dbt model is a `.sql` file but depends on YAML/macros/versioned refs or generated evidence: preserve project handling and source origin (Tasks 3, 4, 8, 9).
2. A batch partly succeeds, an out-of-order worker returns twice, or the process dies after dispatch: retain good item checkpoints without duplicated facts or unapproved billable retries (Tasks 2, 5, 7, 10).
3. Two profiles/workspaces share a quota or a gateway hides its actual upstream: coordinate conservatively without persisting secrets or inventing limits (Tasks 6, 7).
4. A new schema/producer definition appears after an earlier unique lookup, or multiple writer versions/cycles exist: invalidate/relink affected results without name-only or file-order inference (Tasks 3, 8, 9).
5. Permissions, source, route or session credentials change during a quota wait or just before publication: reauthorize before disclosure, reject stale publication and preserve the old graph (Tasks 6, 7, 10, 12).

## Baseline and file ownership

Current source already implements sequential project extraction, semantic partitions, physical-attempt hooks, compact unit/review checkpoints, manual continuation and atomic publication. Extend it rather than rebuilding those components. `dbt/service.py::reject_dbt_ai` currently blocks dbt; remove its project-analysis use only in Task 10 after dbt support is integrated. The current full-manifest cache key and single run-level `inflight` record are specific limitations to replace.

| File | Responsibility in this change |
| --- | --- |
| `src/dataforge/ai_analysis_models.py` | Existing request/report/unit/evidence models; additive scheduling/source/batch contracts |
| `src/dataforge/ai_context.py`, `ai_semantic.py`, `ai_budget.py` | Existing immutable planning, safe boundaries, capacity/allowance estimation |
| **New** `src/dataforge/ai_source_context.py` | SQL/SAS context dispatch, unit dependency tracking and shared context manifest |
| **New** `src/dataforge/dbt/ai_context.py` | dbt source/artifact/project prompt preparation; reuse safe inventory/readers |
| **New** `src/dataforge/ai_pipeline_store.py` | Request/attempt/dependency/link-stage durable records; single coordinator writes |
| **New** `src/dataforge/ai_batching.py` | Pure full-envelope packing and bounded batch adaptation |
| **New** `src/dataforge/ai_rate_limits.py` | Allowlisted provider quota normalization, shared admission and retry schedule |
| **New** `src/dataforge/ai_scheduler.py` | Queue, execution rollover, per-worker snapshots, completion coordination |
| **New** `src/dataforge/ai_linking.py` | Stored-fact identity resolution, dependency linking, ambiguity work and coverage |
| `src/dataforge/llm.py`, `ai_wire.py`, `ai_validation.py`, `ai_citations.py` | Batch transport, per-item decoding, source-aware evidence/semantic checks |
| `src/dataforge/analysis_service.py`, `ai_analysis_store.py`, `ai_reconciliation.py` | Full shared build, existing accepted-fact reuse and atomic publish/report |
| `src/dataforge/store.py`, `database_maintenance.py`, `maintenance.py` | Additive schema, retention, referenced blobs, backup/restore/integrity |
| `src/dataforge/services.py`, `transformations.py`, `dbt/service.py`, `dbt/persistence.py` | AI-aware composition of existing graph/dbt publication contracts; parser behavior unchanged |
| `src/dataforge/project_analysis.py`, `cli.py`, `agent/service.py`, `agent/mcp_server.py`, `agent/jobs.py`, `agent/capabilities.py` | Shared adapters, job lifecycle, inputs/progress and capability descriptions |
| `ui/analysis_ai.py`, `ui/pages/analysis.py`, `ui/pages/connections.py` | User controls, preview, model/quota status, progress and actionable recovery |
| `prompts/project_lineage/`, **new** `prompts/project_resolution/`, `prompts/schemas/` | Shared output envelope, source-specific instructions, targeted resolution and generated schemas |
| `tests/`, `scripts/benchmark_ai_analysis.py`, `scripts/benchmark_lineage_archives.py` | Regression, fault injection, source-specific and scale/accuracy proof |

New modules are focused responsibilities, not an extensible agent framework. Keep existing helpers where they fit; no unrelated reorganization. Do not create a new module merely to hold one forwarding function.

### Contract names used by the tasks

Define new immutable/strict models in `ai_analysis_models.py`; use existing `AnalysisUnit`, `ValidationReport`, `NormalizedFact`, `AnalysisReport`, `Store` and `PreparedAnalysis` where possible.

- `BuildPolicy`: files/parallel maxima, auto-continuation, repair/resolution bounds; runtime-only learned grouping state is separate from semantic identity.
- `ProjectAllowance`: resolved finite attempt/output-reservation/active-time ceilings and their Auto/custom provenance; existing request ceilings remain per execution.
- `ContextDependency`: source/artifact/config hash, scope, lookup key, positive/negative/ambiguous lookup and evidence origin.
- `ContextManifest`: versioned unit context/dependencies, extraction/context-only file dispositions and immutable disclosure list.
- `SourcePlan`: stable units plus context manifests, source-kind counts and unsupported/partial dispositions.
- `BatchPlan`: host batch ID, ordered unit IDs, kind/dialect/route, context fingerprint, input/output estimates and distinct-file count.
- `BatchItemOutcome`: unit ID, validated transport result or bounded error, finish/usage status; contains no publish-ready client authority.
- `QuotaScope`, `RateLimitSnapshot`, `Admission`: non-secret quota identity, known limit/remaining/reset/provenance and granted/wait-until/blocked reason.
- `AttemptTicket`, `AttemptOutcome`: durable host attempt ID, request/unit membership, reservations and known/unknown dispatch state.
- `LinkSnapshot`, `LinkReport`, `ResolutionTask`: staged validated inputs, scoped links/coverage/conflicts and host-issued bounded ambiguity contexts.
- `WorkerRequest`, `WorkerOutcome`: immutable serialized prompt/route/options and sanitized response/error/usage. Workers receive a scoped runtime connection object, never Store.

Public request additions (names shared by UI/CLI/MCP): nullable `max_files_per_request`, nullable `max_parallel_requests`, `auto_continue=True` for new builds, nullable `project_max_provider_attempts`, `project_max_output_tokens_total`, `project_max_seconds`. Null means a disclosed finite Auto recommendation, not unlimited. Preserve existing names/semantics for execution ceilings and `resume_run_id`/`retry_unknown`.

## Execution sequence and review checkpoints

Tasks 1–12 are required core delivery, including dbt. Task 13 finishes the release documentation and Pages work. Review source/evidence contracts after Task 4, admission/recovery after Task 7, and assembled mixed-source publication after Task 10. These are review boundaries, not separate user builds.

Before each implementation task: write the named failing tests, run them to demonstrate the missing behavior, implement the smallest responsible change, run the focused gates, and commit the coherent task when execution is authorized. Commit commands are not part of this planning turn. A later executor must inspect current instructions and version numbers before editing.

## Task 1: Freeze requirements, compatibility and request policy

**Requirements:** R01, R02, R06, R15, R16.

**Files:** modify `ai_analysis_models.py`, `ai_budget.py`, `configuration.py`; tests `test_ai_analysis_contracts.py`, `test_ai_budget.py`, `test_remaining_settings.py`; inspect `ui/pages/analysis.py`, `ui/pages/connections.py` and current CLI/MCP registration.

**Interfaces:** extend `AnalysisRequest` with the public fields above. Add `resolve_project_allowance(plan: SourcePlan, routes: dict, policy: BuildPolicy, request: AnalysisRequest) -> ProjectAllowance`. Routes are the existing sanitized preview routes; a plan's singleton units give a conservative batch-independent ceiling. Add `execution_window(remaining: ProjectAllowance, request: AnalysisRequest) -> dict[str, int]` preserving existing execution bounds.

- [ ] Add `test_new_build_policy_is_finite_and_legacy_request_stays_compatible`: old request JSON still loads; `max_files_per_request` accepts null/1/100 but rejects 0/101; parallel accepts null/1/4 but rejects 0/5; null project caps resolve to positive finite values.
- [ ] Add `test_project_totals_are_distinct_from_execution_window`: synthetic 6,238 initial tasks and two allowed attempts per task display a 12,476-attempt extraction ceiling while a window never exceeds 2,000. Review/repair/resolution ceilings are separately identified; no unapproved work can exceed the persisted lifetime cap.
- [ ] Add `test_project_budget_counts_bounded_dynamic_work`: optional review uses response cardinality limits; repair is at most one dispatch/unit, resolution at most two rounds/initial unit; arithmetic overflow/invalid policy blocks offline before dispatch.
- [ ] Run `uv run pytest tests/test_ai_analysis_contracts.py tests/test_ai_budget.py tests/test_remaining_settings.py -q` before/after implementation.
- [ ] Resolve draft numerical policies during design review, capture them in tests/constants, and record the baseline parser/validator/protocol/schema versions without changing parser algorithms. Commit this contract slice.

## Task 2: Durable requests, attempts and dependency records

**Requirements:** R05, R08, R10, R11.

**Files:** create `ai_pipeline_store.py`; modify `store.py`, `ai_analysis_store.py`, `database_maintenance.py`, `maintenance.py`; tests **new** `test_ai_pipeline_store.py`, existing `test_ai_analysis_persistence.py`, `test_ai_analysis_continuation.py`, `test_maintenance.py`, `test_parity_maintenance.py`, `test_dbt_maintenance.py`.

**Interfaces:** `save_request(store, workspace: str, run_id: str, batch: BatchPlan) -> None`; `begin_attempt(store, workspace: str, run_id: str, batch_id: str, reservation: dict) -> AttemptTicket`; `finish_attempt(store, ticket: AttemptTicket, outcome: AttemptOutcome) -> None`; `save_context_dependencies(store, workspace: str, run_id: str, unit_id: str, dependencies: tuple[ContextDependency, ...]) -> None`; `recover_pipeline(store, workspace: str, run_id: str) -> dict`. Enforce workspace/run membership inside every helper. Existing `save_validation_checkpoint` remains the accepted per-item checkpoint writer.

- [ ] Add `test_parallel_attempts_have_independent_durable_outcomes`: two in-flight requests survive reopen separately; one validates and the other becomes unknown; recovering cannot mark both complete or clear the other's pending outcome.
- [ ] Add `test_duplicate_completion_is_idempotent` and `test_checkpoint_and_request_item_completion_are_atomic`: duplicate item callbacks create no duplicate claims; transaction interruption produces either a complete checkpoint/item terminal update or neither.
- [ ] Add `test_upgrade_preserves_existing_graph_and_legacy_continuation` plus backup/restore/retention checks: existing records load unchanged, referenced original/generated blobs remain protected, quota/credential secrets are absent, expired staging can be cleaned without orphaning accepted support.
- [ ] Add an additive migration (currently schema 8; use 9 only if still next) for `ai_analysis_requests`, `ai_analysis_attempts`, `ai_context_dependencies`, and a compact `ai_link_checkpoints` table. Use explicit schema columns for identities/status/counters and bounded versioned JSON for details; never copy entire source into every attempt. Extend existing table inventories, integrity, cleanup and backup compatibility checks.
- [ ] Run the new persistence suite and existing AI recovery/maintenance suites; review migration rollback as backup/new-home restoration or disabling the feature, not an unsafe down-migration. Commit.

## Task 3: Source-aware units, relevant context and incremental reuse

**Requirements:** R01, R03, R04, R05, R07, R08.

**Files:** create `ai_source_context.py`; modify `ai_context.py`, `ai_semantic.py`, `analysis_service.py::_unit_context_hash`; tests **new** `test_ai_source_context.py`, existing context/scaling/citation/schema-provenance/preparation suites.

**Interfaces:** `prepare_source_plan(prepared: PreparedAnalysis, *, progress=None) -> SourcePlan`; `context_for_unit(plan: SourcePlan, unit: AnalysisUnit) -> ContextManifest`; `unit_reuse_key(unit: AnalysisUnit, context: ContextManifest, identities: dict) -> str`; `affected_units(old: ContextManifest, new: ContextManifest) -> set[str]`. Handler selection uses imported source metadata before extension; dbt invokes Task 4's preparation.

- [ ] Add `test_sql_and_sas_units_keep_semantic_boundaries`: same-line SQL, Unicode, CTE scope, DATA/PROC/macro state, projection independence and source offsets survive planning; indivisible over-capacity code receives an explicit disposition rather than truncation.
- [ ] Add `test_unrelated_file_change_reuses_unchanged_extraction`, `test_macro_or_schema_change_invalidates_consumers`, and `test_new_competing_definition_invalidates_negative_or_unique_lookup`. Preserve the complete project publication pin separately from per-unit dependency keys.
- [ ] Add `test_context_only_file_is_counted_without_fake_extraction` and `test_project_membership_wins_over_sql_extension`: dbt YAML/macros/config have explicit dispositions; dbt `.sql` does not enter ordinary SQL handling.
- [ ] Implement relevant symbol/context indexes once per plan, dependency fingerprints and immutable context references. Avoid whole-source rereads for every unit/callback; use immutable original blobs plus current database revisions/relevant source-hash checks without weakening freshness.
- [ ] Run `uv run pytest tests/test_ai_source_context.py tests/test_ai_analysis_context.py tests/test_ai_analysis_scaling.py tests/test_ai_analysis_schema_provenance.py tests/test_ai_citations.py tests/test_ai_preparation.py -q`; commit without editing static parsers.

## Task 4: Required dbt prompt context and evidence contract

**Requirements:** R01, R03, R04, R08.

**Files:** create `dbt/ai_context.py`; modify `ai_analysis_models.py`, `ai_source_context.py`, `ai_citations.py`, `ai_wire.py`, `ai_validation.py`; reuse unchanged `dbt/discovery.py`, `models.py`, `resources.py`, `templates.py`, `artifacts.py`, `evidence.py`; tests **new** `test_dbt_ai_context.py`, `test_dbt_ai_validation.py`; existing dbt fixtures and tests.

**Interfaces:** `prepare_dbt_units(prepared: PreparedAnalysis, *, selected_file_ids: set[str]) -> SourcePlan`; `dbt_prompt_context(unit: AnalysisUnit, manifest: ContextManifest) -> dict`; `validate_dbt_candidates(response, context: ValidationContext) -> ValidationReport`. Extend existing evidence models compatibly with source-kind/resource identity and source/artifact/generated origin; preserve legacy SQL/SAS model loading. Consume safe source/artifact metadata, not parser lineage answers.

- [ ] Add `test_dbt_context_includes_relevant_model_yaml_macros_and_refs`: a model obtains its project/package/version, relevant `ref`/`source`, config, columns and macro dependency closure; unrelated project source is excluded and closure disclosure is visible.
- [ ] Add `test_source_enriched_artifact_modes_preserve_evidence_origin`: source-only works without compiled SQL; supplied artifacts use exact JSON Pointer/raw JSON evidence; generated expression spans reference supplied generated SQL; known mismatch rejects and unsupported artifact schema has a precise reason.
- [ ] Add `test_dbt_context_handles_ephemeral_versions_packages_and_cycles`: same names across roots/packages/versions do not merge; ephemeral resources remain logical nodes; recursive macros/dynamic refs produce bounded partial coverage rather than unbounded context or execution.
- [ ] Add `test_dbt_documented_columns_do_not_prove_wildcard_completeness` and `test_python_model_and_unknown_jinja_report_partial_coverage`. For source `SELECT * FROM {{ ref('customers') }}`, table-reference evidence and unknown column coverage remain distinct.
- [ ] Add `test_dbt_extraction_prompt_does_not_include_static_lineage_answers`: context contains original source and supplied declared artifacts with origin, never computed parser edge/derivation lists or fixture gold. No dbt/Jinja/Python execution or package downloads.
- [ ] Run `uv run pytest tests/test_dbt_ai_context.py tests/test_dbt_ai_validation.py tests/test_dbt_resources.py tests/test_dbt_settings.py tests/test_ai_analysis_schema_provenance.py -q` and the remaining dbt regression suites. Commit preparation/validation while keeping project rejection until integrated.

## Task 5: Full-envelope batching and per-item response validation

**Requirements:** R04, R06, R07, R08, R10.

**Files:** create `ai_batching.py`; modify `ai_budget.py`, `llm.py`, `ai_wire.py`, `ai_analysis_models.py`, `ai_validation.py`, root project-lineage prompts and generated schemas; tests **new** `test_ai_batching.py`, `test_ai_batch_transport.py`; existing wire/scaling/transport tests.

**Interfaces:** `pack_pending_units(units: tuple[AnalysisUnit, ...], contexts: dict[str, ContextManifest], profile, policy: BuildPolicy, adaptation: dict) -> tuple[BatchPlan, ...]`; `decode_batch_response(raw: str, batch: BatchPlan, units: dict[str, AnalysisUnit]) -> tuple[BatchItemOutcome, ...]`; `next_batch_width(current: int, *, clean_streak: int, outcome: str) -> int`. Introduce a versioned batch envelope whose item payloads reuse current single-unit response contracts; keep single-item and legacy record readers.

- [ ] Add `test_batch_limits_count_distinct_files_and_all_prompt_overhead`: custom 1 excludes a second file; multiple units in one file remain bounded by item/context/output limits; shared context is deduplicated by immutable ID; schema/instructions/evidence references all count.
- [ ] Add `test_model_output_limit_restricts_batch_before_input_limit`: wide column output does not get packed solely because source fits; safe projection partitioning remains source-bound. Unknown/native-JSON-less models use conservative JSON envelopes.
- [ ] Add `test_auto_width_grows_only_after_three_clean_batches_and_shrinks_on_size_failure`, with exact widths 1/2/4/8. A valid partial-coverage response is not falsely treated as evidence that all expected coverage was extracted.
- [ ] Add `test_partial_batch_keeps_good_items_and_requeues_only_missing_items`, `test_foreign_duplicate_and_cross_item_evidence_are_rejected`, and `test_truncated_unparseable_batch_has_no_invented_partial_success`. Per-item usage must remain unknown unless actually attributable; batch totals are counted once.
- [ ] Implement prompt files for SQL/SAS/dbt-specific instructions with the same canonical output facts. Generate wire schemas from models. Increase AI protocol/handler versions as required; do not bump static parser version merely for batching. Review stale legacy runs explicitly.
- [ ] Run the new batch suites plus `tests/test_ai_wire.py`, `test_ai_analysis_transport.py`, `test_ai_analysis_scaling.py`; verify a smaller fallback replans only pending items. Commit.

## Task 6: Provider quota discovery, paced admission and durable waits

**Requirements:** R09, R10, R11, R15.

**Files:** create `ai_rate_limits.py`; modify `llm.py`, `llm_resources.py`, `model_capabilities.py` only where needed for separate quota provenance, and `ai_pipeline_store.py`; tests **new** `test_ai_rate_limits.py`; existing resource/transport/access tests.

**Interfaces:** `normalize_rate_limits(provider: str, headers: dict[str, str], *, now: float) -> RateLimitSnapshot`; `quota_scope(profile, *, quota_group: str | None) -> QuotaScope`; `admit(scope: QuotaScope, *, estimated_input: int, reserved_output: int, now: float) -> Admission`; `retry_schedule(error, snapshot: RateLimitSnapshot, *, attempt: int, now: float) -> Admission`. Use injected clock/random sources in tests. Preserve sanitized status/error reason and allowlisted headers, never authorization/cookies/raw bodies.

- [ ] Add `test_retry_after_seconds_http_date_and_reset_headers`: header waits win over shorter backoff; stale/malformed hints fall back safely; no busy retry loop or minute-boundary assumption.
- [ ] Add `test_request_and_input_output_token_buckets_both_gate_admission`: free request slots cannot bypass token saturation; output reservation is provider-specific. RPM does not become a concurrency number.
- [ ] Add `test_shared_quota_across_profiles_and_workspaces` and `test_unknown_gateway_quota_uses_conservative_adaptation`: explicit quota groups coordinate; no secret-derived identifier is logged; other applications' usage can only be observed through provider feedback.
- [ ] Add `test_daily_quota_auth_failure_and_temporary_throttle_have_different_outcomes` and `test_wait_is_cancellable_and_persists_until_restart`: permanent errors do not back off forever, daily exhaustion checkpoints, temporary waits become status, polling is offline.
- [ ] Implement optional provider-specific discovery only when a supported endpoint and current permission expose limits. Do not require administrator credentials. Keep model capacity and quota snapshots separate. Start fallback backoff at 1 second, double to 60 with jitter, and persist valid longer provider waits.
- [ ] Run `uv run pytest tests/test_ai_rate_limits.py tests/test_llm_resources.py tests/test_ai_analysis_transport.py tests/test_ai_analysis_access.py -q`; ensure every actual retry still obtains a new attempt ticket and authorization. Commit.

## Task 7: Bounded parallel scheduler and automatic execution rollover

**Requirements:** R02, R05, R06, R07, R09, R10, R11, R15.

**Files:** create `ai_scheduler.py`; modify `ai_pipeline_store.py`, `ai_context.py::AIExecutionContext`, `analysis_service.py`, `llm.py`, `agent/jobs.py`; tests **new** `test_ai_scheduler.py`; existing continuation/jobs/lifecycle suites.

**Interfaces:** `run_pending_requests(store, workspace: str, run_id: str, plan: SourcePlan, policy: BuildPolicy, allowance: ProjectAllowance, *, connections, authorize, progress, cancelled, transport=None) -> dict`; `dispatch_provider_request(request: WorkerRequest, *, connections, cancelled, transport=None) -> WorkerOutcome`. Coordinator admits/reserves/journals; each physical retry returns through admission rather than mutating a shared worker ledger. Worker outcomes are persisted by the owner thread and handed to existing validation.

- [ ] Add `test_parallelism_never_exceeds_custom_workspace_process_or_quota_limit`: out-of-order completions preserve correct source/candidate identity; busy capacity queues instead of surfacing the current admission error as build failure.
- [ ] Add `test_execution_rollover_completes_without_new_user_action`: 2,001 pending singleton attempts with an authorized larger project ceiling cross the 2,000-attempt window, retain the same logical run and publish only once at the end. Use a fake clock and small synthetic limits for routine unit speed; retain a real-size scale case in Task 12.
- [ ] Add `test_lifetime_allowance_is_not_reset_by_rollover_or_reopen`: exact charged/reserved counters remain monotonic, unsent fallback reservations are released, unknown sent attempts retain conservative reservations, waiting time is reported separately from active execution time.
- [ ] Add `test_cancel_stops_new_dispatch_and_keeps_completed_items`, `test_unknown_outcome_blocks_only_affected_required_work`, and `test_reopen_requires_resume_but_never_repeats_completed_units`. No exactly-once billing assertion.
- [ ] Replace shared mutable catalog/review candidates/attempt log with immutable per-request snapshots and coordinator counters. Workers submit per-physical-attempt admission messages through a thread-safe queue; the coordinator reauthorizes, reserves and journals before granting dispatch through a completion event. Retries use that same handshake. The coordinator must keep servicing admissions while awaiting outcomes so this cannot deadlock. Propagate runtime connection/authorization scope explicitly to workers. No worker accesses DuckDB, Streamlit state, global session credentials or a database transaction.
- [ ] Run the scheduler/continuation/jobs/lifecycle suites under deterministic concurrent completions and crash injection. Commit after admission/accounting review.

## Task 8: Link stored facts into scoped table and column relationships

**Requirements:** R03, R08, R12, R14.

**Files:** create `ai_linking.py`; modify `ai_analysis_store.py`, `ai_pipeline_store.py`, `ai_reconciliation.py`, `transformations.py` only where existing materialization needs the resolved snapshot; tests **new** `test_ai_linking.py`; existing reconciliation/schema-provenance/transformations/dbt resolution suites.

**Interfaces:** `load_link_snapshot(store, workspace: str, run_id: str) -> LinkSnapshot`; `link_stored_facts(snapshot: LinkSnapshot) -> LinkReport`; `save_link_checkpoint(store, workspace: str, run_id: str, report: LinkReport) -> None`. Linking is deterministic and consumes accepted stored results, not fresh whole-project model output. Preserve typed dbt resource relations separately from data-flow operations.

- [ ] Add `test_stored_a_to_b_to_c_links_tables_and_columns_without_provider_calls`: match producer/consumer identities, preserve both expressions and intermediate operations; table and column views derive from the same snapshot. Rendering/querying performs zero extraction.
- [ ] Add `test_same_names_in_different_schema_job_project_package_or_version_do_not_merge`, `test_unknown_writer_order_is_unresolved`, and `test_quoted_identifier_case_rules_survive_linking`.
- [ ] Add `test_filter_join_and_rowset_roles_do_not_become_value_derivations`, `test_conflicting_schemas_block_unsafe_wildcard_expansion`, and `test_known_schema_expansion_keeps_both_wildcard_and_schema_evidence`.
- [ ] Add `test_cyclic_components_converge_with_bounded_passes`: cycle handling is deterministic, does not infer execution order or create exponential all-pairs edges, and records unresolved boundaries.
- [ ] Implement indexes by scoped resource/operation/field identity, link deduplication and conflict/coverage reports; checkpoint by accepted-input fingerprint. Do not rebuild all source text in memory or call static parsers to manufacture AI-only facts.
- [ ] Run the new linking and existing transformation/reconciliation/dbt identity suites; verify accepted source provenance survives export/reopen. Commit.

## Task 9: Targeted ambiguity resolution and dbt-aware publication composition

**Requirements:** R01, R03, R08, R12, R13, R14.

**Files:** modify `ai_linking.py`, `ai_validation.py`, `ai_wire.py`, `analysis_service.py`, `services.py`, `dbt/service.py`, `dbt/persistence.py`; create `prompts/project_resolution/system.md`, `user_template.md`, generated resolution schemas; tests **new** `test_ai_resolution.py`, `test_dbt_ai_publication.py`.

**Interfaces:** `plan_resolution_tasks(report: LinkReport, snapshot: LinkSnapshot, *, round_index: int) -> tuple[ResolutionTask, ...]`; `apply_resolution(report: LinkReport, responses: tuple[ValidationReport, ...]) -> LinkReport`; `compose_ai_publication(local_results: list, linked: LinkReport, *, mode: str, dbt_projects: tuple) -> dict`. The composition result contains existing file-result/support/dbt publication inputs; only the trusted final transaction consumes it.

- [ ] Add `test_resolution_sends_only_ambiguity_neighborhood_and_source_evidence`: host-issued candidate/context IDs, full envelope/disclosure checks and current source hashes apply; no giant final project prompt, unrelated source or parser answers.
- [ ] Add `test_resolution_cannot_invent_schema_or_override_validation` and `test_resolution_stops_after_two_rounds_or_no_new_supported_fact`: unresolved remains visible, cycles cannot keep generating new work, budgets include all attempts/review.
- [ ] Add `test_ai_only_dbt_uses_validated_ai_facts_while_hybrid_preserves_parser_comparison`: a dbt catalog can remain structural metadata, but static edges cannot silently replace AI-only facts; AI origins and artifact-declared origins remain distinct.
- [ ] Add `test_dbt_logical_assets_resource_impact_and_generated_evidence_publish_together`: logical model/ephemeral identity, versioned/package refs, source/artifact pointers, column derivations and typed macro/test dependencies remain consistent with the existing resource UI.
- [ ] Reuse existing SQL/SAS validators and safe dbt structure/evidence checks; implement new checks in the AI validation layer only. If semantic interpretation is not supported, abstain rather than weakening acceptance. Use only configured/authorized routes; optional stronger-model escalation is not required for initial delivery.
- [ ] Run new resolution/dbt publication tests plus existing dbt/AI reconciliation and source-acceptance suites. Commit after checking parser-module diffs remain empty.

## Task 10: Integrate one full build, required mixed-source support and recovery

**Requirements:** R01, R02, R03, R10, R11, R12, R13, R14, R16.

**Files:** modify `analysis_service.py`, `ai_analysis_store.py`, `project_analysis.py`, `services.py`, `dbt/service.py`, `agent/service.py`, `agent/jobs.py`; tests existing `test_ai_analysis_runs.py`, `test_ai_analysis_jobs.py`, `test_ai_analysis_lifecycle_followup.py`, **new** `test_ai_full_build.py`, `test_dbt_ai_analysis.py`.

**Interfaces:** retain `preview_analysis`, `run_analysis` and `analysis_report` entry points, with additive preview/progress/report fields. Internal stages become `planning`, `extracting`, `reviewing`, `waiting_provider`, `linking`, `resolving`, `ready`, and existing terminal/paused states. Update every status allowlist/query/recovery check consistently; legacy run readers remain supported.

- [ ] Add `test_single_start_builds_sql_sas_and_dbt_to_one_snapshot`: one Analyze action covers extraction, review, linking, resolution and publication with required file dispositions; no separate merge/graph-generation action.
- [ ] Add `test_selected_dbt_member_discloses_project_closure_before_start` and `test_ordinary_sql_and_dbt_sql_use_correct_handlers`: require appropriate context permission; preserve unselected contributions and source-kind identity across mixed runs.
- [ ] Add `test_old_graph_survives_failure_cancel_stale_and_missing_required_item` and `test_partial_semantics_publish_only_supported_facts_with_complete_false`. Provider failure is not silent parser fallback; a terminal unresolved disposition is distinct from an unprocessed/missing response.
- [ ] Add `test_crash_during_linking_or_before_publication_resumes_without_extraction` and `test_publication_crash_is_atomic_and_idempotent`: prior graph/support/dbt catalog/report either all remain or all advance.
- [ ] Replace project-analysis `reject_dbt_ai` invocation with source-aware preparation now that Tasks 4/8/9 pass. Keep manual assistance rejection where that path lacks project-aware context; update the error to describe that specific limitation rather than saying all AI dbt is unsupported.
- [ ] Keep provider calls outside store locks/transactions; perform final freshness, authorization and publication-revision checks inside the existing short atomic publication path. Bind preservation of accepted AI context dependencies to selected-file rebuilds and retention.
- [ ] Run all AI/dbt/service/retention regression suites. Review changes against baseline static parser behavior; commit integrated build.

## Task 11: Controls, progress and CLI/MCP parity

**Requirements:** R02, R06, R09, R10, R11, R15, R16.

**Files:** modify `ui/analysis_ai.py`, `ui/pages/analysis.py`, `ui/pages/connections.py`, `cli.py`, `project_analysis.py`, `agent/service.py`, `agent/mcp_server.py`, `agent/capabilities.py`; tests existing UI/access/contract/parity/documentation suites and **new** `test_ai_build_policy_interfaces.py`.

**Interfaces:** UI controls and CLI/MCP public names match the request contract. CLI flags: `--max-files-per-request`, `--max-parallel-requests`, `--auto-continue/--no-auto-continue`, `--project-max-provider-attempts`, `--project-max-output-tokens-total`, `--project-max-seconds`. Preserve existing execution flags, resume and explicit unknown retry. Nullable API fields and omission mean Auto. Quota group overrides belong to provider/account configuration, not every file.

- [ ] Add `test_controls_appear_after_enabling_ai_and_do_not_send_requests`: Auto/custom persists with clear units; previews show project context closure and selected dbt mode. Existing local/offline default remains.
- [ ] Add `test_project_window_and_provider_limits_are_labeled_separately`: 12,476 project extraction ceiling is not presented as an impossible 2,000-window setting; reserved output is not billed usage; unknown rate limits stay unknown.
- [ ] Add `test_wait_status_resume_unknown_and_quota_actions_are_distinct`: normal rollover/throttle is informational; daily quota/credit pause is actionable; unknown requests show possible duplicate charge; incomplete graph coverage remains visible.
- [ ] Add `test_cli_mcp_ui_policy_and_source_permissions_match`: all new fields reach the same service, preview is offline, dbt closure requires source/network grants for dispatch, report source details remain permission-gated, cancellation persists.
- [ ] Implement stage/file/unit/cache/queue/in-flight/usage/wait/coverage progress without rerunning full preparation on each poll or Streamlit rerender. UI jobs remain responsive with provider waits. Do not start requests by opening a paused run.
- [ ] Run targeted UI/SDK/CLI parity and documentation registration tests; update exact CLI/MCP reference rows alongside this interface change so commits remain green, then Task 13 completes explanatory guides. Commit.

## Task 12: Qualification, regression and bounded rollout

**Requirements:** R01–R17.

**Files:** extend `scripts/benchmark_ai_analysis.py`, `scripts/benchmark_lineage_archives.py`, `tests/fixtures/ai_analysis/` and dbt fixtures; add **new** `tests/test_ai_pipeline_qualification.py`; update qualification records in `docs/TESTING.md` and `docs/PERFORMANCE.md` only with actual evidence.

**Interfaces:** extend the benchmark with `--scenario {existing,mixed,rate-limit,recovery,scale}`, `--files`, `--units`, `--max-files-per-request`, `--max-parallel-requests`, and existing `--output`; preserve existing flags/readers. Mock scenarios must never use `--live`; live remains explicit checked-in synthetic cases, finite budgets and authorized connections.

- [ ] Freeze synthetic SQL/SAS/dbt gold independent of model output. Assert expected table edges, direct/value dependencies, transformations, contextual roles and expected abstentions separately; existing supplied archives without column gold cannot qualify column precision.
- [ ] Run the 2,200-file/6,238-unit synthetic scenario, with 4,055 safely supported projection tasks where feasible and a two-attempt route matching the screenshot's 12,476 extraction ceiling. Also run a >2,000 actual-attempt singleton scenario to prove rollover, not just a high preview count.
- [ ] Compare batch width 1 versus Auto/custom and concurrency 1 versus 2/4. Record requested/unique/completed units, actual physical attempts, review/resolution/repair attempts, known tokens, conservative unknown usage, retry/wait/active/wall time, peak memory and publication count. Packing cannot claim reduced column-output tokens merely because HTTP call count falls.
- [ ] Exercise small context/output capacity, no native structured output, malformed/partial/reordered batch results, delayed callbacks, 429 Retry-After, stripped headers, daily exhaustion, lost responses, process crash/reopen, changing source/route/permissions during wait, failed publication and cleanup/restore. All checks use isolated runtime homes.
- [ ] Require no repeated successful-unit extraction, no cross-project/temp-name merges, exact host item coverage, one final atomic publication, no partial graph replacement, no secret persistence, concurrency/allowance compliance, and no static-parser regression. Use measured comparisons rather than a universal speedup/accuracy promise.
- [ ] Run `uv run pytest -q`, `uv run ruff check .`, and `uv lock --check` after focused suites pass. Run real CLI and MCP SDK transport plus a browser workflow for SQL, SAS, dbt and mixed input. Run installed-wheel smoke for changed prompts/package assets. Broaden platform/build checks only where changed distribution paths require it.
- [ ] Keep Auto conservative until the source-specific contract/coverage tests pass. Optional bounded live qualification reports precision/recall/coverage and latency by source/model separately; existing targets (99% accepted table-edge precision and 98% accepted value-column precision with stated sample sizes) remain unestablished until independently measured. No paid/private-project calls are implied by this plan.
- [ ] Review full diff and trace every R01–R17 acceptance to evidence. Keep optional provider Batch API, prompt caching, stronger resolver routing and new frameworks out of this required delivery unless separately justified. Commit final core qualification before the documentation closeout.

## Task 13: Update/create detailed documentation pages and GitHub Pages flow

**Requirement:** R18, plus accurate explanation of R01–R17. This is the final implementation phase requested by the user. Documentation sources and the website must tell the same story as the implemented app; do not publish this proposal as delivered behavior.

**Files to update:** `docs/AI_ANALYSIS.md`, `DBT_SUPPORT.md`, `USER_GUIDE.md`, `LLM_INTEGRATION.md`, `PROMPT_ENGINEERING.md`, `ARCHITECTURE.md`, `DATA_MODEL.md`, `DATA_MANAGEMENT.md`, `CLI_GUIDE.md`, `MCP_INTEGRATION.md`, `TESTING.md`, `PERFORMANCE.md`, `TROUBLESHOOTING.md`, relevant section indexes, `README.md` when its current workflow summary changes, `mkdocs.yml`, `tests/test_documentation.py` and affected `KNOWLEDGE.md` maps.

**Create these substantive public pages:**

| Page | Audience and exact content |
| --- | --- |
| `docs/user-guide/ai-analysis-flow.md` | End-to-end user flow: one Start, preparation, reuse, batching, queue, extraction, checkpoints, linking, targeted resolution and final table/column views. Explain file versus unit versus request with a worked two-file example. Include the overall Mermaid flow. |
| `docs/user-guide/ai-analysis-controls-and-recovery.md` | Auto/custom files per request and parallelism, model fit, execution versus project allowance versus provider quota, 12,476/2,000 example, normal waits, cancellation, reopen/Resume, unknown-response duplicate-charge warning, source changes and partial coverage. Include a recovery sequence/state diagram. |
| `docs/architecture/ai-analysis-pipeline.md` | Developer flow/contracts, durable request/item/attempt and dependency records, coordinator/worker ownership, quota scopes, exact evidence, cache invalidation, linking/cycles/writer ambiguity, atomic mixed-source publication and origin/confidence boundaries. Include state transitions and a database-to-graph diagram. |

**Canonical ownership:** `AI_ANALYSIS.md` stays the overview/mode/limits entry point and links to the new pages. `DBT_SUPPORT.md` owns the detailed dbt source/enriched/artifact semantics, context closure, templates/macros/ref/source and evidence origin. CLI/MCP files own exact executable references. Other pages link rather than copying large explanations. This gives multiple useful pages without maintaining competing descriptions.

**Interfaces:** MkDocs `nav` is the explicit publication list; `scripts/docs/hooks.py` lowercases public output routes and excludes plans/specs/knowledge maps/unlisted files. Existing `.github/workflows/docs.yml` validates PRs and deploys validated `site/` on the default branch. Do not hand-edit `site/`, broaden the publication allowlist to the whole checkout, or add a second hosting pipeline.

- [ ] Update overview and all stale claims: dbt project AI is now supported for the implemented subset; automatic rollover is distinct from post-restart Resume; the previous fixed projection trigger is described according to delivered fitting; project windows and rate scheduling are distinct; limitations/unknown billing/semantic coverage remain explicit. Preserve the local parser as the default and do not imply model setup automatically sends source.
- [ ] Write the three pages above with accurate screenshots from isolated fixtures where helpful, typed tables and renderable Mermaid diagrams. Cover SQL, SAS and dbt contexts, source/artifact/generated provenance, saved facts through table and column graph construction, and why no final whole-project model call is required.
- [ ] Register them under User guide and Architecture in `mkdocs.yml`; update `docs/user-guide/index.md`, `docs/architecture/overview.md`, onboarding/troubleshooting links and the AI overview. Keep existing URLs. Any new static diagram/screenshot is individually allowlisted in `extra.public_assets`.
- [ ] Update exact CLI flags/MCP inputs and capability descriptions; add documentation checks for new pages/anchors and for exclusion of internal `docs/superpowers/specs/`/`plans/` from HTML/search. Assert documentation neither promises universal low-model accuracy nor treats RPM as simultaneous requests.
- [ ] Refresh `DATA_MODEL.md`/management with additive schema, quota/attempt state, dependencies, retention and recovery; update performance/testing with dated actual measurements, source/model/sample size and mock versus live distinctions. Do not relabel historical failures as new success.
- [ ] Run `uv run --group docs python scripts/docs/build.py` and `uv run --group docs pytest tests/test_documentation.py -q`. The exact clean artifact destined for Pages must pass strict Markdown/nav/link/fragment/search/publication inventory checks.
- [ ] Preview desktop/mobile, keyboard access, all four site themes, search and Mermaid rendering. Verify published routes retain the `/GraveTrail/` prefix. Confirm source/secret/private runtime paths are absent from site output.
- [ ] Update/create affected `KNOWLEDGE.md` maps and scan bookkeeping. Review/commit the documentation alongside the feature. When integration/publication is later authorized, use the existing PR/default-branch workflow; confirm hosted pages and diagrams after deployment. A local build alone is not evidence of hosted publication.
- [ ] Final acceptance: one explicit build covers SQL/SAS/dbt to table/column lineage; all required recovery/accounting/quality gates have recorded outcomes; static parser behavior is preserved; the multi-page public explanation matches shipped controls and flow; no required task is described as delivered while unchecked.
