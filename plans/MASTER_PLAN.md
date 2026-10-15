# DataForge Implementation Plan

**Goal:** Build the complete local engineering workflow specified in
`docs/prompts/MASTER_PROMPT.md`, prioritizing reliable evidence over speculative coverage.
**Architecture:** Single local Streamlit process, modular Python services, transactional
DuckDB, immutable content-addressed original files, SQL AST and conservative SAS rules.
**Execution:** Inline autonomous implementation; write regression fixtures before logic,
verify each slice, and maintain `IMPLEMENTATION_STATUS.md`. No approval pauses.

## Global constraints

Never execute imported code. No mandatory LLM. No fabricated dependencies or simulated
success. Bound uploads, filesystem access, graph size, network context and retries.
Keep the original content and provenance. Clearly document unsupported dynamic constructs.

## Review focus

Archive traversal and bombs; ambiguous names and macro references; CTE scope versus base
columns; atomic recovery after failures; cycles and large graph rendering.

## Vertical slices

These stage checkboxes track the delivered core. They do not assert that every detailed
master requirement is complete. See `CONTINUATION_PLAN.md` and `IMPLEMENTATION_STATUS.md`
for incomplete requirements and current work.

### 1. Foundation and persistent import
- [x] Create `pyproject.toml`, `app.py`, `src/dataforge/models.py`, `store.py`, `ingestion.py`.
- [x] Test ZIP traversal, allowed roots, extension filters, duplicate hashes, persistence.
- [x] Implement workspaces, versioned schema, inventory, immutable original bytes and limits.
- [x] Wire workspace selection, Builder upload/directory import, inventory and full viewer.
- [x] Gate: `pytest tests/test_ingestion.py tests/test_store.py` and Builder UI smoke.

### 2. SQL analysis
- [x] Tests: CTAS/INSERT/UPDATE/MERGE/DELETE, unions, quoted names, CTEs, aliases,
      ambiguity, exact evidence, parse errors, no transitive direct columns.
- [x] Implement `parsers/sql.py`: statement splitter, SQLGlot AST/scopes, read/write
      operations, source ranges, direct usage, warnings; `services.py`: transactional runs.
- [x] Interfaces: `parse_sql(content, dialect) -> ParseResult`; `analyze(store, workspace)`.
- [x] Gate: `pytest tests/test_sql.py` plus persisted SQL import/analyze in Builder.

### 3. SAS and CSV
- [x] Fixtures: explicit CSV import to WORK to staging to mart, unresolved macro, DATA
      SET/MERGE, PROC SQL/SORT/MEANS/TRANSPOSE/IMPORT/EXPORT, comments/quoted semicolons.
- [x] Implement `parsers/sas.py` with static macro assignments, librefs, conservative
      procedure extraction; `parsers/csv.py` bounded schema sampling and row count.
- [x] Gate: `pytest tests/test_sas.py tests/test_workflow.py` and mixed import in UI.

### 4. Graph, explorer and column usage
- [x] Test cycle-safe bounded traversals, cross-file linking and temporary contraction
      preserving all evidence; never infer a CSV match from a table's name alone.
- [x] `graph.py`: stable IDs, focused upstream/downstream/combined traversal and paths.
- [x] `ui/pages/`: exact asset chooser, progressive dependency tree, interactive offline
      HTML/SVG graph, relevant file viewer; columns with grouping/filter/exports.
- [x] Gate: `pytest tests/test_graph.py tests/test_ui.py` and browser verification.

### 5. LLM profiles and privacy
- [x] Test provider payloads with HTTP transport fakes, privacy gates, malformed output,
      invented names, invalid line ranges, prompt integrity and quarantine.
- [x] `llm.py`: provider-specific adapters, env-only secrets, model discovery, bounded
      retries, task routing, grounded structured validation; versioned `prompts/`.
- [x] Wire configuration and unresolved-statement assistance with explicit user action.
- [x] Gate: `pytest tests/test_llm.py`; live test only with an available configured endpoint.

### 6. Exports, productivity and hardening
- [x] Standalone HTML graph, JSON/CSV, original bundles, metadata transfer, code search,
      impact analysis, data dictionary and run comparison using shared inventory.
- [x] Test hostile HTML, workspace isolation, incremental replacement and rollback,
      missing/binary files, graph bounds; run representative generated workload benchmark.
- [x] Add all required docs, folder knowledge, lockfile, Docker and CI.
- [x] Gate: full pytest, Ruff, clean install, Streamlit health, actual browser workflow.

## Design

Palette: ink `#17324d`, blue `#2869c7`, teal `#177e89`, slate `#66788a`,
surface `#f5f8fc`, warning `#b66a16`; system sans for controls, monospace for code only.
Left aligned content, compact navigation, quiet separators, informative empty states.
The graph is the focal visual: evidence is always one selection away. Use native theme
support for light/dark; avoid decorative dashboard cards and external font requests.

## Data flow

`Input -> bounded inventory + original blob -> parse results -> atomic run -> graph/columns
-> focused explorer -> source evidence / offline exports`.
