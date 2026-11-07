# Local analysis and optional AI

Static analysis is the core workflow. After installation, supported parsing, DuckDB
storage, traversal and exports run locally without an AI account, API key or paid
model service. Imported SQL, SAS, Python and Jinja are never executed. No warehouse
connection proves runtime behavior.

| Workflow | Input and result | Network boundary |
| --- | --- | --- |
| Static | Supported parsers inspect imported source/artifacts | No AI provider request |
| Optional project AI | Independent extraction of one SQL, SAS or dbt family; facts remain inferred | Selected source ranges, authorized definitions/context, instructions and model settings go to the configured provider |
| Focused assistance | Explicit source-range question, separate acceptance/merge | Disclosed range/context go to the selected provider |

Current project AI does not compare parser answers or use parser semantic approval.
Historical hybrid runs remain readable; new builds reject retired comparison/review/
execution-window controls. Choosing Static explicitly returns to static results.
Project size alone does not require AI.

## Provider disclosure

**A localhost gateway can forward requests upstream.** Check its routing and policies;
the address alone does not establish local processing. Privacy permission, source
disclosure and confirmed model capacity apply before starting AI.

Preview, ordinary graph browsing and reopening saved results make no generation calls.
Connection tests/model discovery are separate explicit network operations. Full interaction
capture is off by default; enabling it can retain redacted source-bearing bodies locally,
including in backups. See [AI analysis](../AI_ANALYSIS.md) and [providers](../LLM_INTEGRATION.md).

## Three separate offline scopes

1. **Static analysis:** requires an installed environment and imported files. Installation,
   updates and optional dependencies can require downloads. No dbt packages or warehouse
   artifacts are fetched automatically. The built-in graph renderer needs no remote scripts.
2. **Downloaded HTML:** the [fixture example](../examples/interactive-lineage.md) embeds
   graph, CSS and JavaScript. Its separate offline verification is recorded there.
   It is a snapshot, not a portable workspace.
3. **Documentation site:** assets/search are built locally, but external links and
   Mermaid integration can need network access. The header can fetch GitHub repository
   metadata, and Mermaid uses an external unpkg module. Fonts use the system stack.
   No whole-site offline guarantee is made.
   Core diagrams also have standalone editable SVG sources.

Cancellation closes the client request and prevents further dispatch; it cannot guarantee
upstream processing or billing stops. Unknown usage stays unknown. See [recovery](../user-guide/ai-analysis-controls-and-recovery.md).
