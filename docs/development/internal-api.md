# Internal Python API and contracts

These are implementation interfaces at the [documented baseline](index.md), not a public
Python SDK. Signatures shown here are copied from that source. CLI/MCP adapters add
permissions, source disclosure, pagination and sanitized errors; calling a low-level function
in Python does not automatically apply those policies. Start with the
[complete working example](getting-started.md#trace-one-source-to-one-output).

## Import and parse

```python
Importer(store: Any, workspace: str,
         allowed_roots: Iterable[str | Path] = (), limits: Limits | None = None)
Importer.files(entries: Iterable[tuple[str, bytes]], extensions: set[str],
               progress: Callable[[ImportReport], Any] | None = None,
               cancelled: Callable[[], bool] | None = None, *,
               source_kind: str = 'files', dbt_options=None) -> ImportReport
parse_sql(content: str, dialect: str | sqlglot.Dialect = '') -> ParseResult
parse_sas(content: str, library_mappings: dict[str, str] | None = None,
          macros: dict[str, str] | None = None, sql_dialect: str = '') -> ParseResult
parse_csv(content: str, path: str, sample_size: int = 25) -> ParseResult
```

`Importer.files` consumes relative path/raw-byte pairs. `directory` and `zip` reuse the same
inventory contract but enforce their own path/archive admission. Defaults are 10,000 files,
20 MiB per file, 200 MiB total, 100 MiB archive and compression ratio 200. Inspect
[`Limits` and `ImportReport`](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/ingestion.py) rather than treating these as a
promise that every file below a limit is supported. Report counts and diagnostics identify
accepted, skipped and duplicate inputs. `safe_relative('../outside.sql')` raises `ValueError`;
unsupported/binary content must not become an executable fallback.

A parser receives decoded complete source, not a Store, network client or Streamlit state.
It returns `ParseResult(operations, assets, diagnostics, metadata)`. For example:

```python
from dataforge.parsers.sql import parse_sql

source = "CREATE TABLE mart.orders AS SELECT id FROM raw.orders;"
parsed = parse_sql(source)
operation = parsed.operations[0]
assert operation.sources[0].name == "raw.orders"
assert operation.targets[0].name == "mart.orders"
assert operation.code == source
assert (operation.start, operation.end) == (1, 1)
```

An `Operation` includes kind, source/target `AssetRef`s, exact code, one-based inclusive
start/end lines, extraction method/confidence, direct `Usage`s, diagnostics/warnings,
derivations and optional `table_pairs`. `table_pairs=None` permits the normal all-input/output
pair materialization; an explicit pair list selects accepted input/output indices and is
validated. `AssetRef.identity` can retain a logical identity separate from its display name.
`ParseResult.to_dict/from_dict` is the cache round-trip contract.

Source: [models](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/models.py), [SQL](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/parsers/sql.py),
[SAS](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/parsers/sas.py), [CSV](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/parsers/csv.py).
Proof: [workflow](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_workflow.py), [SQL](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_sql.py),
[SAS](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_sas.py), [schemas](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_schemas.py).

## Analyze and retrieve original evidence

```python
analyze(store: Store, workspace: str, file_ids: list[str] | None = None,
        force: bool = False, progress: Callable[[float, str], None] | None = None,
        cancelled: Callable[[], bool] | None = None) -> dict[str, Any]
Store.file(file_id: str, content_hash: str | None = None) -> dict[str, Any]
Store.original(file_id: str, content_hash: str | None = None) -> bytes
Store.snapshot_content(inventory: dict[str, Any]) -> str
```

`analyze` returns `run_id`, `analyzed`, `cached`, `duration`, `assets` and `edges`. It takes the
analysis lock; an active project AI run blocks parser publication. Its cache key includes
parser version, content hash, relative path and parsing configuration. Selection reparses
chosen files and reuses compatible cached facts for others; previously analyzed incompatible
entries are refreshed, while newly imported unselected files stay pending. Failed publication
retains the last committed graph. Cancellation is cooperative and failure/cancellation marks
the run rather than committing half a workspace.

To inspect evidence for an edge, use its `file_id` plus `source_hash`; `Store.original(file_id)`
without a hash selects the current version, which may differ after re-import. `snapshot_content`
checks the pinned inventory representation. Use parameterized Store SQL, and keep the owning
Store alive only for the intended lifecycle. `Store.transaction()` serializes a block and
rolls back when it raises; do not hold it across provider network waits.

Source: [services](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/services.py), [Store](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/store.py).
Proof: [persisted workflow](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_workflow.py), [Store](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_store.py),
[version publication](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_ai_version_publication.py).

## Query graph, direct columns and derivations

```python
LineageGraph(assets: list[dict[str, Any]], edges: list[dict[str, Any]],
             min_confidence: float = 0.0, include_inferred: bool = True)
LineageGraph.focus(asset: str, direction: str = 'upstream', depth: int = 5,
                   limit: int = 200) -> LineageGraph
LineageGraph.path_report(asset: str, direction: str = 'upstream', limit: int = 50,
                         depth: int = 15, *, max_relationships: int | None = None,
                         max_evidence: int | None = None,
                         include_code: bool = False) -> dict[str, Any]
column_report(store: Store, workspace: str, asset_id: str) -> list[dict]
column_catalog(store: Store, workspace: str, asset_id: str,
               limit: int = 500) -> list[dict[str, Any]]
```

`search` returns candidate assets by substring; select an exact `asset_id` before traversal.
`path_report` accepts upstream/downstream, 1–500 paths and depth 1–30. It returns `paths`,
`boundaries`, `truncated`, `complete` and selection/budget metadata. A missing selected ID
returns an empty path report. Cycles, limits, missing endpoints and unresolved edges affect
coverage; an empty list by itself does not prove there are no dependencies. Parallel stored
evidence lives on the graph relationship and survives temporary contraction. Source excerpts
are omitted unless explicitly requested.

`column_report` lists direct references, their context/expression/alias, operation and exact
source evidence. `column_catalog` and `trace_columns` in
[transformations.py](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/transformations.py) address derivation paths, role/scope,
unknown writers and coverage. A WHERE-only reference must not silently become a value
contribution. Do not derive transformation claims by recursively joining direct-usage rows.

Proof: [graph](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_graph.py), [transformations](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_transformations.py),
[transformation access](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_transformation_access.py).

## Export committed facts

```python
export_lineage_excel(store: Store, workspace: str, asset: str, *,
                     direction: str = 'upstream', max_paths: int = 50,
                     max_depth: int = 15, max_relationships: int = 2000,
                     collapse_temporary: bool | None = None,
                     include_evidence: bool = False,
                     include_source_text: bool = False) -> tuple[bytes, dict[str, Any]]
```

This service snapshots committed graph/settings/revision and returns XLSX bytes plus metadata,
including selected `source_versions`. It neither analyzes pending imports nor calls AI. Bounds
include 500 paths, depth 30 and 20,000 relationships. Source text requires the Evidence sheet;
`include_source_text=True, include_evidence=False` raises `ValueError`. Large graph/text/time
budgets fail explicitly. Stale analysis appears as a warning in scope metadata. Data cells use
literal text so imported values cannot become spreadsheet formulas.

[Graph image service](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/graph_image_service.py) similarly returns bytes/metadata
for SVG/PNG; [exports](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/exports.py) owns offline graph/report/source serializers.
The automation layer adds artifact IDs, authorized retrieval and response chunking.
Proof: [Excel](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_excel_exports.py), [graph images](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_graph_images.py),
[image artifacts](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_image_artifacts.py).

## Use policy-checked automation inside Python

```python
AgentService(store: Any, policy: AccessPolicy | None = None)
AgentService.call(action: str, workspace_id: str = '',
                  options: dict[str, Any] | None = None,
                  **arguments: Any) -> dict[str, Any]
```

The default `AccessPolicy()` grants reads, with workspace settings still able to deny access
or source. For a bounded read:

```python
from dataforge.agent.contracts import AccessPolicy, AgentError
from dataforge.agent.service import AgentService

service = AgentService(store, AccessPolicy(workspaces=(workspace,)))
try:
    result = service.call("assets", workspace, options={"limit": 10, "max_chars": 4000})
    print(result)
except AgentError as exc:
    print(exc.response())
finally:
    service.close()
```

Responses are JSON-compatible. `AgentError.response()` is `{"error": {"code": ..., "message": ...}}`
plus safe details. Unknown operations/invalid arguments use `invalid_argument`; unauthorized
workspace access uses `forbidden`; I/O failures use `io_error`. Oversized responses use
`budget_too_small` rather than silent JSON truncation. `QueryOptions` forbids extra keys;
cursors bind the query and revision. Launch writes, workspace writes, source disclosure,
configuration writes, provider origin/reference authorization and local administration are
independent checks. MCP is a transport over these checks, not a policy bypass.

Source: [service](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/agent/service.py), [contracts](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/agent/contracts.py),
[paging](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/agent/paging.py). Proof: [service](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_agent_service.py),
[MCP](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_agent_mcp.py), [parity contracts](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_parity_contracts.py).

## Project analysis and focused assistance

```python
preview_analysis(store, workspace, request, *, connections=None, progress=None)
run_analysis(store, workspace, request, *, connections=None, authorize=None,
             progress=None, cancelled=None, transport=None)
analysis_report(store, workspace, run_id=None, *, include_source=False)
```

`request` is an `AnalysisRequest`. Parser preview stays offline; AI preview resolves the
pinned model, source units, budgets and blockers without dispatching a provider call. Project
AI execution belongs behind the authorization service above. `run_analysis` returns an
`AnalysisReport`; durable report reads expose saved work and publication outcome. Project
`validate_extraction` checks source-reference provenance and internal consistency without
static semantic approval. AI publication keeps `complete=False` and
`semantic_coverage_not_proven`; model-reported coverage is not a semantic proof. Protocol 5
accepts parser/AI; compatibility model fields for hybrid, additional review, character/window/
parallel/lifetime batch controls are explicitly rejected by the coordinator. Resume requires
compatible saved protocol, inventory, configuration, profile and publication pins; unknown
request outcomes require the applicable recovery decision. A committed partial run can retry
its unresolved work while preserving successful checkpoints.

Focused assistance uses `preview_assistance(...)` followed by `assist_task(...)`, pinned to
file hash/job and optionally the prepared request fingerprint. Its saved result is separate
from explicit `merge_claims(store, workspace, record_id) -> int`. Advisory explanation/column
results remain non-mergeable. See [AI architecture](../architecture/ai-analysis-pipeline.md),
[LLM adapter](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/llm.py) and [project policy adapter](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/src/dataforge/project_analysis.py).
Proof: [build contract](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_ai_build_contract.py), [resumable files](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_ai_resumable_files.py),
[partial recovery](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_ai_partial_recovery.py), [focused assistance](https://github.com/SahasilAK/GraveTrail/blob/1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414/tests/test_focused_assistance.py).
