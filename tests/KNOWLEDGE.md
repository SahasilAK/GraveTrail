# tests/

Column transformation regressions: `test_sql_transformations.py` covers projection source
spans/roles, scoped CTEs, UNION/INSERT and unsupported grammar; `test_sas_transformations.py`
covers ordered variables, SET options and unresolved runtime functions; `test_transformations.py`
pins storage, old-home migration/restore, immutable revisions, wildcard mappings, unknown writers,
bounded cycles and cleanup. It also pins equivalent/escaped quoted names, literal marker
identities, positional INSERT wildcard targets, limit-independent row effects and old-cache
reanalysis boundaries. `test_transformation_sas_integration.py` verifies SAS traces/jobs;
`test_transformation_access.py` checks native AppTest, CLI/MCP parity, real SDK stdio, source
permissions, continuation budgets and stale widget identities.

Unit, integration, security and AppTest regressions. Use temporary Store homes; no live LLM keys required. tests/fixtures supplies real deterministic input.

## Subfolders
- `fixtures/` — [fixtures/KNOWLEDGE.md](fixtures/KNOWLEDGE.md).
- `sample_data/` — SQL and SAS sample project ZIPs for loading sample data into the application during testing. See [sample_data/KNOWLEDGE.md](sample_data/KNOWLEDGE.md).

## Files
- `test_excel_exports.py` — Independent OOXML checks for ordered paths/steps, branches, job identities, continuations, cycles/isolated assets, evidence counts, inert text, global relationship/evidence/text bounds and temporary cleanup on failure/timeout.
- `test_excel_artifacts.py` — Real workspace, CLI download, MCP and Explorer XLSX preparation; original-hash evidence, explicit raw-source disclosure, stale analysis and authorization revocation.
- `test_cleanup.py` — Preview staleness, workspace/source dependencies, active jobs/providers, shared blobs, path hardlinks/traversal, scoped backup denial, integrity-checked new-home restore, CLI/MCP and UI backup/rebuild.
- `test_connections.py` — Session isolation, expiration/disconnect, read-only session connect and explicit process-environment entry; validation preserves environment on failure, masked fields clear, environment values are not cached in sessions or saved data/logs, and provider echoes stay redacted across mid-request rotation. Sanitization depth/cycles/shared references/input preservation.
- `test_provider_setup.py` — Unsaved endpoint/credential/test/model order, actual environment entry, mocked HTTP discovery and fetched selection save; endpoint changes invalidate lists, failed discovery allows manual entry, remote checks honor privacy, and non-string model IDs are excluded.
- `test_distribution.py` — Runtime home/theme preservation, integrity path/tamper errors, build environment isolation and real wheel/sdist dummy secret/database exclusion canaries.
- `test_agent_service.py` — Shared SQL/SAS/CSV queries/cache, ambiguity, paging/depth/budgets, stale inputs/config, permissions/source boundaries, jobs/crash states and nonblocking/revoked status.
- `test_agent_cli.py` — No-UI subprocess help, authorization/errors, real import/background build/status/export and polling revocation/budgets.
- `test_agent_mcp.py` — Official SDK tool parity/resources/prompts, actual stdio client, authenticated HTTP client/refusals and status responsiveness while a query waits on ingestion.
- `test_agent_settings.py` — Agent settings AppTest, generated client config, local handler test and durable source/access revocation.
- `test_explorer_evidence.py` — Missing-asset warning/search regression; Graph direction and active Tree tab scope source files; explicit graph evidence selection overrides it.
- `test_lineage_qol.py` — AppTest for full disconnected All beyond focus limits, direction/combined evidence, Back/Forward branching and exact graph focus across search/shared context, including the 501st asset; history restores Tree tab and traversal controls.
- `test_column_qol.py` — Real imported schema/usage lists and comma filtering; deduplication, schema-minus-usage and unknown wildcard/schema coverage.
- `test_inventory_controls.py` — CSV sample bounds/portability/cache refresh and immediate post-analysis inventory status counters.
- `test_storage_locations.py` — Explicit/bounded path choices, two-session switching/back with retained sources and failed-open preservation.
- `test_vendor_fixtures.py` — Exact labeled dependency/direct-column/temporary sets for six SQL dialects and SAS in LF/CRLF, original evidence and warm-cache preservation.
- `test_job_identity.py` — Cross-job temporary/schema/column isolation, global persistent paths, mixed-lifetime diagnostics, AI refresh, history/exports and Settings/chooser UI regressions.
- `test_temporary_cleanup.py` — Scope/age/count bounds, changed preview/journal failures, idle guard, recovery after restart/no overwrite, atomic publication failure, v3 migration and UI cleanup/restore. Windows symlink privilege may skip one test.
- `test_remaining_settings.py` — Extension/folder precedence, PROC SQL dialect, non-destructive graph filtering, safe log level, portable/UI preferences and selected cache-upgrade preservation.
- `test_llm_resources.py` — Chunk coordinates/statement/SAS context, concurrent admission/release, cancellation/no transmission, connection gate and explicit single-chunk UI request.
- `test_ai_results.py` — Task schemas, invented/ambiguous/transitive/comment/string attribution, historical advisory merge exclusion, saved offline UI results and stale-source warnings.
- `test_assistance_queue.py` — Current diagnostic eligibility/bounds, SQL/SAS focused context, isolation, privacy, quarantine/inferred merge and preview-hash race refusal using synthetic HTTP only.
- `test_exports.py` — Escaped reports/original ZIPs, path evidence/order, live/offline appearance parity and Node syntax/DocumentFragment mount regression; double-click cancels single-click selection, exact node clipboard payload, shadow-root fullscreen enter/exit.
- `test_graph.py` — Graph traversal plus missing-endpoint regression: evidence retention, valid search/rows and incomplete path propagation. Run with pytest; temporary runtime data only.
- `test_lineage_tree.py` — AppTest covers lazy compact branches, Expand all/Collapse all, inline files, both directions, optional evidence details, cycle stops and depth/entry limits.
- `test_hardening.py` — Behavioral regression tests for hardening. Run with pytest; temporary runtime data only.
- `test_ingestion.py` — ZIP/browser/directory ingestion; unapproved absolute/relative/traversal/sibling-prefix paths and empty roots fail before filesystem access. Valid roots, normalized nested paths and filesystem-root allowlists preserve original bytes. Symlink escape/child exclusion runs where OS permissions allow link creation. Temporary data only.
- `test_llm.py` — Provider protocols, grounding/privacy, fenced JSON rejection boundaries, malformed HTTP envelopes including 80/1100-level nesting across Python decoder versions, and inferred merge retention. Temporary runtime data only.
- `test_logging.py` — Behavioral regression tests for logging. Run with pytest; temporary runtime data only.
- `test_maintenance.py` — History archive/restore bounds, workspace/reference protection, idempotence, tamper rejection, transaction rollback, v3 migration and journal recovery after lost file/restart.
- `test_sas.py` — Static SAS rules, FORMAT=/LENGTH=/CALCULATED/DATETIME(), nested scope, malformed modifiers, exact evidence and no phantom source columns.
- `test_sas_project.py` — Real SAS ZIP exact 128 logical edges, seven layers/all 16 sources, WORK collapsing, original evidence, warm reuse and parser-version cache upgrade.
- `test_schemas.py` — Typed DDL/wildcard eligibility, conflicts/changes/inheritance, cache refresh, disabled extraction, identical declarations, unqualified invalidations, SWAP/RENAME and no CSV name guessing.
- `test_sql.py` — Behavioral regression tests for sql. Run with pytest; temporary runtime data only.
- `test_parser_static_wrappers.py` — PostgreSQL SQL procedure/Snowflake literal wrappers and SAS %LET expressions; conservative runtime/bind/mutation rejection, nesting/resource bounds, exact LF/CRLF evidence, persisted service queries, warm caches and newline-tamper detection. Subprocess deadline covers 100k-space/comment ReDoS; header variants and dialect-specific comment nesting preserve the procedure guard.
- `test_store.py` — Behavioral regression tests for store. Run with pytest; temporary runtime data only.
- `test_themes.py` — Exact Ocean/Ink preservation and Ocean default, eleven atomic preset saves, sidebar-layout transitions, invalid-sidebar rollback, custom native-color startup, semantic graph roles and readable action/link contrast.
- `test_ui.py` — Page/workspace/provider flows, complete eleven-theme dropdown, schema/history, visualization/source defaults and workspace selection resets; diagnostic preview/stale-click refusal/synthetic request/explicit merge. Temporary data only.
- `test_workflow.py` — Behavioral regression tests for workflow. Run with pytest; temporary runtime data only.
- `test_workspace_configuration.py` — Workspace edits preserve identity/data; safe v1/v2 configuration portability, resource validation, isolation and injected-failure rollback.

- `test_parity_contracts.py` — complete catalog IDs/cursors, actual MCP/CLI discovery and independent/scoped launch authorization.

- `test_parity_settings.py` — Seven typed schemas/defaults/ranges, atomic revisions, privilege non-escalation and local admin recovery; rejects process-cap/launch-policy patches.
- `test_parity_providers.py` — Approved origin/reference checks, runtime isolation/profile-edit invalidation, sanitized mocks, no environment mutation and immediate concurrent admission.
- `test_parity_ai.py` — All five tasks through actual MCP handlers, exact hash/job race refusal, per-fallback credentials, explicit idempotent merge and concurrent refresh storage access.
- `test_parity_reports.py` — Scoped dictionary/schema/history/evidence, CLI exact literal matches and configured >10k ZIP discovery admission.
- `test_parity_artifacts.py` — Exact raw bytes/hashes/chunks/ZIP, source revocation, scoped IDs, CLI exclusive output, enriched graph/path evidence, combined tree and cycle incompleteness.
- `test_parity_maintenance.py` — Read-side effect absence, mandatory backup guards, fresh local archive/recovery in disposable homes; general cleanup backup opt-out refused.
- `test_parity_runtime.py` — Eleven shared themes/TOML preservation, actual logging/setup/self-test MCP, application scope and CLI settings.
- `test_parity_coverage.py` — Every keyed catalog field/CLI route/help/MCP schema and all mutation/network tool denials under a read-only launch.
- `test_parity_ui.py` — Equal asset labels across workspaces retain selectable widget identity, reproducing the real-browser regression.

- `test_documentation.py` — Exact CLI/MCP reference coverage against registered routes/flags/inputs/resources/prompts, plus public-source safety, Windows route collisions, rendered anchors/project prefixes and artifact inventory rejection.

Distribution regression verifies source archives exclude agent context (plans, AGENTS.md, KNOWLEDGE.md, .kbignore and .codex) while retaining release tooling. KNOWLEDGE.md maps are tracked in the repository for navigation; package contents are tested separately.

- `test_release.py` — Exact/highest stable-release bump resolution, uv project/lock materialization without dependency changes, Windows explicit-directory installer/source/trust gates and legacy three-platform staging integrity; no overwrite, Copilot fallback and preserved release records.
- `test_windows_installer.py` — Real Windows mutex lifetime plus per-user/no-force-close/no-data-delete installer and explicit production signing/timestamp policy contracts.

Rebrand regressions: distribution script aliases, unrelated-brand/stale-version wheel exclusion and /GraveTrail/ documentation link validation; AppTest sidebar/client examples; export titles; MCP identity and equivalent new/legacy resource URLs; exact new/legacy cleanup and CLI restore confirmations with byte-exact originals.

Frozen-dispatch regression executes the real frozen entry script with a captured CLI and asserts gravetrail is the program name.

Documentation regressions walk real Typer routes/groups/flags/positional arguments and SDK MCP tool/input/resource/prompt registrations, requiring exact checked-in reference coverage and no duplicate/stale rows. Discovery uses isolated temporary storage and makes no provider calls.

`test_navigation_redesign.py` — Sources/Analysis/admin boundaries, no writes on navigation, hidden source/diagnostic laziness, persistent cross-page and related-view asset/file selection, workspace/reimport invalidation, existing-provider protocol preservation and pending-diagnostic source safety with manual assistance retained. Evidence tests additionally pin changing browser source-widget identities and hidden Tree direction persistence. Distribution canaries require packaged CSS bytes.

Theme regressions preserve Ocean/Ink, exercise eleven atomic saves and apply Rose Circuit through AppTest. `test_site_themes.py` verifies eleven published schemes, original Ink/Celadon and shared app/site/sidebar token parity.

Graph image regressions: test_graph_images.py parses inert XML, shares UI paths, checks Unicode/titles, PNG dimensions/backgrounds, bounds, renderer failures/timeouts and concurrency. test_image_artifacts.py covers service/UI/MCP/CLI parity, permissions, stale/filter coverage, cyclic temporary ordering and failed publication cleanup. test_exports.py JS fixtures include shared bounds.

- `test_ai_analysis_contracts.py`, `test_ai_analysis_context.py`, `test_ai_analysis_transport.py` — Strict project contracts, exact complete-unit planning, declaration conflicts, provider truncation and per-physical-attempt limits. `fixtures/ai_analysis/` contains separate synthetic holdout semantics/abstention labels, not live accuracy evidence.
- `test_ai_analysis_validation.py`, `test_ai_analysis_reconciliation.py` — Complete-source semantic negatives, SQL DML gaps, dependency roles, sparse accepted pairs, writer identity and parser/AI omissions.
- `test_ai_analysis_runs.py`, `test_ai_analysis_schema_provenance.py` — Mock HTTP extraction/review through atomic publication, freshness/CAS, retained declaration context, exact schema statement identities, compact review bounds and token accounting; repeated owner close/reopen preserves all historical support across cached builds.
- `test_ai_analysis_persistence.py`, `test_ai_analysis_lifecycle_followup.py` — Additive upgrade, accepted offline rebuilds, support rebinding, retention/privacy, backup/cleanup/integrity and unresolved artifact boundaries.
- `test_ai_analysis_access.py`, `test_ai_analysis_jobs.py`, `test_ai_analysis_ui.py` — Launch/credential/source policy, detached full-grant jobs/cancel markers, unchecked UI defaults, offline preview, terminal report selection/refresh and full progress rendering from integer journal completion.
- `test_ai_analysis_evaluation.py` — Role/scope/version-aware offline scoring, explicit live opt-in/limits and isolation across multiple benchmark workspaces; no normal provider use.

Automatic AI tests: `test_model_capabilities.py` validates metadata/identity/freshness; `test_ai_wire.py` covers strict compact refs and canonical expansion >16MB; `test_ai_budget.py` covers full envelopes and 1000-unit bounds; `test_ai_analysis_continuation.py` covers partial outcomes/reopen/deadline between extraction-review, unknown attempts and zero-work avoidance. UI tests cover edit/reset/context action and rejected provider inputs never enter default history. Access suite uses the real MCP HTTP SDK for auto+resume.

Navigation uses a non-minimum custom budget to detect widget cleanup; Continue preserves saved API/CLI limits. Constrained fallback transport must send only to the fitting primary. Wide claim tests bound repeated host detail; final durable claims reference original source instead of duplicating quotes.
