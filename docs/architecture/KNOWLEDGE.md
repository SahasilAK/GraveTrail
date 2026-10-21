# docs/architecture/

`overview.md` maps the static pipeline in Mermaid and links canonical root architecture/data-model/parser/security references. Source paths remain compatible; website routes are lowercased by the publication hook.

Direct usage and the separate bounded column transformation service have distinct contracts.

- `ai-analysis-pipeline.md` — Coordinator/worker sequence, schema9 journals, quota/accounting/reuse and one atomic graph publication.
