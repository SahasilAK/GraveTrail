# prompts/schemas/

Generated Pydantic JSON response schema; test equality with GroundedResponse and regenerate when the model changes.

## Files
- `column_response.json` — Generated ColumnResponse v2 contract; compare to ai_results.py in tests.
- `explanation_response.json` — Generated cited ExplanationResponse v2 contract.
- `grounded_response.json` — Generated structured schema or recorded metrics; keep synchronized with owning code/tests.

- `project_lineage_response.json`, `lineage_review_response.json` — Pydantic-generated strict v1 project-analysis contracts; parity tests require exact equality.

`project_lineage_wire_response.json` and `lineage_review_wire_response.json` are generated v2 transport contracts from ai_wire; canonical response schemas stay readable for durable v1 accepted data.

Extraction wire schema is v4, including dependency fragments and optional expression_reference, with strict legacy expression/offset decoding. Local canonical expressions/inputs can exceed bounded wire limits after validated host composition. Review wire schema remains v2; test_ai_wire enforces generated/runtime equality for both.
