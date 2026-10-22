# How AI analysis builds lineage

AI analysis is one build: extraction, saved checkpoints, linking, optional targeted
resolution and publication. SQL, SAS and dbt can share a workspace. Static parser
analysis remains the default and its parsing algorithms are unchanged.

```mermaid
flowchart TD
    A[Enable AI and choose limits] --> B[Offline source and context preview]
    B --> C[Explicit Analyze action]
    C --> D[Complete source units]
    D --> E[Reuse compatible saved work]
    E --> F[Fit pending units into requests]
    F --> G[Quota and request-slot admission]
    G --> H[Bounded parallel provider calls]
    H --> I[Validate each item against original evidence]
    I --> J[Save accepted item checkpoints]
    J --> K{Pending work?}
    K -->|Yes| F
    K -->|No| P[Compose validated expression components]
    P --> L[Link saved table and column facts]
    J --> M[Bounded targeted resolution when needed]
    M --> I
    L --> N[Freshness and permission checks]
    N --> O[Publish one consistent graph]
```

## Plan complete units

A unit prefers a complete SQL statement, a safe projection group retaining its parent
statement, a SAS DATA/PROC/macro block, or a dbt resource with project context.
When necessary, the planner creates bounded views of original source and indexed
context. Every view retains exact coordinates and parent identity; omitted ranges
belong to sibling tasks. A fragment never becomes a standalone executable statement.
The full original remains local for validation and publication; fragment coverage is
explicitly partial. More source creates more checkpointed work rather than requiring
the user to calculate character counts. A model unable to fit the minimum protocol,
or unsupported semantics, still requires attention.

For dbt, project membership takes priority over the `.sql` extension. Preparation
includes resource identity, root/package/version, relevant `ref`/`source` and macro
definitions, YAML and selected source/artifact mode. Configuration and macro files
are disclosed as context rather than fake extraction tasks. Selecting a dbt member
includes its project closure; inspect that disclosure before Analyze.

Imported SQL, SAS, Jinja, Python and hooks are never executed. GraveTrail does not
run dbt compile or download packages. Dynamic templates, Python column semantics,
unknown wildcard schemas and generated-to-source mappings may remain partial.

## Gather structured facts

Each model item proposes table reads/writes, relationships, column usage,
expressions and derivation inputs with dependency roles. It also reports coverage
and unresolved symbols. Host-issued unit and expression references bind proposals
to immutable source hashes and exact coordinates. The host supplies execution
metadata; the model cannot authorize publication or certify its own accuracy.

Validation checks identities, original evidence, scope and supported semantics.
Accepted AI additions remain inferred. A model or reviewer cannot establish a
schema merely by asserting one, or turn join/filter dependencies into values.

An expression can itself exceed one request or contain more dependencies than a
response can hold. In that case, each view can return a component: an original
expression reference plus only the dependency inputs and roles visible in that
view. The database stores the component, its exact covered ranges and review
decisions. It does not treat the component as a complete column derivation.

## Save and continue

A successful item is checkpointed independently. Missing or malformed items do
not erase successful siblings. A bounded repair retries pending items; oversized
batches shrink. Within an active authorized build, execution windows roll over
automatically while the finite project allowance remains available.

After restart, choose **Continue AI analysis**. Completed checkpoints are reused,
including completed units inside a partially processed file. Opening the app,
previewing, polling or browsing a graph sends no source. An unknown dispatched
outcome needs explicit retry because the previous call may already have been billed.

## Connect the saved facts

First, the host groups compatible components by original expression, target,
scope, branch, version and output ordinal. Their ranges must cover the complete
expression. It combines their inputs, restores the original expression locally
and checks the complete dependency set against supported source semantics.
Missing coverage, unsupported semantics or an incorrect input set cannot produce
a complete derivation. Optional review checks bounded components before this
step; rejected components invalidate a previously composed result as well.

The host reads validated checkpoints to connect scoped producers, consumers and
column dependencies. It retains intermediate operations and expressions. It does
not send the entire project to one final model request. Equal names in different
dbt roots/packages/versions remain distinct; multiple writers without proven
execution order remain unresolved. Cycles are reported with bounded graph work.
Each original parent is reconciled once, preserving one writer across its views.
Long expressions are saved as source offsets instead of repeated large JSON
strings. Reopening or rebuilding reuses the source components and their review
decisions without sending the composed expression back to the model.

Targeted resolution revisits only an uncertain unit and its declared context,
with at most two rounds and an early stop when no new supported fact appears.
Optional review may withhold facts but cannot override validation.

Only the final atomic transaction replaces the graph, provenance, saved results
and dbt catalog together. Failures, cancellation, stale input or missing required
responses retain the previous publication. Successfully processed but unsupported
semantics may publish supported facts with incomplete coverage.

See [controls and recovery](ai-analysis-controls-and-recovery.md) and the
[pipeline architecture](../architecture/ai-analysis-pipeline.md).
