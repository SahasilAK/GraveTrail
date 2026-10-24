# docs/architecture/

`overview.md` maps the static pipeline in Mermaid and links canonical root architecture/data-model/parser/security references. Source paths remain compatible; website routes are lowercased by the publication hook.

Direct usage and the separate bounded column transformation service have distinct contracts.

- `ai-analysis-pipeline.md` — Coordinator/worker sequence, schema9 journals, quota/accounting/reuse, adaptive source/context views, component review/composition, source-offset persistence and one atomic graph publication.

ai-analysis-pipeline.md is the current protocol-5 file extraction/index/completion/consolidation/operation graph design. Older adaptive/resumable plans are marked superseded.

Recovery documents durable per-item passes/backoff, corrective sizing, pinned context restoration and frozen consolidation membership in existing journals.

The current pipeline adds pinned deterministic model-share allocation and three-pass unresolved partial publication with successful-checkpoint reuse. Enrichment waits for required upstream work to resolve; partial retry accepts only its own prior publication, retaining freshness and cumulative spending checks.
