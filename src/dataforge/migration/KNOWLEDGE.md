# src/dataforge/migration/

Static, workspace-owned dbt migration. Imported code remains data throughout the workflow.

- `sources.py` — Complete source ranges and conservative SQL, SAS and dbt source extraction.
- `engine.py` — Model planning, literal dbt dependency lowering, independent SQL inspection, lineage and quality gates.
- `targets.py` — Enabled format and warehouse registries, pinned profile and target SQL/type generation.
- `service.py` — Immutable retained inputs, Store schema 11, transactional revisions and engineer reviews.
- `assistance.py` — Scoped disclosure, provider budgets and attempt journal, proposals and approved lessons.
- `exports.py` — Revision-pinned dbt project, documentation, lineage and review bundle.
- `inspection.py` — Code inventory, line-anchored annotations and inert evidence for unresolved regions.
