# Prompt engineering

Root `prompts/` contains task-specific system/user Markdown, a Pydantic-generated response
schema, representative positive and counterexamples, and version guidance. Wheels bundle these
files as package data. System messages never contain imported source. Context is JSON serialized.

`assist` hashes system+template and records the hash/version with provider/model/token metadata.
When updating a prompt, update its version, examples and test expectations. Run
`pytest tests/test_llm.py` for schema equality, template completeness, explicit evidence and
hallucination rejection. Exact quotes must match original unredacted evidence after privacy
redaction; a mismatch is rejected rather than approximated.

## Project extraction and review contracts

`prompts/project_lineage/` contains extraction prompt 6; `prompts/lineage_review/` uses review prompt 4. Their generated `project_lineage_response.json` and `lineage_review_response.json` schemas match strict Pydantic models in `ai_analysis_models.py`; parity tests cover schema equality and exactly one `{{context}}` placeholder. Prompt identity hashes system + optional focus instructions + template + transmitted schema; validator/reconciliation identity remains separate.

Project output cites host-issued complete units and preferably source-only expression references, which the host resolves to exact original coordinates. Review decides exactly the host-issued candidate set, without new publishable facts. Source is JSON user data; system messages never interpolate source. Examples distinguish constants, value/row roles, unused CTEs, ambiguous aliases, unknown wildcards, SAS runtime macros and repeated writers. Separate holdout fixtures under `tests/fixtures/ai_analysis/` are scorer labels and must never be included as model context. See [AI project analysis](AI_ANALYSIS.md).

Transmitted project JSON uses compact separators. Schema annotations (`title`, `default`, `description`, `examples`) are omitted recursively; named properties and every validation keyword remain. Prompt identity hashes the actual transmitted schema/system/template. Generated schema assets retain full Pydantic annotations for parity and documentation. Both previews and dispatch still count the full resulting envelope against model token capacity; disclosed source/context has a separate character allowance.

The v1 project protocol supplies a host citation template and explicit operation/context/category names. SQL derivations retain complete projections including aliases; UPDATE/MERGE uses assignment right-hand sides, while SAS assignment/version scopes follow the task instructions. Omitted expression offsets are host-resolved only for a unique exact substring; explicit incorrect spans still fail. Review omits repeated evidence from compact candidates, targets 2,000 candidate characters per batch, and checks larger singleton candidates against the actual full envelope. Every eligible candidate belongs to a batch; none receive approval by overflow omission.

## Project protocol v2

`project_lineage` and `lineage_review` use root `prompts/` system/template files and generated `*_wire_response.json` schemas. Model citations contain only `unit_id`; the host expands exact source hashes/offsets/lines/text before existing canonical validation. The canonical `*_response.json` schemas and legacy accepted facts remain readable. Prompt/schema hashes invalidate incompatible extraction caches. Durable unit caches use compact references; rejected provider text remains history-opt-in.

## Source focus and review batches

Extraction instructions keep conditional projection guidance in root `prompts/project_lineage/focus.md`. This file contains no source and is loaded only for a focused task, keeping ordinary requests small. Its content is included in the focused prompt identity. Continuation pins both prompt variants, so editing it invalidates incompatible cached focus results and saved continuation. Ordinary extraction hashes continue to identify the actual transmitted prompt. Unit evidence remains compact; extraction uses protocol v4 source-expression references while review stays v2. Canonical evidence shapes are unchanged.

Focused requests carry exact original header/projection/shared-context segments and absolute coordinates. Instructions preserve original output ordinals and assign shared facts to the first task. The host independently checks the partition and complete original semantics. Review instructions require exactly the supplied batch IDs; durable host checkpoints retain completed IDs, not model approval of unseen candidates.

## Extraction protocol v4

Prompt 6 issues source-only `expression_references` and accepts `expression_reference` on a derivation. The model omits expression text/offsets for this path; `ai_wire.decode_project_result` regenerates the catalog with the same dialect/settings and resolves exact original text/absolute coordinates before canonical validation. Conflicting supplied text/positions, foreign IDs and references hidden by projection focus fail closed. Semantic validation still checks the exact occurrence, branch, SAS version and dependency roles.

`ai_citations.py` creates locations from original syntax and tokens, including paged static PROC SQL and bounded SAS format syntax. It supplies no parser lineage answers. Full catalog metadata counts in preview/dispatch limits; redundant source/coordinate copies are omitted from the transmitted catalog. The runtime wire schema and generated `project_lineage_wire_response.json` change together, with parity tests. Legacy strict text/offset responses and compact canonical v2 checkpoints remain readable. Parser 14 / validator 4 plus prompt/schema hashes invalidate incompatible continuations and caches. Independent column labels and live precision qualification are separate work.


## Resumable AI analysis

Project extraction uses shared strict facts with SQL/SAS/dbt context. dbt prompts include safe source/resource/YAML/macro/artifact context rather than computed parser lineage answers. Batch protocol 1 wraps independently validated unit payloads (maximum eight); targeted resolution reuses exact source evidence and cannot override host validation. See [AI pipeline](architecture/ai-analysis-pipeline.md).

Protocol4 adds partial_expression_references and fragment input subsets for exact source/context views. The host validates each component, requires complete expression-range coverage and validates the union against the original parent. Review prompt4 uses source references and bounded one-input components, retaining scope/branch/version/ordinal identity. Full expressions remain local during component review. Complete source, projection and generic source/context tasks share the same strict evidence boundary. See the [detailed flow](user-guide/ai-analysis-flow.md).


## Protocol 5 file extraction (2026-10-23)

New project builds use independent AI extraction from exact file parts, token-budgeted items envelopes, persisted file records, one frozen-context completion wave, bounded file consolidation and deterministic operation-graph publication. Static analysis and manual assistance remain independent. Older hybrid/review/window/project-resolution descriptions on this page are historical and do not define new project builds. See [AI analysis](AI_ANALYSIS.md) and [pipeline architecture](architecture/ai-analysis-pipeline.md).

Offline qualification uses nonempty independent SQL/SAS/dbt golden transport fixtures. The oracle scores table, column and file relationships separately and catches semantic omissions despite complete model JSON. Mock results do not establish live-model accuracy; live precision/recall and cost evaluation remain pending. Ordinary tests spend no provider credits.
