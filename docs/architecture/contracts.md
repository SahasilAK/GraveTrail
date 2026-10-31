# Engineering boundary contracts

This page states what each layer may accept, what it must return and what callers must not
assume. Interfaces are internal to the pinned [source baseline](../development/index.md).
Use the [code map](../development/code-map.md) to find files and adjacent tests.

## Input admission

`Importer` accepts ZIP bytes, an allowed local directory or relative path/byte pairs. It
validates paths, extensions, file/total/archive/compression bounds, decoding and directory
containment before retaining inventory. Directory allowlists are startup grants; a browser
upload's relative path cannot grant arbitrary filesystem access. dbt admission additionally
handles configured project paths, excluded secrets/profiles and bounded YAML/artifacts.

**Input:** `('jobs/a.sql', b'CREATE TABLE mart.a AS SELECT id FROM raw.a;')` with `.sql` selected.
**Output:** an import report and workspace inventory containing immutable source identity/hash.
**Failure:** traversal such as `../a.sql`, binary data, symlinks/outside roots or resource excess
must be rejected or reported as skipped/diagnostic according to the import path. An import
failure must not fall back to executing source or expanding filesystem authority.

Sources: [ingestion](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/ingestion.py), [dbt imports](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/dbt/imports.py).
Proof: [ingestion](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_ingestion.py), [hardening](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_hardening.py),
[inventory controls](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_inventory_controls.py), [dbt imports](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_dbt_imports.py).

## Parser facts and evidence

A parser receives text and explicit configuration, returns `ParseResult`, and has no
persistence/presentation authority. Each `Operation` carries source/target references,
original code and one-based inclusive source lines. `Usage` records direct references;
derivations preserve output/value/role information separately. Diagnostics carry uncertainty.
Source splitting and SAS inline-data handling must preserve original coordinates.

**Input:** literal `CREATE TABLE mart.a AS SELECT id FROM raw.a;`.
**Output:** read raw.a/write mart.a with exact original statement evidence.
**Failure:** runtime-generated/ambiguous references stay unsupported, candidate or unresolved;
a matching catalog name does not make them verified. Serialization must round-trip cacheable
facts. Semantic changes require a `PARSER_VERSION` bump; baseline version is `15`.

Sources: [models](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/models.py), [services](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/services.py),
[SQL parser](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/parsers/sql.py), [SAS parser](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/parsers/sas.py).
Proof: [wrappers](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_parser_static_wrappers.py), [SAS project](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_sas_project.py),
[SQL transformations](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_sql_transformations.py).

## Identity, schemas and publication

The resolver owns workspace/job/session/lifetime identity. Stable IDs and logical dbt
identities must survive display labels. Quoted identifier boundaries matter. A temporary WORK
asset in one job must not merge with another job's WORK asset; a persistent output may be
shared when the identity rules establish it. Wildcards expand only from compatible trustworthy
schema evidence. Conflicting declarations disable certainty instead of guessing runtime order.

Prepared parser/validated AI results become current facts in a shared atomic transaction.
Inventory/settings/profile/protocol/publication revisions are checked at the responsible
coordinator. A successful parse, request or checkpoint is not a published workspace revision.
Failure or cancellation retains the preceding publication. A deliberate partial publication
has explicit coverage and unresolved work; it must not claim complete analysis.

Sources: [identity](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/asset_identity.py), [schemas](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/schemas.py),
[services](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/services.py), [AI coordinator](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/analysis_service.py).
Proof: [job identity](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_job_identity.py), [schemas](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_schemas.py),
[version publication](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_ai_version_publication.py), [saved publication](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_ai_saved_publication.py).

## Storage and lifecycle

`Store` owns the local DuckDB connection, locks, transactions, migrations and retained blobs.
One process owns a home; threads share its locked Store. SQL values use parameters. Baseline
migrations run through version 10, including dbt, AI checkpoints and inspection artifacts.
Schema changes must remain compatible with integrity, full-home backup/restore and cleanup.
A data home is not disposable merely because it contains derived tables: retained originals,
settings, history and recovery journals are user data.

Version-pinned evidence uses `file_id` plus content/source hash. Calling current-file readers
without a version after re-import can show a different original. Cleanup requires a current
preview, scope/confirmation, active-job protection and mandatory backup where required.
General cleanup and specialized history/staging recovery are different operations; do not
promise a universal undo. Whole-home restore targets a new directory.

Sources: [Store](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/store.py), [cleanup](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/cleanup.py),
[database maintenance](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/database_maintenance.py), [history](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/maintenance.py),
[staging recovery](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/temporary_cleanup.py).
Proof: [Store](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_store.py), [cleanup](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_cleanup.py),
[maintenance](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_maintenance.py), [staging](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_temporary_cleanup.py).

## AI requests, credentials and grounding

External source disclosure is opt-in and must satisfy workspace privacy plus exact launch
provider-origin/credential-reference grants. Profiles store reference names rather than secret
values. Session/request `RuntimeConnections` owns ephemeral values and redaction; job journals,
portable preferences and global caches must not retain those values. Configured local-loopback
HTTP and remote HTTPS have different transport rules.

Project extraction sends exact source parts; it does not redact likely secrets from
those parts. Review source disclosure before authorizing it. Focused assistance uses
its separate request redaction, and retained interaction bodies redact only the saved
copy. Preview and dispatch count the same actual complete provider envelope with bound model
capacity and pinned allocation. Host-owned source parts and references pin original file/hash and permitted offset ranges,
with source scope and run protocol. Current independent project extraction uses
`validate_extraction` for strict shape, source-reference bounds/hash, own-source operation
evidence, stable identity and conflict consistency. It does not invoke static semantic approval
or prove that an inferred relationship is semantically correct. AI publication remains inferred;
its report retains `complete=False` with `semantic_coverage_not_proven`.

Legacy `validate_project_response`/`ai_semantic` paths and manual focused grounding perform
different checks; their parser/lexical guards must not be described as the acceptance gate
for current independent extraction. Model output and imported prompt-like text cannot grant
authority or change instructions.

Unknown transport outcome is not equivalent to a request that never reached its provider.
Preserve attempt accounting, safe recovery reasons and explicit retry decisions. Resume
reuses compatible successes, not stale source or incompatible protocol state. Do not hold
a Store transaction across network waits. Transient reasoning display and durable retained
inspection have distinct lifetimes and disclosure controls.

Sources: [connections](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/connections.py), [provider policy](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/provider_service.py),
[LLM adapter](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/llm.py), [budget](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/ai_budget.py),
[validation](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/ai_validation.py), [pipeline store](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/ai_pipeline_store.py).
Proof: [connections](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_connections.py), [allocation](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_ai_budget_allocation.py),
[citations](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_ai_citations.py), [replay](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_ai_response_replay.py),
[partial recovery](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_ai_partial_recovery.py),
[independent extraction](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_ai_independent_extraction.py).

## Automation and source disclosure

CLI and MCP call `AgentService`; launch policy and persisted workspace policy both apply.
Reads, writes, source, configuration, provider network, application configuration and local
administration are distinct permissions. Read-only is the launch default. A scoped workspace
policy cannot create unrestricted whole-home backups. MCP exposes safe inspection/preview
rather than local-admin destructive maintenance mutations.

`QueryOptions` validates detail, items, depth and serialized-character bounds. Cursors bind
query/revision; returned JSON contains whole records. Source text needs explicit evidence or
detailed/source-authorized retrieval. Credentials and raw provider/source payloads stay out
of status/audit journals. Detached status polling must remain possible without opening the
DuckDB home owned by a running worker. HTTP MCP additionally requires bearer and host/origin
protection; stdio does not make application authorization optional.

Sources: [agent contracts](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/agent/contracts.py), [service](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/agent/service.py),
[paging](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/agent/paging.py), [MCP server](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/agent/mcp_server.py),
[jobs](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/agent/jobs.py).
Proof: [agent service](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_agent_service.py), [MCP](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_agent_mcp.py),
[gateway sockets](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_gateway_sockets.py), [parity contracts](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_parity_contracts.py).

## Investigation and artifact output

Graph traversal uses exact asset IDs and retains multiple evidence rows per relationship.
Temporary contraction preserves underlying steps. Missing endpoints, unresolved references,
cycles and path/depth/item/evidence limits remain visible. `complete` and `truncated` carry
meaning; an empty result is not a general proof of absence. Direct column usage and
transformation lineage remain separate query contracts.

Exports snapshot committed revision/settings/facts. They do not implicitly analyze new
imports or call AI. Source text is opt-in, version-pinned and subject to retrieval policy.
HTML/JavaScript/SVG encode imported labels as inert data. XLSX uses literal cells, bounded
text/memory/time and metadata for scope/coverage. Failed artifact generation cleans owned
partials; PNG workers have bounded admission/timeouts and SVG remains available when the
renderer is unavailable.

Sources: [graph](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/graph.py), [transformations](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/transformations.py),
[exports](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/exports.py), [Excel](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/excel_exports.py),
[image service](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/graph_image_service.py), [artifacts](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/artifacts.py).
Proof: [graph](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_graph.py), [Excel](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_excel_exports.py),
[image artifacts](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_image_artifacts.py), [transformation access](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_transformation_access.py).

## Evidence for claims

A mocked provider regression proves request/response behavior under that fixture. A parser
fixture proves a supported static case. AppTest proves Python-side UI interactions; it does
not execute custom browser JavaScript. A wheel or native build proves construction, while
installed smoke tests prove behavior on the tested platform. A synthetic benchmark must
retain its workload and correctness oracle. Hosted publication needs inspection of the
artifact/deployment. Keep those claim boundaries explicit in reviews and documentation.
