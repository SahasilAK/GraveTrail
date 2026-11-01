# docs/architecture/

`overview.md` maps static/dbt and protocol-5 AI preparation, durable checkpointing, atomic publication and policy-checked clients with Mermaid, source/test links and evidence/query distinctions. Links pin the full 1864dc8 baseline. Website routes remain lowercased by the publication hook.

`contracts.md` defines admission, parser facts, identity/schema, publication, storage/recovery, AI/secret, transport/source-disclosure and export trust boundaries with concrete I/O/failure examples and regression evidence. Python interfaces are internal.

Overview embeds two standalone accessible SVGs in assets/diagrams for offline context and request/persistence flow. Current independent validate_extraction checks provenance/structure/consistency without static semantic approval; legacy ai_semantic/focused grounding are distinct. AI publication retains complete=False and semantic_coverage_not_proven.

Direct usage and the separate bounded column transformation service have distinct contracts.

- `ai-analysis-pipeline.md` — Coordinator/worker sequence, schema9 journals, quota/accounting/reuse, adaptive source/context views, component review/composition, source-offset persistence and one atomic graph publication.

ai-analysis-pipeline.md is the current protocol-5 file extraction/index/completion/consolidation/operation graph design. Older adaptive/resumable plans are marked superseded.

Recovery documents durable per-item passes/backoff, corrective sizing, pinned context restoration and frozen consolidation membership in existing journals.

The current pipeline adds pinned deterministic model-share allocation and three-pass unresolved partial publication with successful-checkpoint reuse. Enrichment waits for required upstream work to resolve; partial retry accepts only its own prior publication, retaining freshness and cumulative spending checks.
