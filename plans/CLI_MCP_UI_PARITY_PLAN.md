# CLI and MCP UI Parity Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement this plan task by task. Track the checkboxes and coverage IDs below. This document is a plan, not evidence that any proposed command or tool exists.

**Goal:** Make every current UI capability discoverable through CLI and MCP, implement equivalent headless operations wherever policy permits, and explicitly report the few operations restricted to a local human interface.

**Architecture:** Extend the existing shared services and validated contracts; keep CLI, MCP and Streamlit as thin adapters. Reuse parsing, evidence, LLM, exports and maintenance implementations. Preserve current commands, tool names, response formats, workspaces, source versions and credentials.

**Tech stack:** Python 3.11+, Typer, official MCP SDK, Pydantic, DuckDB, Streamlit, SQLGlot and NetworkX; existing pytest/Ruff tooling.

**Specification and context:** [MASTER_PROMPT](../docs/prompts/MASTER_PROMPT.md), [maintenance specification](../docs/prompts/FEATURE_MAINTENANCE_AND_DEPLOYMENT.md), [AGENTS](../AGENTS.md), [current status](IMPLEMENTATION_STATUS.md), [existing agent plan](AGENT_INTEGRATION_PLAN.md), [CLI guide](../docs/CLI_GUIDE.md), [MCP guide](../docs/MCP_INTEGRATION.md). This plan implements the user's request following the complete UI-only inventory discussed on 2026-10-16.

**Status (2026-10-17):** All nine source slices implemented. Actual catalog/checked fixture account for46 IDs:36 implemented equivalents and10 policy-restricted capabilities. Full regression320 passed/1 existing privilege skip; actual CLI/MCP/running UI, both ZIPs and bounded live checks recorded in [PARITY_ACCEPTANCE.md](PARITY_ACCEPTANCE.md). Standalone downloaded offline-HTML browser interaction and new release-artifact gates remain open below. The section4 command/tool names were design targets; [the user matrix](../docs/CLI_MCP_CAPABILITIES.md) and checked fixture contain the exact shipped names.

## 1. Completion boundary and existing coverage

Existing CLI/MCP workspace creation/listing/summary, source discovery/retrieval, imports, deterministic analysis, asset search, lineage, column usage, diagnostics, impact, jobs and ordinary lineage exports remain supported. CLI already has guarded workspace cleanup and database inspection/backup/checkpoint/restore. MCP already has cleanup inspection/preview. Reuse and extend these; do not create parallel implementations.

Every coverage ID in section 4 must end in one of two tested states:

1. **Implemented:** CLI and MCP both expose the permitted headless equivalent, with shared service behavior and documentation.
2. **Policy restricted:** discovery names the capability, explains the restriction and provides the applicable local CLI/UI route. Do not count a restriction as full operational parity.

Interactive graph selection, tree expansion, browser upload dialogs and changing a browser's active workspace/home have no literal headless widget equivalent. Their data/query/export operations must be available; CLI/MCP select explicit workspace IDs and a launch-time home. Do not build a browser controller into either adapter.

## 2. Global constraints and required policy exceptions

- Preserve all source bytes, original statement/file/line/method evidence and user settings. Never execute imported SQL/SAS or invent dependencies.
- Keep one DuckDB owning process per home. Do not add a second writer, copy an open database, or silently restart the UI to run CLI commands.
- New configuration is schema validated and allowlisted; no arbitrary setting keys, environment enumeration, SQL, filesystem paths or general RPC execution.
- Read-only remains the default. Existing write permission is necessary but insufficient for external AI, configuration administration or application-wide operations.
- Runtime secrets use named read-only launch variables or `RuntimeConnections`. New session references use `DATAFORGE_`; explicit legacy launch references such as `OMNIROUTE_API_KEY` remain supported. Never persist secret values or mutate `os.environ` for session credentials.
- Never place a secret value in CLI arguments, MCP tool arguments/results, prompts, audit trails, diagnostic reports, configuration transfers or job journals. No secret-export API.
- All existing path/root, ZIP, resource, freshness, pagination, audit and workspace isolation guards remain effective.
- Current `AGENTS.md` explicitly says **shared cache/orphan/application cleanup is UI-only** and **MCP cleanup remains read-only**. Retain these restrictions. MCP previews must not delete, archive, restore, checkpoint, clear caches or trigger automatic cleanup as a side effect.
- General destructive cleanup requires a fresh guarded preview, explicit local confirmation and a recoverable full-home backup. Specialized history/staging recovery is not a replacement for that backup. Whole-home restore always targets a new destination.
- MCP must not broaden its own access policy, source permissions, external-network permission, filesystem roots or response ceiling. Administration commands must not bypass startup restrictions.
- Do not change the master prompt, overwrite unrelated `.gitignore` changes, add hosted authentication systems or implement unrelated parser/packaging work.
- Live OmniRoute acceptance uses `http://localhost:20128/v1`, `auto/best-reasoning` and the existing named `OMNIROUTE_API_KEY` launch reference. No fixed-route substitution. Use bounded calls and stop repeated failures as requested by the user.

### Policy exceptions that remain visible in the completed product

| Operation | CLI target | MCP target under current policy |
| --- | --- | --- |
| Shared parser/Streamlit cache cleanup, orphan blobs, full application reset | Explain and direct to UI; no new apply command | Inspect/preview only; no apply tool |
| Workspace cleanup/reset/deletion | Preserve guarded existing CLI apply | Inspect/preview only |
| History archiving and staging cleanup, including automatic cleanup | New guarded local CLI operations | List/preview/recovery status only; no mutation |
| Recovery restores and database checkpoint/backup | Local CLI with existing/new explicit guards | Safe metadata inspection only; no maintenance mutation |
| Broaden agent/privacy/network permissions | Explicit local administrator CLI/UI operation | Read status and return `requires_local_admin`; cannot self-grant |
| Enter a raw runtime secret | Hidden local input for the current operation; UI session input | Use only a preapproved named launch reference; no raw-secret parameter |
| Switch the active data home | Existing `--home` selects a separate invocation | Relaunch against another authorized home; no tool switches a live server |
| Clear a running UI's in-memory cache or connection | UI owner performs the action | Cannot clear another process/session's resources |

If future work intentionally removes one of these boundaries, it needs an explicit policy revision, threat review, updated AGENTS/docs and dedicated regression tests. This plan does not silently authorize such a revision.

## 3. Common command, tool and response contracts

### 3.1 Discoverability and compatibility

- Add `dataforge capabilities` and MCP `get_capabilities(workspace_id?)`. Return versioned entries with `capability_id`, CLI command, MCP tool, scope, read/write/network effects, required startup permissions, availability and restriction reason. Do not list denied workspace identities or secret references from other scopes.
- Add CLI `settings schema|get|update` and MCP `get_settings_schema`, `get_workspace_settings`, `update_workspace_settings`. Sections: `parsing`, `analysis`, `resources`, `visualization`, `privacy`, `agent_access`, `temporary_cleanup`. Application logging/theme use separate application-scoped operations.
- CLI examples below omit the existing global flags: `dataforge --home HOME --json [--allow-write ...] COMMAND --workspace ID`. All workspace mutations and reads require an explicit workspace ID; application-wide commands reject workspace-scoped launches.
- Proposed additional launch permissions: `--allow-config-write`, `--allow-llm`, repeated `--allowed-llm-origin ORIGIN`, repeated `--allowed-credential-ref NAME`, unrestricted-owner `--allow-application-config` for theme/logging, and local-CLI-only `--allow-admin` for permission administration. They narrow authority in addition to `--allow-write` and existing workspace settings; none can be changed by an MCP request. Neither administrator flag grants a scoped launch access to another workspace.
- Configuration mutations use a bounded UTF-8 JSON file on CLI and typed JSON objects on MCP. Reject unknown fields, wrong types, unrecognized versions and partial invalid updates atomically. Do not accept a generic SQL/key/value escape hatch.
- Return current values plus defaults and scope where safe. A settings mutation returns `changed_fields`, `settings_revision`, `analysis_required`, `reload_required` and warnings; never run analysis or call a provider implicitly.
- Use `expected_revision` for settings/profile/routing mutations and preview hashes for destructive actions. Return `conflict` on stale requests instead of overwriting concurrent UI changes.
- Preserve current CLI JSON/human output and exit codes. Add stable bounded errors: `conflict`, `credential_unavailable`, `requires_local_admin`, `requires_local_ui`, `network_not_allowed`, `validation_failed` and `source_changed`, using existing `AgentError` envelopes.
- MCP successes retain a single `structuredContent` object. Tool annotations accurately distinguish reads, local writes and outbound network operations. Annotation hints never replace authorization checks.

### 3.2 Scope, credentials and outbound requests

- CLI may use a saved profile's permitted launch variable or a `--credential-prompt` option on `providers test|models` and `ai request`; hidden input creates a `RuntimeConnections` scope only until that invocation ends. No misleading durable `credentials connect` command for a process that immediately exits.
- MCP `connect_runtime_reference(workspace_id, profile_id)` binds only the profile's already approved, startup-allowlisted launch reference into that server's runtime context. `get_runtime_connection_status` returns booleans and reference names only. `clear_runtime_connection` clears only that authorized context, never UI credentials or unrelated workspace bindings.
- Do not discover environment variable names or let a profile point at arbitrary process secrets. CLI/UI administrator provisioning explicitly approves references; enforce that allowlist before connecting or invoking a provider.
- Server-scoped runtime connections follow the current one-trust-group-per-MCP-server model. Bindings are isolated by workspace/profile; they are not independently authenticated multi-user sessions. Cleanup on shutdown and exceptions; no credentials in background job serialization.
- Provider model discovery and test completions are outbound operations even when they do not send source. Require `--allow-llm`, an allowed exact recipient origin, and the applicable workspace privacy gate. Revalidate redirects and fallback origins; no metadata-endpoint or arbitrary-URL proxy.
- AI requests additionally require source permission, the exact file/range/hash and an explicit task. Never transmit source merely because a read query, settings update, chunk preview or diagnostic list was requested.
- MCP may tighten privacy/access settings within startup authority. Enabling transmission, complete-source access, history storage, disabling redaction, widening access/budgets or disabling read auditing requires local administrator authority. Return the exact local action needed, without executing it.

### 3.3 Bounded data and artifacts

- Reuse `QueryOptions`: limit50/max500; depth15/max30; max_items2000/max20000; max_chars12000/max100000, further capped by workspace policy. New list operations use stable ordering/cursors and report `count`, `total`, `next_cursor`, `complete` and relevant revision/freshness.
- Keep current MCP64KB request-body cap. Configuration import accepts a typed inline object that fits the request or an explicitly allowed local input file capped at1MB. No unbounded upload tool.
- Large HTML/ZIP/source/backup downloads return a scoped artifact ID, MIME type, byte size, checksum and completeness; never embed a ZIP or full HTML graph in a normal tool response.
- Extend `export read`/`get_export` additively with bounded byte-range/base64 retrieval for binary artifacts. Default chunks max16KiB before encoding, reduced further to the response budget. Bind IDs to home/workspace/content version and authorize every read; no caller-chosen server output path.
- CLI artifact download writes to a new destination exclusively unless a separate explicit overwrite option is deliberately supported and tested. MCP input/output paths are restricted to launch-approved roots or application-managed artifact IDs.
- Source-related artifacts require source permission at creation and retrieval, including after revocation. Historical source downloads refer to pinned source hashes, not whichever file is current. Whole-home backup downloads remain local-CLI/UI only; MCP artifact retrieval must reject backup IDs even when an administrator can inspect backup metadata.

## 4. Complete UI-to-CLI/MCP coverage checklist

Names below are proposed interfaces, not existing commands. A grouped row still requires every listed field/action. **R** denotes a policy-restricted MCP or local-only operation from section2.

| ID | UI capability and required coverage | Proposed CLI | Proposed MCP | Slice |
| --- | --- | --- | --- | --- |
| P01 | List/get/create/edit/remove provider profiles; name/provider/URL/model/reference/auth/timeout/retries/max_tokens/context_chars/temperature/structured/Azure API version | `providers list\|get\|save\|remove` | `list_provider_profiles`, `get_provider_profile`, `save_provider_profile`, `remove_provider_profile` | 3 |
| P02 | Session connect/status/clear; reference compatibility and restart behavior | `providers credentials status`; per-call `--credential-prompt` | `connect_runtime_reference`, `get_runtime_connection_status`, `clear_runtime_connection` (R for raw input) | 3 |
| P03 | Model discovery with sanitized results | `providers models PROFILE_ID` | `discover_provider_models` | 3 |
| P04 | Actual model connection test and sanitized usage/failure | `providers test PROFILE_ID` | `test_provider_connection` | 3 |
| P05 | Default profile, each of five task routes and ordered fallback profiles | `providers routing get\|update` | `get_model_routing`, `update_model_routing` | 3 |
| A01 | Selected evidence analysis: SQL lineage, SAS lineage, lineage validation, column usage, code explanation | `ai request` | `request_ai_assistance` | 4 |
| A02 | Offline statement chunk preview, selected chunk/range and budget information | `ai chunks` | `preview_ai_chunks` | 4 |
| A03 | Unresolved warning/error review queue, recommended source context, custom bounds and explicit AI review | `ai review list\|preview\|request` | `list_review_candidates`, `preview_diagnostic_review`, `request_diagnostic_review` | 4 |
| A04 | Saved AI result list/get, outcomes/quarantine, source-job/hash warnings, advisory download and AI activity/usage/duration | `ai results list\|get\|export`; `ai activity` | `list_ai_results`, `get_ai_result`, `export_ai_result`, `get_ai_activity` | 4 |
| A05 | Explicit validated lineage merge as inferred and graph refresh; no advisory merge | `ai merge RECORD_ID` | `merge_ai_claims` | 4 |
| S01 | Default SQL dialect, per-folder/per-extension overrides | `settings get\|update parsing` | Workspace settings tools | 2 |
| S02 | Case-sensitive identities, wildcard expansion, CSV sample rows | Same | Same | 2 |
| S03 | SAS library mappings, static macros, default job/session and folder job assignments | Same | Same | 2 |
| S04 | Saved minimum confidence, include_inferred, diagnostic visibility, reanalysis mode | `settings get\|update analysis` | Workspace settings tools | 2 |
| S05 | max_file_mb1–100, max_files1–100000, parse_workers1–8 | `settings get\|update resources` | Workspace settings tools | 2 |
| S06 | AI workspace concurrency1–4, process cap8, chunk_chars500–100000 | Same; schema exposes process cap read-only | Same | 2 |
| S07 | external_llm, allow_full_source, max_context_chars500–100000, redact_secrets, llm_history, retention_days1–3650 | `settings get\|update privacy` (admin for widening) | Read/update with non-escalation restrictions (R) | 2 |
| S08 | Application logging DEBUG/INFO/WARNING/ERROR, persisted per home | `application logging get\|update` | `get_application_logging`, `update_application_logging` | 8 |
| S09 | Agent enabled/write/source permissions, default detail, max_chars512–100000, audit_reads | `settings get\|update agent_access` | Read; safe tightening only (R) | 2 |
| S10 | Actual local MCP-handler check, available schemas and generated Codex/Claude stdio/HTTP examples | `agent inspect\|self-test\|client-config` | `get_agent_setup`, `test_local_agent_access`; capability discovery | 8 |
| W01 | Rename existing workspace and edit description | `workspace update` | `update_workspace` | 2 |
| W02 | Export allowed configuration and create new workspace from v1/v2 configuration; exclude profiles/secrets/privacy/source/history | `workspace config export\|import` | `export_workspace_configuration`, `import_workspace_configuration` | 2 |
| W03 | Storage locations/home status and current browser home selection equivalent | `runtime info`; existing `--home` | `get_runtime_info`; relaunch guidance (R for live switching) | 8 |
| W04 | Analysis and ingestion run lists/details, inventory file_size/encoding/metadata and import diagnostics | `runs list\|get`; `ingestions list\|get`; extend `source list`; `source metadata` | `list_analysis_runs`, `get_analysis_run`, `list_ingestion_runs`, `get_ingestion_run`, extended source inventory and `get_source_metadata` | 5 |
| W05 | Baseline/comparison run diff and JSON download | `runs compare BEFORE AFTER` | `compare_analysis_runs`; artifact export | 5 |
| V01 | Fourteen theme presets, detected/configured/loaded theme and explicit apply | `application theme list\|get\|apply` | `list_theme_presets`, `get_application_theme`, `apply_application_theme` | 8 |
| V02 | Saved graph node limit10–1000, traversal depth1–30, tree expansion0–30, upstream/downstream/combined, collapse temporary | `settings get\|update visualization` | Workspace settings tools | 2 |
| V03 | Graph labels compact/full/hidden, semantic/neutral palette, width1–5, source complete/relevant and line numbers | Same | Same | 2 |
| V04 | Interactive graph/tree/edge/node focus, expand/collapse and column grouping/filter equivalents | Extend lineage/detail/column queries with bounded filters; no widget commands | Same query equivalents, including graph/tree data | 6 |
| R01 | Data dictionary: declared SQL types, sampled CSV types, fallback direct references, provenance and unknowns | `dictionary list` | `get_data_dictionary` | 5 |
| R02 | Declared schema columns plus original DDL evidence | `assets schema ASSET` | `get_asset_schema` | 5 |
| R03 | Dashboard hotspots, isolated/temporary assets, cyclic groups and parsing-status counts | `workspace health` | `get_workspace_health` | 5 |
| R04 | Standalone stored-lineage evidence check (does not analyze or repair) | `lineage validate` | `validate_stored_lineage` | 5 |
| R05 | Dependency paths in both directions, max_paths1–500, depth, temporary view, boundaries and exports | `lineage paths`; `export paths` | `get_dependency_paths`, `export_dependency_paths` | 6 |
| R06 | Step-wise lineage rows/logical dependency order with evidence; no inferred runtime order | `lineage steps` | `get_lineage_steps` | 6 |
| R07 | Code search matching line numbers/snippets and report export, beyond current metadata-only file search | Extend `source search --include-matches`; `export report --kind code-search` | Extend `search_source_code` with opt-in matches; `export_report` | 5, 6 |
| E01 | Interactive offline graph HTML and graph visualization JSON with appearance | `export graph --format html\|json` | `export_graph` | 6 |
| E02 | Relevant original source ZIP, selected original file download and historical evidence versions | `export sources`; `source download` | `export_source_bundle`, `export_original_source` | 6 |
| E03 | Inventory/dictionary/column/impact/code-search/run-comparison CSV/JSON/HTML reports matching available UI formats | `export report --kind ... --format ...` | `export_report` | 6 |
| C01 | Cleanup counts/estimates and all existing workspace-category previews/applies/reset/deletion | Existing `cleanup`/`workspace reset`; add discovery parity | Existing inspect/preview tools; no apply (R) | 7 |
| C02 | Shared parser/Streamlit caches, orphan blobs and full recognized application-data reset | Local UI instructions only (R) | Safe inspect/preview with `requires_local_ui` (R) | 7 |
| C03 | History retention preview, archive eligibility, archive list, local archive and recovery restore | `history preview\|archive\|archives\|restore` | `preview_history_archive`, `list_history_archives`; local mutation guidance (R) | 7 |
| C04 | Stale staging preview, selected cleanup, age24–8760h, recovery list/restore | `staging preview\|clean\|recoveries\|restore` | `preview_staging_cleanup`, `list_staging_recoveries`; local mutation guidance (R) | 7 |
| C05 | Automatic expired staging preference; only app-created files,24h,100 files/25MB per visit | `settings get\|update temporary_cleanup`; explicit local `staging clean --expired` | Preference read/tightening; never automatically clean on tool read (R) | 7 |
| M01 | Database integrity/storage, checkpoint, full-home backup, backup list/download, new-home restore | Existing `maintenance`; add `backups` listing/download | `inspect_database_maintenance`, `list_runtime_backups` metadata only; local action guidance (R) | 7 |
| I01 | Browser ZIP/folder uploads and file inspection | Keep allowed-path ingest; extend inventory/source export where needed | Keep authorized server-path ingest; no reading client paths by magic | 5, 6 |

## 5. Shared implementation map

Reuse these existing modules and tests rather than importing UI into automation:

- `src/dataforge/agent/contracts.py`, `service.py`, `paging.py`, `jobs.py`, `mcp_server.py` and `src/dataforge/cli.py`: authorization, bounded requests, adapters and jobs.
- `configuration.py`, `connections.py`, `llm.py`, `llm_resources.py`: settings/profile contracts, credential scopes, existing `Adapter`, `assist_task`, `merge_claims` and offline `context_chunks`.
- `services.py`, `exports.py`, `graph.py`, `store.py`: existing analysis, `compare_runs`, `column_report`, graph/path data, original bytes and safe exports.
- `cleanup.py`, `maintenance.py`, `temporary_cleanup.py`, `database_maintenance.py`: shared guards, history/staging recovery and full-home backup.
- `logging_config.py` and existing `ui/themes.py`: logging and theme behavior; extract theme logic without changing the presets or unrelated TOML content.
- Presentation adapters: `ui/provider_settings.py`, `assistance.py`, `assistance_result.py`, `unresolved_review.py`, `agent_settings.py`, `data_management.py`, `workspace_history.py`, `temporary_cleanup.py`, `common.py`, `themes.py` and `ui/pages/`.

Create only the following focused modules when their slice needs them:

| New file | Responsibility |
| --- | --- |
| `src/dataforge/agent/capabilities.py` | Explicit capability inventory and adapter/policy metadata; no dynamic arbitrary dispatcher |
| `src/dataforge/settings_service.py` | Typed section reads/atomic updates and non-escalation checks |
| `src/dataforge/provider_service.py` | Profile/routing CRUD, permitted runtime references and adapter discovery/tests |
| `src/dataforge/ai_service.py` | Authorized selected-range requests, offline review/chunks, durable result/activity access and explicit merge |
| `src/dataforge/reporting.py` | Shared inventory/history/dictionary/health/schema/validation report construction |
| `src/dataforge/artifacts.py` | Typed artifact creation/authorization, source versions and bounded binary retrieval |
| `src/dataforge/theme_configuration.py` | Extract existing preset/detection/atomic apply logic without Streamlit imports |
| `src/dataforge/agent/cli_settings.py`, `cli_ai.py`, `cli_reports.py` | New Typer groups only if needed to keep existing `cli.py` manageable |
| `tests/test_parity_*.py` | Focused contracts/settings/providers/AI/reports/artifacts/maintenance/runtime/coverage tests named per slice below |

Keep the existing MCP server factory and shared service dispatch; split new handlers by feature only when module size warrants it. Do not add a second API server or a general plugin framework.

## 6. Ordered vertical slices

Every slice follows this cycle: write the specified failing regression, run it to demonstrate the gap, implement shared behavior plus CLI/MCP/UI adapters, rerun focused tests, exercise the affected UI in an isolated home, update docs/status/coverage and commit a coherent Conventional Commit. Read-only refactors must prove before/after output equivalence. No feature checkbox is complete because only its service function exists.

### Slice 1 — Capability and permission foundation

**Files:** `agent/contracts.py`, new `agent/capabilities.py`, `agent/service.py`, `agent/mcp_server.py`, `cli.py`; `tests/test_parity_contracts.py`, existing agent tests.

**Interfaces:** `capability_catalog(service, workspace_id=None) -> dict`; strict typed settings/operation requests; additive launch policy fields described in section3. All new handlers still pass through shared authorization.

- [x] Add `test_capabilities_cover_inventory`: every section4 ID has CLI/MCP status, effects and restriction metadata; no unknown or duplicate IDs.
- [x] Add tests denying source/network/config writes without their independent permission, scoped global administration and attempts to alter launch policy through request JSON.
- [x] Implement capability discovery, schema versions, stable errors and conflict revisions. Do not change existing default policy semantics or tool outputs.
- [x] Add tests showing both stdio and HTTP enforce the same service checks and MCP64KB admission limit remains effective.
- [x] Run `uv run pytest tests/test_parity_contracts.py tests/test_agent_service.py tests/test_agent_cli.py tests/test_agent_mcp.py`; update guides and commit `feat: add capability and permission discovery`.

### Slice 2 — Settings, workspace details and configuration portability

**Coverage:** S01–S07, S09, W01–W02, V02–V03; temporary preference schema used in slice7.

**Files:** `configuration.py`, new `settings_service.py`, agent adapters, `ui/pages/settings.py`, `ui/agent_settings.py`; `tests/test_parity_settings.py`, existing configuration/settings/resource tests.

**Interfaces:** `read_settings(store, workspace_id, section) -> dict`; `update_settings(store, policy, workspace_id, section, values, expected_revision) -> dict`; reuse `export_workspace_configuration` and `import_workspace_configuration`.

- [x] Pin every UI field/range in section4 in a settings schema test, including defaults and all profile-independent privacy/resource fields. Reject unknown keys, invalid dialects/folder mappings, out-of-range values and mixed invalid/valid patches with no partial write.
- [x] Test stale revision conflicts and UI cache invalidation. Changing parsing settings marks analysis required without deleting old committed facts or triggering analysis.
- [x] Test `enabled=false` cannot be undone by MCP, tightening revokes subsequent requests, widening source/network/audit/budget permissions is refused, and the credential-free polling snapshot stays consistent.
- [x] Implement workspace identity editing and bounded configuration v1/v2 import into a new workspace. Test that profiles/secrets/privacy/agent permissions/history never transfer, including malicious extra fields and oversize files.
- [x] Wire CLI and MCP section schemas and adapters; UI uses the same update validators. Saved settings and per-request overrides remain distinct.
- [x] Run `uv run pytest tests/test_parity_settings.py tests/test_workspace_configuration.py tests/test_agent_settings.py tests/test_llm_resources.py`; verify existing UI save/import flows; commit `feat: expose typed workspace configuration`.

### Slice 3 — Secure profiles, runtime connections and routing

**Coverage:** P01–P05.

**Files:** new `provider_service.py`, `connections.py`, `llm.py`, agent contracts/adapters, `ui/provider_settings.py`; `tests/test_parity_providers.py`, existing LLM/connection tests.

**Interfaces:** `save_profile(store, policy, workspace_id, profile, expected_revision) -> dict`; `provider_operation(store, policy, connections, workspace_id, profile_id, operation) -> dict`, where operation is only `models` or `test`; typed routing with exactly the current five tasks and ordered profile IDs.

- [x] Test all Profile fields and validation rules, secret-bearing URL/userinfo rejection, authorized recipient origins, missing/duplicate profile IDs, routing references, removal of a referenced profile and stable fallback order.
- [x] Test the named-reference allowlist, DATAFORGE_ session names, explicit legacy launch reference, hidden CLI prompt and runtime clear/shutdown. Assert canary secrets absent from database bytes, files, CLI output, MCP envelopes, logs, audits, exceptions and job metadata; assert `os.environ` unchanged.
- [x] Test zero outbound requests for profile/routing reads/updates, offline capability checks and denied operations. Test blocked redirect/origin changes and same-host fallback rules before any credential is forwarded.
- [x] Implement CLI hidden per-operation credentials and MCP reference binding/status/clear with workspace isolation. UI session values cannot be retrieved or implicitly shared through these APIs.
- [x] Reuse existing model discovery/completion adapters. Return sanitized timing/usage and errors; no raw HTTP headers, raw provider body or automatic fallback model substitution.
- [x] Run `uv run pytest tests/test_parity_providers.py tests/test_connections.py tests/test_llm.py`; mock network first, then at most one authorized OmniRoute discovery/test pair; verify UI connect/clear/routing; commit `feat: expose secure provider operations`.

### Slice 4 — AI requests, unresolved review and durable results

**Coverage:** A01–A05.

**Files:** new `ai_service.py`, `llm.py`, `llm_resources.py`, agent service/adapters, all four assistance/review UI modules; `tests/test_parity_ai.py`, existing LLM/resource/advisory tests.

**Interfaces:** `preview_ai_evidence(store, policy, workspace_id, file_id, first, last, task) -> dict`; `request_ai_assistance(store, policy, connections, workspace_id, file_id, first, last, task, expected_hash, cancelled=None) -> dict`; `get_ai_result(store, policy, workspace_id, record_id, options) -> dict`; `merge_ai_result(store, policy, workspace_id, record_id, refresh=True) -> dict`. Use `assist_task`/`merge_claims`, not duplicate grounding logic.

- [x] Test all five tasks, diagnostic selection, adjustable line bounds, chunk selection and exact hash pinning. Preview/chunk/review listing is entirely offline. A later source/job assignment change must produce a bounded conflict/warning, never silently analyze different evidence.
- [x] Test schema and exact-quote rejection, fenced valid JSON, ambiguous symbols, provider failure, redaction, quarantine persistence and source permission revocation. No guessed preprocessing or relaxed evidence checks.
- [x] Expose saved result/activity lists and versioned detail/advisory artifacts with usage, duration, task/provider/requested model, outcome and freshness; respect full-history privacy and retention. Do not reveal source-bearing quotes in summary responses without source permission.
- [x] Implement explicit inferred merge only for validated lineage tasks; repeat merge is safe, advisory/quarantined results cannot merge, and refresh failure reports that merge committed while graph refresh needs retry.
- [x] Keep requests synchronous and bounded initially: no background secret-bearing job queue, no automatic calls for remaining chunks. Enforce existing workspace/process concurrency and provider timeout/retry budgets. Document safe retry after ambiguous disconnect without promising provider exactly-once billing.
- [x] Run `uv run pytest tests/test_parity_ai.py tests/test_llm.py tests/test_llm_resources.py`; exercise UI request/result/review/merge in isolated fixtures; commit `feat: expose grounded AI workflows`.

### Slice 5 — Inventory, history and engineering reports

**Coverage:** W04–W05, R01–R04, R07; source/ingest equivalents for I01.

**Files:** new `reporting.py`, `services.py`, agent adapters, `ui/pages/dashboard.py`, `builder.py`, `columns.py`, `tools.py`; `tests/test_parity_reports.py`.

**Interfaces:** shared `workspace_health`, `data_dictionary`, `asset_schema`, `validate_lineage_evidence`, analysis/import run list/detail and `compare_analysis_runs` report builders, each accepting explicit workspace and bounded options.

- [x] Test inventory encoding/file size/metadata/import diagnostics, completed/failed/pending statuses, stable run pagination, cross-workspace run rejection and before/after comparison semantics using existing `compare_runs`.
- [x] Test dictionary declared SQL/CSV sampled types/provenance, unknown types, missing schemas and disagreement. Declared-schema reports include exact original DDL evidence only with source permission. Do not promote sampled/inferred fields to verified schema.
- [x] Test hotspot ordering, temporary/isolated counts and bounded cycle reporting; omit no freshness/truncation warnings. Reuse NetworkX and current graph filtering semantics.
- [x] Expose the standalone existing evidence validation checks as a read-only operation and distinguish them from reparsing, schema validation and runtime correctness.
- [x] Extend source search additively: default remains metadata-only; `include_matches` requires source permission and returns bounded exact line/snippet matches. Preserve literal matching and clearly document CSV exclusion for the UI-style code-search report.
- [x] Run `uv run pytest tests/test_parity_reports.py tests/test_agent_service.py tests/test_agent_cli.py tests/test_agent_mcp.py`; compare UI/report outputs on both supplied fixtures; commit `feat: expose engineering and history reports`.

### Slice 6 — Graph, paths, source downloads and artifact parity

**Coverage:** V04, R05–R07, E01–E03, I01.

**Files:** new `artifacts.py`, `exports.py`, graph module, agent adapters, `ui/common.py`, explorer/columns/tools pages; `tests/test_parity_artifacts.py`, existing export/agent tests.

**Interfaces:** `create_artifact(store, policy, workspace_id, kind, selection, format, options) -> dict`; `read_artifact(..., artifact_id, offset, length) -> dict`. `kind` is an explicit enum: graph, paths, source-bundle, original-source, inventory, dictionary, columns, impact, code-search, run-comparison, ai-result, backup. Format compatibility is declared, not guessed.

- [x] Test upstream/downstream/combined graph data, filtered nodes/edges and scoped node/edge selection, direct-column filters/grouping, temporary collapse and bounded tree representation with cycle boundaries. Return selection/evidence data rather than browser expansion state.
- [x] Expose dependency path and step-wise reports with exact original evidence, `max_paths`1–500, depth and boundary/completeness flags. Never describe dependency order as runtime execution order.
- [x] Reuse `graph_data`, `graph_html`, `path_rows`, `source_bundle` and existing report exporters. Keep existing ordinary lineage export formats/results compatible; add specialized artifact kinds without repurposing their meaning.
- [x] Publish the format allowlist: graph HTML/JSON; paths CSV/JSON; source bundle ZIP; original source raw bytes; inventory/code search CSV/JSON; dictionary/columns/impact CSV/JSON/HTML; run comparison and advisory AI result JSON. Reject unsupported combinations rather than silently changing formats. Backup ZIP retrieval is local-only.
- [x] Test raw original file byte equality (including BOM/non-UTF8/newlines), original source versions in ZIPs, safe ZIP entry names, missing blobs, HTML escaping and offline graph assets. Source permission must apply even to saved artifacts after revocation.
- [x] Test artifact cross-workspace IDs, traversal/symlinks/redirected paths, new-file-only CLI writes, invalid ranges, max response budgets, base64 chunk reassembly checksum and truncation of bounded reports. No arbitrary artifact file read/write tool.
- [ ] Run `uv run pytest tests/test_parity_artifacts.py tests/test_exports.py tests/test_agent_service.py tests/test_agent_mcp.py`; open exported HTML outside the checkout and verify UI downloads still work; commit `feat: expose graph and source artifacts`. **Partial:** tests, UI downloads and feature commit pass; standalone file-URL browser opening is blocked. See acceptance.

### Slice 7 — Maintenance visibility and permitted local actions

**Coverage:** C01–C05, M01. Do not relax section2 exceptions.

**Files:** existing cleanup/history/staging/database modules and agent adapters, affected maintenance UI modules; `tests/test_parity_maintenance.py`, existing cleanup/maintenance tests.

**Interfaces:** reuse `cleanup_plan`/`apply_cleanup`, `history_plan`/`archive_history`/`list_archives`/`restore_history`, `temporary_plan`/`cleanup_temporary`/`temporary_recoveries`/`restore_temporary`, `inspect_database`/`backup`/`checkpoint`/`restore_backup`. New discovery/preview wrappers are read-only.

- [x] Preserve all existing guarded workspace CLI cleanup operations. Extend capability discovery to every category; safe shared previews expose estimates/notes without offering CLI/MCP apply.
- [x] Add CLI history/staging preview, local archive/clean, list and restore with explicit selection, confirmation and stale-file/revision guards. MCP supports preview/list only, including safe archive/recovery metadata.
- [x] Test that inspecting settings, listing recoveries, invoking MCP tools or constructing a service never triggers automatic staging cleanup. Only the existing opt-in UI event or an explicit local CLI cleanup may do so.
- [x] Add local backup listing/download and safe MCP maintenance metadata. Scope global inspection/backup metadata to unrestricted administrator launches; do not leak full-home paths or other workspaces through a scoped server.
- [x] Exercise stale preview, active LLM/jobs, referenced originals, symlinks, unexpected runtime files, missing/failed backup, interrupted recovery and restore-to-existing-destination refusal. Preserve reset-vs-delete semantics and theme/source-controlled files.
- [x] Run `uv run pytest tests/test_parity_maintenance.py tests/test_cleanup.py tests/test_maintenance.py tests/test_temporary_cleanup.py`; destructive tests only in disposable homes; verify maintenance UI; commit `feat: expose safe maintenance discovery`.

### Slice 8 — Application settings, runtime context and client setup

**Coverage:** S08, S10, W03, V01.

**Files:** new `theme_configuration.py`, `logging_config.py`, launcher/home helpers, agent adapters, `ui/themes.py`, `ui/agent_settings.py`; `tests/test_parity_runtime.py`, existing theme/logging tests.

**Interfaces:** preserve `current_preset`/`apply_preset` semantics in the shared theme module; `runtime_info(policy) -> dict`; `agent_setup(store, policy, workspace_id, client, transport) -> dict`.

- [x] Extract existing fourteen theme presets/detection/atomic TOML updates; no Streamlit import in CLI/MCP service code. Applying requires unrestricted `--allow-application-config` plus write/config permission; MCP may apply only when that authority was explicitly granted at launch, never through workspace write permission alone. Use the startup-selected theme config path, never a request-supplied path.
- [x] Test theme apply preserves unrelated TOML content and reports configured-vs-loaded/reload-required states. A CLI/MCP process cannot inspect another Streamlit process's loaded theme: return loaded state as unavailable and reload required, rather than falsely confirming a live UI update. No browser refresh or server restart is automatic.
- [x] Expose application log level read/update with the same app-wide guards, sanitized outputs and persistence; never return log contents through a configuration tool.
- [x] Expose runtime home/location context and allowed storage options only to appropriately scoped callers; no server home mutation. CLI `--home` remains the switching mechanism.
- [x] Generate credential-free Codex/Claude stdio/HTTP examples with actual authorized workspace/home paths and existing executable selection. Reuse schema generation, never edit client config files automatically.
- [x] Run the actual in-process MCP handler self-test and label it accurately; external connectivity remains a separate client test. Test disabled access, missing token and lock contention without bypasses.
- [x] Run `uv run pytest tests/test_parity_runtime.py tests/test_themes.py tests/test_logging.py tests/test_agent_settings.py`; verify UI themes/settings/setup without changing the user's current theme; commit `feat: expose application and agent setup controls`.

### Slice 9 — Complete parity proof, documentation and release gates

**Files:** `tests/test_parity_coverage.py`, existing CLI/MCP integration tests, `docs/CLI_GUIDE.md`, `docs/MCP_INTEGRATION.md`, `docs/SETUP_AND_DEPLOYMENT.md`, README, AGENTS policy documentation if clarifications are needed, plans/status/acceptance and affected KNOWLEDGE maps.

- [x] Add a checked-in capability fixture keyed by every section4 ID, with implemented command/tool names and restriction reasons. Tests compare it with actual Typer help, MCP tool schemas and service authorization; a prose-only matrix does not pass.
- [x] Test read-only launch denial for every new mutation/network tool, cross-workspace access, unsafe path/HTML inputs, secret canaries, non-escalation, source revocation and every policy-restricted action.
- [x] Run both fixture ZIPs in isolated homes with only the matching extension:85 persistent tables,128 collapsed logical edges, seven layers/all16 sources from `pub.all_kpis`; SAS additionally16 WORK assets/144 physical edges. Verify cache reuse, original evidence and persistence after closing/reopening the owner.
- [x] Test direct service vs CLI vs MCP vs UI outputs for configuration, reports, AI mocked results and artifacts. Confirm each new report declares freshness/completeness and deterministic queries make zero LLM calls.
- [x] Execute real stdio and authenticated streamable-HTTP integration, not just server factory calls; test missing/bad token and correct structured results. Keep one Store owner per home during all comparisons.
- [x] Run `uv run pytest`, `uv run ruff check .`, `git diff --check`, `uv run dataforge --help` and new subgroup help/schema checks. Report skipped gates separately from passing ones.
- [x] Perform one bounded live SQL and one SAS AI request/validate/merge/refresh/reopen check if the named OmniRoute credential and service are available; stop repeated failures, retain sanitized diagnostics and never claim mocked results as live success.
- [x] Run the UI against the completed slices, including profiles/runtime credentials, privacy/settings, builder/review, schema/reports, exports and isolated cleanup/recovery. Confirm no existing functionality regressed.
- [x] Document every new command/tool with examples, flags, scoping, secrets, external effects, versioned schemas, binary artifacts, error/retry behavior, DuckDB ownership and explicit restricted capabilities. Include the original UI-only-to-parity matrix in user documentation.
- [ ] If executable/wheel/Docker artifacts are distributed for these changes, rebuild and smoke-test their new commands/tools outside the checkout; record native/hosted gates that remain unavailable. **Not executed:** no artifacts distributed for parity; rebuild/outside-checkout and target-platform acceptance remain release gates.
- [x] Update `IMPLEMENTATION_STATUS.md` for each completed slice, acceptance evidence and remaining restricted/unverified items; update affected KNOWLEDGE files. Commit `docs: document CLI and MCP feature parity` after passing the recorded checks.

## 7. Review focus and explicit acceptance tests

| Likely failure | Required proof and owner |
| --- | --- |
| An assistant configures a profile using a powerful unrelated environment secret or sends a key to another host | Slice3 tests reference allowlists, origin/redirect checks, runtime isolation and persistent canary absence |
| An agent enables its own source/external-AI access or widens its launch policy | Slice1/2 tests deny escalation through settings, portability and all MCP tools, including previously disabled access |
| A UI edit/source replacement occurs between preview, external completion and merge | Slice2/4 conflict/hash tests retain committed facts and refuse stale actions with precise status |
| A read-only MCP request archives/deletes data, triggers automatic cleanup or exposes another workspace's backup | Slice7 read-side-effect, active-job, global-scope and artifact-authorization tests |
| A nominally successful graph/source export is incomplete, wrong-version, corrupt or exceeds tool response limits | Slice6 exact-byte/hash, path/cycle boundary, escaping and chunk-budget tests |

## 8. Remaining work ledger and stop condition

- [x] Slices1–9 implemented and tested in order; capability matrix IDs all accounted for.
- [x] Current policy exceptions remain explicit in discovery, command help, MCP schemas and docs.
- [x] No raw secret transport/persistence, self-escalation, second DuckDB owner or source execution introduced.
- [x] Existing user data, settings, source versions and deterministic fixture results preserved.
- [x] Full test/UI/CLI/MCP/artifact evidence recorded; external/platform limits named honestly.

Stop after this scope is verified. OAuth/multi-user authentication, a remote control plane for a running UI, arbitrary environment/filesystem access, MCP destructive cleanup and unrelated new app features are outside this plan. Do not describe a policy-restricted capability as fully implemented headless parity.


## 9. Execution record — 2026-10-17

Actual implementation/verification is documented in [PARITY_ACCEPTANCE.md](PARITY_ACCEPTANCE.md)
and sanitized [PARITY_ACCEPTANCE.json](PARITY_ACCEPTANCE.json). Commits follow the dependency
order:409e4de,a0c48f6,9956546,21ebcc9,ce3297d,ec5752f,12b010f,0569f2f;
review fixes cea21cb; slice9 coverage/docs follow. No pending catalog capabilities remain.
Checked implementation items do not close the two unexecuted acceptance actions above.
P02,S07,S09,W03,C01,C02,C03,C04,C05,M01 are restricted, not full operational parity.
Source evidence, master prompt, source ZIPs and primary user data/settings are preserved.
