# CLI and MCP capability coverage

Verified source implementation: 2026-10-17. All 46 UI coverage IDs are accounted for:
36 implemented equivalents and 10 explicitly policy-restricted capabilities. Restricted
rows have working permitted reads/local routes; they do **not** claim full MCP parity.
`gravetrail capabilities` and MCP `get_capabilities` return this versioned inventory,
including scope, aggregate effects, required grants and current launch authorization.
Follow `next_cursor`; availability does not mean the current caller has permission.

Use [CLI guide](CLI_GUIDE.md) for command options/examples and [MCP integration](MCP_INTEGRATION.md)
for typed schemas and transport setup. Every workspace operation selects an explicit ID.
Use `--home` at launch and keep one DuckDB owning process per home. Stop that owner before
opening the same home with another process; separate test homes may run concurrently.

Read-only is the default. Write, configuration, outbound AI and application authority are
independent startup grants. `--allow-admin` is local CLI only, requires unrestricted scope
and cannot be accepted by MCP. Workspace settings can revoke access immediately. MCP may
tighten privacy/access settings; it cannot expand its own policy. Application writes need
unrestricted `--allow-write --allow-config-write --allow-application-config`.

Profile/routing reads and saves, chunk/review previews, reports and deterministic graph
queries make zero provider calls. Discovery, connection tests and explicit AI requests need
`--allow-llm`, exact `--allowed-llm-origin` and approved `--allowed-credential-ref` names,
in addition to write/source/privacy gates where applicable. The catalog aggregates effects
for each capability; an ordinary read within a mixed capability does not require its write grant.
Never put a credential value in arguments, patches, profiles or MCP payloads. Use a read-only
named launch variable, hidden per-invocation CLI input, or UI session input. Runtime bindings
are scoped to workspace/profile, expire on profile changes and clear on close; UI credentials
are separate. Fallback profiles resolve their own approved references. No environment mutation
is used for session credentials. Redirects are refused.

| ID | UI capability | CLI routes | MCP tools | State / restriction |
| --- | --- | --- | --- | --- |
| P01 | List/get/create/edit/remove provider profiles; name/provider/URL/model/reference/auth/timeout/retries/max_tokens/context_chars/temperature/structured/Azure API version | `providers list`<br>`providers get`<br>`providers save`<br>`providers remove` | `list_provider_profiles`<br>`get_provider_profile`<br>`save_provider_profile`<br>`remove_provider_profile` | Implemented |
| P02 | Session connect/status/clear; reference compatibility and restart behavior | `providers credentials status`<br>`providers test`<br>`ai request` | `connect_runtime_reference`<br>`get_runtime_connection_status`<br>`clear_runtime_connection` | **Restricted:** MCP binds only an approved named launch reference. Raw credentials use hidden per-invocation CLI input or a UI session; never tool arguments. |
| P03 | Model discovery with sanitized results | `providers models` | `discover_provider_models` | Implemented |
| P04 | Actual model connection test and sanitized usage/failure | `providers test` | `test_provider_connection` | Implemented |
| P05 | Default profile, each of five task routes and ordered fallback profiles | `providers routing get`<br>`providers routing update` | `get_model_routing`<br>`update_model_routing` | Implemented |
| A01 | Selected evidence analysis: SQL lineage, SAS lineage, lineage validation, column usage, code explanation | `ai request` | `request_ai_assistance` | Implemented |
| A02 | Offline statement chunk preview, selected chunk/range and budget information | `ai chunks` | `preview_ai_chunks` | Implemented |
| A03 | Unresolved warning/error review queue, recommended source context, custom bounds and explicit AI review | `ai review list`<br>`ai review preview`<br>`ai review request` | `list_review_candidates`<br>`preview_diagnostic_review`<br>`request_diagnostic_review` | Implemented |
| A04 | Saved AI result list/get, outcomes/quarantine, source-job/hash warnings, advisory download and AI activity/usage/duration | `ai results list`<br>`ai results get`<br>`ai results export`<br>`ai activity` | `list_ai_results`<br>`get_ai_result`<br>`export_ai_result`<br>`get_ai_activity` | Implemented |
| A05 | Explicit validated lineage merge as inferred and graph refresh; no advisory merge | `ai merge` | `merge_ai_claims` | Implemented |
| S01 | Default SQL dialect, per-folder/per-extension overrides | `settings schema`<br>`settings get`<br>`settings update` | `get_settings_schema`<br>`get_workspace_settings`<br>`update_workspace_settings` | Implemented |
| S02 | Case-sensitive identities, wildcard expansion, CSV sample rows | `settings schema`<br>`settings get`<br>`settings update` | `get_settings_schema`<br>`get_workspace_settings`<br>`update_workspace_settings` | Implemented |
| S03 | SAS library mappings, static macros, default job/session and folder job assignments | `settings schema`<br>`settings get`<br>`settings update` | `get_settings_schema`<br>`get_workspace_settings`<br>`update_workspace_settings` | Implemented |
| S04 | Saved minimum confidence, include_inferred, diagnostic visibility, reanalysis mode | `settings schema`<br>`settings get`<br>`settings update` | `get_settings_schema`<br>`get_workspace_settings`<br>`update_workspace_settings` | Implemented |
| S05 | max_file_mb1–100, max_files1–100000, parse_workers1–8 | `settings schema`<br>`settings get`<br>`settings update` | `get_settings_schema`<br>`get_workspace_settings`<br>`update_workspace_settings` | Implemented |
| S06 | AI workspace concurrency1–4, process cap8, chunk_chars500–100000 | `settings schema`<br>`settings get`<br>`settings update` | `get_settings_schema`<br>`get_workspace_settings`<br>`update_workspace_settings` | Implemented |
| S07 | external_llm, allow_full_source, max_context_chars500–100000, redact_secrets, llm_history, retention_days1–3650 | `settings schema`<br>`settings get`<br>`settings update` | `get_settings_schema`<br>`get_workspace_settings`<br>`update_workspace_settings` | **Restricted:** MCP may tighten privacy. Enabling transmission/full source/history, increasing disclosure/retention budgets or disabling redaction requires local CLI --allow-admin or UI. |
| S08 | Application logging DEBUG/INFO/WARNING/ERROR, persisted per home | `application logging get`<br>`application logging update` | `get_application_logging`<br>`update_application_logging` | Implemented |
| S09 | Agent enabled/write/source permissions, default detail, max_chars512–100000, audit_reads | `settings schema`<br>`settings get`<br>`settings update` | `get_settings_schema`<br>`get_workspace_settings`<br>`update_workspace_settings` | **Restricted:** MCP cannot enable disabled access/source/write, increase detail/response budgets or disable read auditing. Use local administrator CLI/UI. |
| S10 | Actual local MCP-handler check, available schemas and generated Codex/Claude stdio/HTTP examples | `agent inspect`<br>`agent self-test`<br>`agent client-config` | `get_agent_setup`<br>`test_local_agent_access` | Implemented |
| W01 | Rename existing workspace and edit description | `workspace update` | `update_workspace` | Implemented |
| W02 | Export allowed configuration and create new workspace from v1/v2 configuration; exclude profiles/secrets/privacy/source/history | `workspace config export`<br>`workspace config import` | `export_workspace_configuration`<br>`import_workspace_configuration` | Implemented |
| W03 | Storage locations/home status and current browser home selection equivalent | `runtime info` | `get_runtime_info` | **Restricted:** No live server home switch. Relaunch CLI/MCP with an authorized --home; UI changes its current browser session only. |
| W04 | Analysis and ingestion run lists/details, inventory file_size/encoding/metadata and import diagnostics | `runs list`<br>`runs get`<br>`ingestions list`<br>`ingestions get`<br>`source list`<br>`source metadata` | `list_analysis_runs`<br>`get_analysis_run`<br>`list_ingestion_runs`<br>`get_ingestion_run`<br>`search_source_code`<br>`get_source_metadata` | Implemented |
| W05 | Baseline/comparison run diff and JSON download | `runs compare`<br>`export report` | `compare_analysis_runs`<br>`export_report` | Implemented |
| V01 | Fourteen theme presets, detected/configured/loaded theme and explicit apply | `application theme list`<br>`application theme get`<br>`application theme apply` | `list_theme_presets`<br>`get_application_theme`<br>`apply_application_theme` | Implemented |
| V02 | Saved graph node limit10–1000, traversal depth1–30, tree expansion0–30, upstream/downstream/combined, collapse temporary | `settings schema`<br>`settings get`<br>`settings update` | `get_settings_schema`<br>`get_workspace_settings`<br>`update_workspace_settings` | Implemented |
| V03 | Graph labels compact/full/hidden, semantic/neutral palette, width1–5, source complete/relevant and line numbers | `settings schema`<br>`settings get`<br>`settings update` | `get_settings_schema`<br>`get_workspace_settings`<br>`update_workspace_settings` | Implemented |
| V04 | Interactive graph/tree/edge/node focus, expand/collapse and column grouping/filter equivalents | `lineage graph`<br>`columns usage` | `get_graph_data`<br>`get_column_usage` | Implemented |
| R01 | Data dictionary: declared SQL types, sampled CSV types, fallback direct references, provenance and unknowns | `dictionary list` | `get_data_dictionary` | Implemented |
| R02 | Declared schema columns plus original DDL evidence | `assets schema` | `get_asset_schema` | Implemented |
| R03 | Dashboard hotspots, isolated/temporary assets, cyclic groups and parsing-status counts | `workspace health` | `get_workspace_health` | Implemented |
| R04 | Standalone stored-lineage evidence check (does not analyze or repair) | `lineage validate` | `validate_stored_lineage` | Implemented |
| R05 | Dependency paths in both directions, max_paths1–500, depth, temporary view, boundaries and exports | `lineage paths`<br>`export paths` | `get_dependency_paths`<br>`export_dependency_paths` | Implemented |
| R06 | Step-wise lineage rows/logical dependency order with evidence; no inferred runtime order | `lineage steps` | `get_lineage_steps` | Implemented |
| R07 | Code search matching line numbers/snippets and report export, beyond current metadata-only file search | `source search`<br>`export report` | `search_source_code`<br>`export_report` | Implemented |
| E01 | Interactive offline graph HTML and graph visualization JSON with appearance | `export graph` | `export_graph` | Implemented |
| E02 | Relevant original source ZIP, selected original file download and historical evidence versions | `export sources`<br>`source download` | `export_source_bundle`<br>`export_original_source` | Implemented |
| E03 | Inventory/dictionary/column/impact/code-search/run-comparison CSV/JSON/HTML reports matching available UI formats | `export report` | `export_report` | Implemented |
| C01 | Cleanup counts/estimates and all existing workspace-category previews/applies/reset/deletion | `cleanup inspect`<br>`cleanup sources`<br>`cleanup lineage`<br>`cleanup columns`<br>`cleanup ai`<br>`cleanup history`<br>`cleanup jobs`<br>`cleanup reset`<br>`cleanup workspace`<br>`workspace reset` | `inspect_cleanup`<br>`preview_cleanup` | **Restricted:** MCP cleanup is read-only. Guarded local CLI apply needs a fresh preview, typed name and full-home backup. |
| C02 | Shared parser/Streamlit caches, orphan blobs and full recognized application-data reset | `cleanup inspect`<br>`capabilities` | `inspect_cleanup`<br>`preview_cleanup` | **Restricted:** Shared cache/orphan/application apply is UI-only. Authorized unrestricted previews expose estimates, never apply tokens or paths. |
| C03 | History retention preview, archive eligibility, archive list, local archive and recovery restore | `history preview`<br>`history archive`<br>`history archives`<br>`history restore` | `preview_history_archive`<br>`list_history_archives` | **Restricted:** MCP may preview/list history archives only. Archive/restore is an explicit guarded local CLI/UI action. |
| C04 | Stale staging preview, selected cleanup, age24–8760h, recovery list/restore | `staging preview`<br>`staging clean`<br>`staging recoveries`<br>`staging restore` | `preview_staging_cleanup`<br>`list_staging_recoveries` | **Restricted:** MCP may preview/list staging recoveries only. Clean/restore is an explicit guarded local CLI/UI action. |
| C05 | Automatic expired staging preference; only app-created files,24h,100 files/25MB per visit | `settings get`<br>`settings update`<br>`staging clean` | `get_workspace_settings`<br>`update_workspace_settings`<br>`preview_staging_cleanup` | **Restricted:** MCP may read/disable the automatic preference, never enable or execute it. Automatic cleanup runs only on the existing opt-in UI event. |
| M01 | Database integrity/storage, checkpoint, full-home backup, backup list/download, new-home restore | `maintenance inspect`<br>`maintenance backup`<br>`maintenance checkpoint`<br>`maintenance restore`<br>`maintenance backups`<br>`maintenance download` | `inspect_database_maintenance`<br>`list_runtime_backups` | **Restricted:** MCP exposes authorized unrestricted metadata only. Checkpoint/backup/restore and backup download are local CLI/UI; restore requires a new home. |
| I01 | Browser ZIP/folder uploads and file inspection | `ingest`<br>`source list`<br>`source metadata`<br>`source download` | `ingest_sources`<br>`search_source_code`<br>`get_source_metadata`<br>`export_original_source` | Implemented |

Artifacts use managed IDs, home/workspace binding, exact source versions, SHA-256 and
bounded base64 reads (at most 16 KiB before encoding and the response budget). Files cap at
64 MiB. Source authorization is checked again on retrieval, including saved exports after
revocation. CLI downloads create a new destination exclusively and verify the assembled hash.
Unsupported kind/format pairs fail; no arbitrary file read/write or backup retrieval MCP tool exists.

Settings/profile patches require `expected_revision`; refresh stale state before retrying.
AI requests pin original hash/job and explicit line bounds. Schema/quote failures stay
quarantined. Only validated lineage tasks may merge, always as inferred relationships;
repeat merge is idempotent. A committed merge with failed graph refresh reports retry required.
Synchronous requests have bounded concurrency/timeouts; busy requests refuse without queuing.
After an ambiguous disconnect, inspect saved activity before retrying: provider billing is
not exactly once. Summary pages omit source-bearing details; exact evidence is an explicit,
separately authorized request. Respect `analysis_current`, `complete`, boundaries and cursors.

General cleanup requires a fresh preview, explicit local confirmation and successful full-home
backup. History/staging journals are specialized recovery, not general undo. Restore full-home
archives only into a new destination. Shared cache/orphan/application removal stays UI-only;
MCP maintenance stays read-only. Reading settings/recoveries never triggers automatic cleanup.
Runtime reset and schema removal remain separate operations.

The checked-in [capability fixture](https://github.com/SahasilAK/dataforge-engineering-hub/blob/main/tests/fixtures/parity_capabilities.json) is tested against
actual Typer routes/help, MCP schemas and authorization. The [testing guide](TESTING.md)
describes parity checks for transports, the running UI, both real ZIPs and live providers.
