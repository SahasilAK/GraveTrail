# Prompt engineering

Root `prompts/` contains task-specific system/user Markdown, a Pydantic-generated response
schema, representative positive and counterexamples, and version guidance. Wheels bundle these
files as package data. System messages never contain imported source. Context is JSON serialized.

`assist` hashes system+template and records the hash/version with provider/model/token metadata.
When updating a prompt, update its version, examples and test expectations. Run
`pytest tests/test_llm.py` for schema equality, template completeness, explicit evidence and
hallucination rejection. Exact quotes must match original unredacted evidence after privacy
redaction; a mismatch is rejected rather than approximated.
