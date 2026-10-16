# Master specification acceptance matrix

Audited 2026-10-16 against `docs/prompts/MASTER_PROMPT.md` (1,597 lines). This matrix
supersedes old stage-completion claims. Implementation and external-service verification are
different gates. Tests use isolated stores and synthetic/hand-labeled fixtures; they do not
establish universal SQL/SAS accuracy or a production deployment certification.

**Verified** means implemented with automated behavioral evidence and the recorded running UI
checks. **Bounded coverage** identifies a deliberate conservative language/runtime boundary.
**External gate** means the implementation exists but the corresponding real environment has
not passed. Optional enhancements are explicitly separate.

| Master requirement | Implementation/evidence | Acceptance |
|---|---|---|
| §§1–4, 11–12: architecture, plans, persistent agent context | AGENTS.md, MASTER_PLAN, COMPLETION_PLAN, status, ADRs, per-folder KNOWLEDGE.md; modular domain/storage/parser/graph/services/UI | Verified |
| §§3–4, 17: multipage local application, startup/setup | app.py, six native pages, pyproject.toml, uv.lock, README; test_ui.py navigation and clean-install gates below | Verified locally |
| §5.1: nested ZIP import | ingestion.py ZIP stream/path/count/size/ratio validation; test_ingestion.py and actual ZIP import | Verified |
| §5.1: browser-selected directory | Native directory uploader retains relative paths; test_ingestion.py and prior actual directory upload | Verified |
| §5.1: restricted host directory | Explicit DATAFORGE_ALLOWED_ROOTS, resolved containment and symlink checks; actual scenario directory import | Verified |
| §5.1: independent persisted workspaces and reopening | Store, workspace picker, name/description editing and isolated databases; test_store.py, test_workflow.py, test_workspace_configuration.py | Verified |
| §5.1: SQL/SAS/CSV extension selection and skip reporting | Builder multiselect, ImportReport, duplicate/hash/decoding diagnostics and progress; test_ingestion.py | Verified |
| §5.1: bounded resources, individual failures, cancellation where practical | Limits, bounded record/allocation checks, per-file errors; cooperative service callbacks and Streamlit stop; no preemption of a blocked parser/HTTP read | Verified with stated boundary |
| §5.2: full inventory and immutable original content | source_files + hash-addressed original blobs, source versions, metadata-first selectors and exact downloads; concurrent import/version tests | Verified |
| §5.2: CSV metadata and configurable sample | csv.py headers/row count/delimiter/sampled types/fingerprint; sample0–100 via ParsingSettings; test_inventory_controls.py | Verified; first row explicitly assumed header |
| §5.3: import/parse counts, searchable inventory and exports | Builder report + success/partial/failed/pending metrics, extension breakdown, filtered table, metadata/full source, CSV/JSON; immediate post-analysis rerun regression | Verified |
| §5.4: SQL reads/writes, CTAS/views, insert/overwrite, update, merge, delete | SQLGlot AST and original statement locations; test_sql.py, labeled vendors; SQL Server SELECT INTO and Teradata volatile CTAS | Verified for tested syntax |
| §5.4: CTEs, nested queries, unions, aliases/quoted identifiers | Reachable scopes only; unused CTEs excluded; direct columns honor scope; test_sql.py and test_hardening.py | Verified for tested syntax |
| §5.4: dialect selection/failure handling | Default → extension → longest folder precedence, explicit parse diagnostics; no silent dialect guessing; test_remaining_settings.py | Verified |
| §5.4: statically analyzable stored-procedure logic | Unsupported Command/Block/procedural constructs produce diagnostics; no runtime execution or fabricated dependencies | Bounded coverage; full procedural compiler excluded |
| §5.4: SAS DATA/SET/MERGE/UPDATE/MODIFY, PROC SQL/common procedures | Dedicated rules, SORT/MEANS/SUMMARY/TRANSPOSE/IMPORT/EXPORT, file references and conservative direct variable lists; test_sas.py, vendor SAS chain | Verified for tested rules |
| §5.4: SAS macros/libraries/unsupported constructs | Static variables and configured library mappings; dynamic controls/definitions/invocations/name literals diagnosed, inline data excluded from code | Bounded coverage; runtime expansion unavailable |
| §§5.4–5.5: conservative identity, aliases, temporary/job scope | asset_identity.py; qualified ambiguity diagnostics, explicit job/session mappings, persistent global assets, mixed-lifetime reads unresolved; test_job_identity.py | Verified |
| §§5.4–5.5: preserve intermediate transformations/evidence | NetworkX contraction retains all supporting records and named intermediate jobs; expanded/collapsed views, path/graph export tests | Verified |
| §§5.5–5.6: normalized operations, evidence and logical steps | DuckDB migrations1–4, operations/input-output memberships, stable asset IDs, statement/hash/line/method/confidence/status; services.py and graph.py | Verified |
| §5.7: selected/all/changed/rebuild/validate/unresolved review | Content/config/version cache, atomic materialization, immutable run snapshots, prior facts on failure; selected incompatible-cache preservation | Verified |
| §6.1: partial/qualified search and exact ambiguous choice | Search plus searchable native selector with namespace/kind/job context; never auto-select first; UI/job tests | Verified |
| §§6.2–6.3: upstream/downstream progressive trees and cycles | Lazy open branches, expand-to-depth/collapse, evidence/file/status summaries, explicit limits and cycle stops; test_lineage_tree.py | Verified |
| §6.4: tree/source panels and original source controls | Left tree and right relevant-file/source viewer, code highlighting/line numbers, source search, native copy and original download; active-tab evidence regression/graph-selection override and running UI proof | Verified |
| §6.5: directed interactive focused graph | Direction/depth/node bounds, root paths, node search, zoom/pan/fit, path highlighting, node/edge evidence, temporary toggle; graph/export tests and actual edge clicks | Verified locally |
| §6.6: original ZIPs, lineage/path tables and graph JSON | exports.py, exact version bundles, CSV/JSON paths with explicit traversal boundaries, escaped reports; test_exports.py | Verified |
| §6.6: self-contained HTML5 graph | Embedded data/CSS/JS, no CDN, shared interactive renderer, JS syntax and mount tests, actual download | Export verified; direct file-browser interaction external gate |
| §§7.1–7.5: direct column usage | Scope-local references, context/alias/expression, file/line/code, unique/ref counts, grouping/filtering/source/downloads; test_sql.py, test_schemas.py and UI | Verified |
| §7.4: wildcards/ambiguity/CTE/transitive boundaries | Only consistent explicit typed DDL expands plain wildcards, labeled inferred with query/declaration evidence; unknowns retained, no CSV filename/schema guessing | Verified |
| §8.1: provider profiles and differing protocols | llm.py/provider_settings.py: OpenAI-compatible, Anthropic, Ollama, Gemini, Azure and Databricks-specific requests; discovery/manual IDs, environment-key refs, connection controls | Protocol tests verified; most live providers external gates |
| §8.1: OpenAI/Claude/Ollama/LM Studio/OmniRoute/compatible/Databricks/Azure/Gemini/OpenRouter targets | Profile-specific protocol/auth behavior; synthetic HTTP envelope/error tests; configuration instructions in LLM_INTEGRATION.md | Mock-backed coverage; no blanket live-provider claim |
| §8.1: Codex and Databricks Genie investigation | Integration guide distinguishes supported API protocols from desktop/subscription or separate query-agent integrations | Documented boundaries; neither impersonated as generic chat |
| §8.2: default/task models and suitable fallback | Task routing, ordered same-host transient-only fallback, manual model IDs, usage where returned; privacy/routing regressions | Verified with synthetic HTTP |
| §§8.3–8.4: deterministic-first grounded AI results | Explicit focused previews, strict schemas, exact source/known-asset checks, quarantine, inferred merge and version/job invalidation; tests for invented/cross-statement claims | Verified with synthetic HTTP |
| §§8.4–8.5: task schemas/prompts/provenance | Five prompt tasks, task-specific column/explanation v2, schema-inclusive hashes, provider/model/usage/duration/outcome, bundled wheel assets; advisory results never create graph edges | Verified |
| §8.6: privacy/security/history/logging | External/full-source gates, redaction/context limits, opt-in interaction bodies, retention, safe logs, credentials only from env names | Verified locally; redaction explicitly best effort |
| §9: parsing/lineage settings | Dialects/macros/library/case/wildcards/sample/job settings, confidence/inferred/diagnostic views and reanalysis preferences; compatible safe transfer | Verified |
| §9: storage/workspace settings | Naming/descriptions, allowlisted session storage choices, database size, ingestion/history recovery, safe configuration transfer, staging cleanup/restore and named deletion | Verified; no automatic migration or blob GC |
| §9: performance/resource controls | Parsing1–8, AI per-workspace1–4/app8, chunk preview, file/context/token/depth/node/timeout/retry budgets and cache clear | Verified; process-local/cooperative limits documented |
| §9: visualization settings | Fourteen preserved/additive themes, graph direction/palette/edge/labels/tree depth/temp/source defaults; no user theme overwritten | Verified by palette/config/UI tests; appearance remains user-selected |
| §10: productivity enhancements | Dashboard/hotspots/orphans/cycles, dictionary with provenance, downstream impact, run comparison, code search and cited advisory explanation | Implemented; optional scope |
| §§11–12: docs and tested feature commits | Guides, data model, extension/security/performance/testing docs, ADRs/status/maps; coherent Conventional Commits after checks | Verified |
| §§13–14: tests, labeled metrics and bounded scalability | All eight required scenarios plus vendor/job/security/advisory/UI regressions; 500-file benchmark records cold/warm/traversal/evidence/accuracy | Verified on synthetic workloads; real-project accuracy external gate |
| §15: integrity and untrusted content | No imported execution, parameterized values/fixed-table allowlists, path/resource controls, immutable original versions, atomic replacement and rollback | Verified within documented local single-user threat model |
| §§16–17: setup/package/CI/container definitions | Lockfile, wheel/sdist allowlists, clean source install, Windows/Linux/Python CI matrix and nonroot Docker definition | Local gates below; remote CI/Docker runtime external gates |

## Eight required fixture scenarios

| Scenario | Evidence |
|---|---|
| CSV → SAS WORK → staging → mart | fixtures/scenario, test_workflow.py; explicit file link and collapsed provenance |
| Multiple orders matches | test_workflow.py/test_ui.py; exact selector required |
| Reachable CTE resolution | test_sql.py; no persistent CTE nodes or unused CTE dependencies |
| Direct versus transitive columns | test_sql.py/test_schemas.py; direct table attribution only |
| Ambiguous SAS macro | test_sas.py; warning and no fabricated edge |
| Cyclic dependencies | test_graph.py/test_workflow.py; bounded traversal and SCC reporting |
| No LLM configured | test_ui.py/test_workflow.py; import/analysis/explore/columns/exports remain available |
| Invalid/hallucinated LLM output | test_llm.py/test_ai_results.py/test_assistance_queue.py; quarantine and no mutation |

## Release gates and external boundaries

Latest measured gate results are recorded in IMPLEMENTATION_STATUS.md. Clean artifacts live
under ignored `.dataforge/verification/`; do not commit runtime databases, sources or secrets.

- Literal OmniRoute model **auto**: latest retry failed during discovery in4.15s, before
  connection/SQL/SAS assistance. No local TCP listener was present on20128; named credential
  exists. Earlier discovery returned964 IDs including auto/... routes but no literal auto. That absence does
  not itself prove a route unsupported. No fixed model substitution is allowed. Historical
  fixed-route success predates the user's auto-only instruction and is not current acceptance.
  Keep strict grounding/quarantine. Re-run `scripts/verify_llm.py` after gateway availability/routing
  changes; use named OMNIROUTE_API_KEY and synthetic sources. New advisory tasks are mock-backed.
- Other live provider protocols: credentials/endpoints not exercised here; synthetic HTTP
  tests establish request/validation behavior, not live account compatibility.
- Docker: CLI installed; Docker Desktop Linux engine pipe unavailable on final check. No
  container build/run is claimed. CI definition exists; no remote CI run/push was requested.
- Standalone HTML: self-contained artifact and shared JS validated/downloaded. This browser
  environment blocked direct file navigation in earlier checks, so independent offline browser
  interactions remain unverified. Serving it via an application would not prove that gate.
- Windows symlink-creation regression skips when the account lacks permission; runtime checks
  remain enforced. Real private production projects and large dense graphs were not supplied.
- This is conservative local static analysis: no universal procedural compiler, runtime macro/
  dynamic SQL execution, database schema discovery, execution-order inference, distributed job
  scheduling or multi-user authentication. Unknown cases retain diagnostics and source evidence.

Optional additions not required for core delivery: transitive column-transformation lineage,
SVG/PNG exports, automatic blob garbage collection, full portable source/history backups,
scheduled retention, collaboration/authentication and a general conversational assistant.

Implementation slices are complete within these documented boundaries. Full external release
acceptance remains open; an all-requirements-green or production-certification claim is not made.


## Final local gate evidence

- Main checkout:220 passed,1 skipped in25.21s; Ruff and lock validation pass.
- Clean source distribution: fresh Python3.11.16 environment with locked offline dependencies;
  final refreshed code passed220 tests/1 skipped in25.06s; Ruff clean. Installed-wheel/UI
  results are recorded in the status tail.
- Final500-file SQL chain: import15.8705s, cold2.1065s, warm0.8708s; all500 parses reused,
  traversal0.0969ms, exact500 expected edges and evidence coverage1.0. See BENCHMARK_RESULTS.json.
- Seven vendor/SAS cases run in both LF and CRLF (14 fixture runs), preserving original bytes
  and original contiguous statement evidence. No newline-normalized fiction in stored snippets.
- Wheel import with Python -I resolves site-packages, parser7 and both advisory response schemas.
  Source archive excludes runtime homes/databases. Primary8501 and clean8503 health returned200.
- Installed-wheel browser imported delivered scenario directory (7 accepted/2 documentation
  files skipped), analyzed9 assets/7 edges, showed expected macro warning, explored source
  statements and tree. No LLM was configured for this deterministic workflow.

Final continuation: primary8501 restarted/health200 with original1 workspace/7 files/9 assets/
7 edges/2 runs intact;80 code/test/fixture files match the clean verified artifact byte-for-byte.
