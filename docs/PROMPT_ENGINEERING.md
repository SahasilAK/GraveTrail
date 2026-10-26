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

Current project builds load `prompts/project_lineage/extract.md` through
`ai_batching.extraction_instructions`. The system prefix includes the compact JSON-serialized
Pydantic `PartExtraction` item schema; the response is an `ExtractionEnvelope` containing
independently validated items. Source parts, relevant definitions, settings and optional
saved details are JSON user data. System instructions contain no imported source.

File/hash/offset ownership and identity validation are separate from AI semantic inference.
Parser answers are not prompt context or semantic approval. Completion and file consolidation
share protocol 5 and its durable attempt ledger. Protocol/instruction/schema identity is
pinned for compatible resume. The complete actual provider envelope and framing estimate
count in preview/dispatch budgets; explicit source-disclosure limits apply separately.
Preview never downloads tokenizer assets.

`project_lineage` is the sole current project route. Legacy extraction/review system/template
and generated response/wire schemas remain packaged for retained contracts; their prompt
numbers and review contracts are not the current build protocol. Historical sections below
explain those formats. Holdout gold is scorer data and must never become model context.
See [AI project analysis](AI_ANALYSIS.md).

## Project protocol v2

**Historical contract:** pre-protocol-5 extraction/review used root system/template files
and generated `*_wire_response.json` schemas. Unit-only citations expanded to exact source
identity/coordinates before canonical validation. Canonical schemas and saved accepted
facts remain readable; old paused runs require a new build. This is not the current
`ExtractionEnvelope`/`PartExtraction` wire format.

## Source focus and review batches

**Historical execution:** `project_lineage/focus.md` supplied conditional projection
guidance, with original header/projection/shared-context coordinates and output ordinals.
Focused prompt variants, candidate batches and completed review IDs were checkpointed.
Current builds prefer whole files and otherwise use exact contiguous parts, one bounded
completion wave and file-local consolidation. They do not execute this focus/reviewer flow.

## Extraction protocol v4

**Historical wire contract:** prompt 6 supported source-only `expression_references` and
`expression_reference` derivations. `ai_wire.decode_project_result` regenerated source
locations and resolved them to exact expressions before legacy semantic validation.
Foreign/stale/conflicting or hidden references failed validation. `ai_citations.py` and
legacy wire/schema parity tests preserve these retained formats. Parser 14 / validator 4
were qualification versions at that checkpoint, rather than current build settings.
Current protocol 5 cites original file-part source references and does not require a
parser-generated expression catalog to accept inferred transformations.

## Resumable AI analysis

Each current build selects SQL, SAS or dbt as its family. dbt parts carry disclosed
project/resource/YAML/macro/artifact context with explicit origins, rather than computed
parser lineage answers. Every valid item is checkpointed independently, so failed siblings
do not erase successes. Token capacity and expected output determine packing; no fixed
eight-unit, files-per-request, reviewer or execution-window policy governs new builds.
See the [AI pipeline](architecture/ai-analysis-pipeline.md) and
[detailed flow](user-guide/ai-analysis-flow.md).

## Protocol 5 file extraction (2026-10-23)

New project builds use independent AI extraction from exact file parts, token-budgeted
items envelopes, persisted file records, one frozen-context completion wave, bounded file
consolidation and deterministic operation-graph publication. Static analysis and manual
assistance remain independent. Accepted AI facts stay inferred; exact citations and valid
JSON do not prove semantic completeness. See [AI analysis](AI_ANALYSIS.md) and
[pipeline architecture](architecture/ai-analysis-pipeline.md).

Offline qualification uses nonempty independent SQL/SAS/dbt golden transport fixtures.
The oracle scores table, column and file relationships separately and catches semantic
omissions despite complete model JSON. Mock results do not establish live-model accuracy;
live precision/recall and cost evaluation remain pending. Ordinary tests spend no provider credits.
