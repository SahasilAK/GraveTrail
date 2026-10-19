# prompts/schemas/

Generated Pydantic JSON response schema; test equality with GroundedResponse and regenerate when the model changes.

## Files
- `column_response.json` — Generated ColumnResponse v2 contract; compare to ai_results.py in tests.
- `explanation_response.json` — Generated cited ExplanationResponse v2 contract.
- `grounded_response.json` — Generated structured schema or recorded metrics; keep synchronized with owning code/tests.

- `project_lineage_response.json`, `lineage_review_response.json` — Pydantic-generated strict v1 project-analysis contracts; parity tests require exact equality.
