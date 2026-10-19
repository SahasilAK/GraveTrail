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

`prompts/project_lineage/` and `prompts/lineage_review/` contain v1 system/user assets. Their generated `project_lineage_response.json` and `lineage_review_response.json` schemas match strict Pydantic models in `ai_analysis_models.py`; parity tests cover schema equality and exactly one `{{context}}` placeholder. Prompt identity hashes system + template + canonical schema; validator/reconciliation identity remains separate.

Project output cites host-issued complete units and exact original expression coordinates. Review decides exactly the host-issued candidate set, without new publishable facts. Source is JSON user data; system messages never interpolate source. Examples distinguish constants, value/row roles, unused CTEs, ambiguous aliases, unknown wildcards, SAS runtime macros and repeated writers. Separate holdout fixtures under `tests/fixtures/ai_analysis/` are scorer labels and must never be included as model context. See [AI project analysis](AI_ANALYSIS.md).

Transmitted project JSON uses compact separators. Schema annotations (`title`, `default`, `description`, `examples`) are omitted recursively; named properties and every validation keyword remain. Prompt identity hashes the actual transmitted schema/system/template. Generated schema assets retain full Pydantic annotations for parity and documentation. Both previews and dispatch still count the full resulting envelope against unchanged privacy/profile limits.

The v1 project protocol supplies a host citation template and explicit operation/context/category names. SQL derivations retain complete projections including aliases; UPDATE/MERGE uses assignment right-hand sides, while SAS assignment/version scopes follow the task instructions. Omitted expression offsets are host-resolved only for a unique exact substring; explicit incorrect spans still fail. Review omits repeated evidence from compact candidates because the complete unit is supplied once, reserves 2,000 candidate characters during preview and leaves overflow unresolved.
