# prompts/

Version 1 grounded AI tasks. Source goes in JSON user context, never system instructions. Schemas and exact-evidence tests govern changes.

## Subfolders
- `code_explanation/` — [code_explanation/KNOWLEDGE.md](code_explanation/KNOWLEDGE.md).
- `column_usage/` — [column_usage/KNOWLEDGE.md](column_usage/KNOWLEDGE.md).
- `lineage_validation/` — [lineage_validation/KNOWLEDGE.md](lineage_validation/KNOWLEDGE.md).
- `sas_lineage/` — [sas_lineage/KNOWLEDGE.md](sas_lineage/KNOWLEDGE.md).
- `schemas/` — [schemas/KNOWLEDGE.md](schemas/KNOWLEDGE.md).
- `sql_lineage/` — [sql_lineage/KNOWLEDGE.md](sql_lineage/KNOWLEDGE.md).
- `project_lineage/` — Strict project extraction protocol and evidence template. See [project_lineage/KNOWLEDGE.md](project_lineage/KNOWLEDGE.md).
- `lineage_review/` — Bounded host-issued candidate review. See [lineage_review/KNOWLEDGE.md](lineage_review/KNOWLEDGE.md).

## Files
- `README.md` — Prompt repository. Maintained documentation; consult implementation status for verification boundaries.

Project tasks are separate from five manual contracts: `project_lineage/` and `lineage_review/` v1 use strict full-unit evidence schemas under schemas/. Project task registration is routing-only; manual selection retains existing task names.

Project extraction/review now use protocol v2 compact unit references; manual task protocols stay v1. Host hydration restores immutable citations before canonical validation. Both canonical and wire generated schemas are packaged.
