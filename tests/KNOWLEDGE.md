# tests/

Unit, integration, security and AppTest regressions. Use temporary Store homes; no live LLM keys required. tests/fixtures supplies real deterministic input.

## Subfolders
- `fixtures/` — [fixtures/KNOWLEDGE.md](fixtures/KNOWLEDGE.md).

## Files
- `test_exports.py` — Behavioral regression tests for exports. Run with pytest; temporary runtime data only.
- `test_graph.py` — Behavioral regression tests for graph. Run with pytest; temporary runtime data only.
- `test_lineage_tree.py` — AppTest proves closed descendants are absent and expand/collapse controls change rendered branches.
- `test_hardening.py` — Behavioral regression tests for hardening. Run with pytest; temporary runtime data only.
- `test_ingestion.py` — Behavioral regression tests for ingestion. Run with pytest; temporary runtime data only.
- `test_llm.py` — Provider protocols, grounding/privacy, fenced JSON rejection boundaries, malformed HTTP envelopes and inferred merge retention. Temporary runtime data only.
- `test_logging.py` — Behavioral regression tests for logging. Run with pytest; temporary runtime data only.
- `test_sas.py` — Behavioral regression tests for sas. Run with pytest; temporary runtime data only.
- `test_sql.py` — Behavioral regression tests for sql. Run with pytest; temporary runtime data only.
- `test_store.py` — Behavioral regression tests for store. Run with pytest; temporary runtime data only.
- `test_ui.py` — Behavioral regression tests for ui. Run with pytest; temporary runtime data only.
- `test_workflow.py` — Behavioral regression tests for workflow. Run with pytest; temporary runtime data only.
- `test_workspace_configuration.py` — Workspace edits preserve identity/data; safe v1/v2 configuration portability, resource validation, isolation and injected-failure rollback.
