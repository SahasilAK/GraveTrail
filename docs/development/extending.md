# Extend an existing boundary

Choose the owning subsystem in the [code map](code-map.md), read its tests, then change the
smallest shared layer that gives UI, CLI and MCP the same result. The Python interfaces here
are [internal](internal-api.md); check the baseline source when changing signatures.

## Extend a parser

The existing signatures are:

```python
parse_sql(content: str, dialect: str | sqlglot.Dialect = '') -> ParseResult
parse_sas(content: str, library_mappings: dict[str, str] | None = None,
          macros: dict[str, str] | None = None, sql_dialect: str = '') -> ParseResult
parse_csv(content: str, path: str, sample_size: int = 25) -> ParseResult
```

1. Add the smallest positive source fixture and an ambiguous/unsupported negative case in the
   appropriate [SQL](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_sql.py), [SAS](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_sas.py) or
   [transformation](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_sql_transformations.py) test module.
2. Return `Operation`/`AssetRef` facts with exact original code and inclusive line coordinates.
   Put direct references in `Usage`; put value/role derivations in the established derivation
   shape. Use `Diagnostic` for uncertainty instead of inventing a dependency.
3. Keep catalog/job/cross-file resolution in [asset_identity.py](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/asset_identity.py)
   and [services.py](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/services.py). A parser must not open a Store, contact a
   provider or execute imported text.
4. If a new format is necessary, extend admission/extension choices in
   [ingestion.py](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/ingestion.py), `_parse_inventory` in services, source-selection
   UI and CLI options. A new parser file alone does not make the format reachable.
5. Bump `PARSER_VERSION` in services when extraction semantics or cached result shape changes.
   Verify `ParseResult.to_dict/from_dict`, warm-cache behavior, source-version evidence and
   persisted publication, not only the parser's return value.

For `CREATE TABLE mart.x AS SELECT id FROM raw.y;`, the expected relationship is raw.y → mart.x
with the exact statement as evidence. If the table name comes from an unknown runtime
expression, the expected output is an explicit gap/diagnostic, not a guessed table. See
[static-wrapper regressions](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_parser_static_wrappers.py) and
[schema regressions](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_schemas.py) for literal versus dynamic boundaries.

## Extend dbt support

Treat a dbt input as a project with resource identities, packages, versions and source origins,
not just SQL files. Add fixture cases before extending supported artifact versions.

| Change | Owning modules | Required counterexample |
| --- | --- | --- |
| Import a new resource location | `dbt/imports.py`, `yaml.py`, `discovery.py` | outside-root, symlink, excluded profile/secret and bounded-input cases |
| Recognize a resource/ref/config | `resources.py`, `templates.py`, `resolution.py` | conditional/dynamic/package/version ambiguity remains candidate or unresolved |
| Accept artifact structure | `artifacts.py`, `evidence.py`, `models.py` | unsupported schema version and mismatched original/generated evidence |
| Publish or report new facts | `analysis.py`, `persistence.py`, `service.py`, shared services | atomic publication, unchanged source hash, cross-interface access |
| Supply AI context | `ai_context.py`, shared AI planner | context-only evidence cannot masquerade as authoritative execution or parser answers |

Static `ref`/`source` evidence and generated SQL evidence retain different origins. Never run
dbt, import resource Python, render imported Jinja or open `profiles.yml` to resolve a gap.
Read [dbt support](../DBT_SUPPORT.md), [resource tests](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_dbt_resources.py),
[artifact tests](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_dbt_artifacts.py), [store tests](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_dbt_store.py) and
[AI context tests](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_dbt_ai_context.py).

## Extend a provider protocol

[llm.py](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/llm.py) owns `PROVIDERS`, validated `Profile`, `Adapter` request/response
branches and model discovery. Existing completion interfaces include:

```python
Adapter.completion_request(p, system, user, *, stream_analysis=False)
Adapter.complete(self, system: str, user: str, *, prepared_request=None) -> tuple[str, dict]
Adapter.models(self) -> list[str]
Adapter.model_catalog(self) -> list[ModelDescriptor]
Adapter.model_details(self, model: str) -> ModelDescriptor
```

Add a protocol identity/default endpoint only when an existing compatible protocol cannot
express it. Cover endpoint URL, request body, authentication headers, discovery, normal/error/
stream responses, timeout/cancellation and redaction with HTTPX `MockTransport`. Return the
same content/usage contract and sanitized `ProviderError` behavior. Remote HTTP, embedded URL
credentials and query/fragment parameters are rejected by `Profile`; local HTTP is allowed
only for loopback. A key field is a reference name, never a persisted secret value.

Update [model_capabilities.py](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/model_capabilities.py) for capacity provenance,
[provider_service.py](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/provider_service.py) for validated routing/policy and
[connections.py](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/connections.py) only if the new protocol genuinely needs a
new credential binding. Complete request-envelope counting must still agree between preview,
dispatch and resume. Keep offline protocol tests distinct from live-provider qualification.
Read [LLM tests](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_llm.py), [transport tests](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_ai_analysis_transport.py),
[provider parity](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_parity_providers.py) and [capacity tests](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_model_capabilities.py).

## Change AI extraction or recovery

Read the [current protocol flow](../architecture/ai-analysis-pipeline.md) before editing the
coordinator. Add a saved-run/resume regression when changing source units, prompts, schemas,
model allocation, context restoration, request attempts, consolidation membership or linking.
The [analysis coordinator](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/analysis_service.py) pins these contracts; a model
schema field alone does not make a legacy option supported.

Current `validate_extraction` checks source-reference identity/hash/bounds, own-source
operation evidence, schema and internal consistency before results can be composed. It does
not use the static parser to approve the model's meaning; AI semantics remain inferred.
Preserve `semantic_coverage_not_proven` and `complete=False` in AI reports. Keep legacy
`ai_semantic`/`validate_project_response` and focused-assistance guards distinct from this path.
Durable request attempts and checked file results are reusable
checkpoints; they are not the published workspace graph. A failed/cancelled network attempt
must not publish partial unvalidated facts. Preserve explicit coverage for unresolved work
when a valid partial graph is committed. Retrying unresolved work should reuse successful
checkpoints and cumulative spending while enforcing freshness and current authorization.

Useful tests: [independent extraction](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_ai_independent_extraction.py), [resumable files](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_ai_resumable_files.py),
[replay](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_ai_response_replay.py), [consolidation](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_ai_file_consolidation.py),
[partial recovery](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_ai_partial_recovery.py), [saved publication](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_ai_saved_publication.py).

## Add a service operation and transport

`AgentService.call(action, workspace_id='', options=None, **arguments)` is the shared action
boundary. Add the handler to its existing subsystem mixin when appropriate rather than
putting a second implementation in each transport.

1. Define input validation and result shape, then register its read/write classification.
2. Apply workspace scope and access revocation. Source-bearing output needs source permission;
   mutation needs both launch and workspace write grants. Configuration/network/application/
   admin effects have additional independent grants.
3. Bound serialized output and pagination. Reuse `QueryOptions` and revision/query-bound cursors.
   Reject invalid/oversized input with stable `AgentError` codes; never return broken JSON fragments.
4. Wire the Typer adapter in `cli.py` or `agent/cli_*.py` and typed tool in `agent/mcp_server.py`.
   Keep local-admin destructive maintenance out of MCP.
5. Update capability/parity inventories and the command/tool reference tables. Verify service,
   CLI and MCP all give the same facts with both allowed and denied policies.

For a read that returns source excerpts, a denied source policy should fail before content
is loaded or serialized. For a report without source, summary output should remain bounded
and should not acquire source text merely because a neighboring service can access it.
See [access tests](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_agent_service.py), [MCP tests](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_agent_mcp.py),
[parity contracts](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_parity_contracts.py), [documentation tests](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_documentation.py).

## Add an exporter or report

Use committed facts and retained source versions. [exports.py](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/exports.py)
serializes graphs/reports/source bundles; [excel_exports.py](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/excel_exports.py)
formats path reports; [graph_image_service.py](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/graph_image_service.py) snapshots
image inputs; [artifacts.py](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/artifacts.py) owns managed artifacts.

Define the input report, returned bytes/text plus metadata, traversal/input/output/time bounds,
source-disclosure choice and failure cleanup before adding a format. Preserve all evidence
for collapsed temporary paths and surface incomplete coverage. HTML/SVG/JS must escape or
safely serialize imported values; XLSX must write literal text rather than inferred formulas.
A formatter must never trigger analysis or network calls. Test hostile labels, missing nodes,
parallel evidence, cycles/limits, stale analysis and interruption cleanup. Use
[export tests](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_exports.py), [Excel tests](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_excel_exports.py),
[image tests](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_graph_images.py) and [artifact tests](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_image_artifacts.py).

## Add a setting, migration or UI page

Settings belong in the existing validated section model and revision-checked service;
portable workspace preferences, runtime secrets, launch grants and app-wide configuration
are different scopes. Update transfer/schema/permission tests with the form or CLI adapter.
For schema changes add a numbered transactional migration in `Store` and synchronize table
ownership with backup/restore, cleanup, integrity and history protections. Test upgrade from
an older home plus backup/restore; never reset an existing user database as a migration.

For a page, register `st.Page` in `app.py`, reuse `ui.common` selectors/source views and keep
service calls independent of Streamlit. Verify AppTest and browser JS separately. In session
state retain controls and durable IDs rather than copied raw source or provider responses.
Relevant suites: [workspace settings](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_workspace_configuration.py),
[Store](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_store.py), [maintenance](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_maintenance.py),
[UI](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_ui.py), [navigation](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_navigation_redesign.py).
