# AI project analysis

AI project analysis adds table lineage, direct column usage and column transformations to the main **Analysis** workflow. Local parser analysis remains the default and needs no provider. Use hybrid analysis first; AI-generated analysis is experimental and has no qualified live precision claim.

## Choose a build

| Analysis controls | Mode | Published SQL/SAS facts |
| --- | --- | --- |
| **Use AI for analysis** off | `parser` | Existing local parsing and still-valid saved inferred support; no new AI requests |
| AI on, **Compare with parser** on | `hybrid` | Parser facts plus independently extracted, deterministically validated AI facts |
| AI on, comparison off | `ai` | Validated AI facts; unmatched parser facts are shown as omissions rather than silently published |

CSV continues to supply local schema metadata. **Additional AI review** is optional. Review can withhold a candidate, but cannot make an unsupported claim publishable. AI additions remain **inferred**, with the compatibility confidence ceiling of 0.8. That number is display metadata, not a measured probability.

Review receives compact candidates and the original unit once. Preview reserves 2,000 characters for candidates. Candidates beyond that bound stay unresolved with `additional_ai_review_context_limit`; they never receive implied approval. This keeps the optional review within the previewed request and call budget.

1. Import SQL/SAS source files and configure a provider under **Connections & AI**.
2. Open **Analysis**, select files, and enable **Use AI for analysis**. Keep **Compare with parser** selected for a hybrid build.
3. Inspect the offline preview: selected files, complete units, disclosure, configured routes, context failures, retry/fallback call ceiling and output-token reservations. Preview does not test connections or send source.
4. Start the explicit AI analysis action. Inspect the completed comparison/report and original evidence; unresolved and rejected candidates do not become accepted dependencies.
5. Use the job cancellation control when needed. Cancellation, stale source/settings, exhausted budgets and failed required units retain the previously committed graph.

The five existing manual assistance tasks remain available in Diagnostics, including their separate explicit inferred merge workflow. Project extraction/review tasks require host-issued units and candidates and do not appear as manual range tasks.

## What happens to the source

```mermaid
flowchart TD
    A[Explicit analysis action] --> B[Snapshot source hashes and settings]
    B --> C[Offline complete-unit and disclosure preview]
    C --> D[Local extraction]
    C --> E[AI extraction from original units]
    D --> F[Deterministic evidence and semantic checks]
    E --> F
    F --> G[Comparison by original operation]
    G --> H[Optional bounded AI review]
    G --> I[Final freshness and authorization checks]
    H --> I
    I --> J[Atomic publication of accepted facts]
    F --> K[Rejected and unresolved report]
```

Units retain original character offsets and lines, including multiple statements on one line. SQL statements and SAS DATA/PROC/macro blocks stay whole. An oversized indivisible unit blocks the run instead of being truncated. Project planning can exceed 50 units; the existing manual selection limit remains 50 chunks.

Each request receives its original unit, relevant selected-source declarations and safe configured context. Extraction does not receive parser relationship or transformation answers. The declaration catalog includes provenance and marks conflicts unknown. Unselected source is not implicitly sent as extra context. Static schemas and structural parsing are shared inputs, so independent extraction is not independent proof.

A remote project run can transmit a complete selected file across several chunks. It requires both **external requests** and **complete source** permission. A loopback gateway such as OmniRoute may forward data to another provider. Source, comments and embedded instructions are untrusted data and are never executed. Session credentials remain in memory; credentials and provider echoes are redacted through the existing connection boundary.

## Context and run budgets

The complete request counts toward both the profile `context_chars` and workspace Privacy `max_context_chars` limits: system prompt, JSON encoding, source, relevant catalog and response schema. The transmitted schema omits nonvalidating annotations and JSON whitespace, so a short ordinary unit fits the default limits. Larger source/catalog combinations can still exceed them. If preview reports `complete_prompt_exceeds_context_budget`, deliberately adjust both limits under **Connections & AI**, or reduce scope/context where possible. The application does not loosen privacy settings automatically. Raising a character limit is not an exact token estimate.

| Run ceiling | Default | Allowed range |
| --- | --- | --- |
| Physical provider attempts | 200 | 1–2000 |
| Reserved output tokens | 200000 | 1000–2000000 |
| Cooperative execution seconds | 1800 | 30–14400 |

Every extraction/review/retry/fallback attempt reserves its configured maximum output allocation before dispatch and rechecks current authorization, source identity, cancellation and remaining budget. Unknown usage keeps that conservative reservation. Reported token counts remain provider metadata; absent usage is unknown. No monetary estimate is invented.

The deadline starts when work enters execution, excluding queue time. HTTP timeouts are limited by remaining time; checks also run between received chunks, stages and immediately before publication. A blocked socket/parser cannot always be preempted exactly, so cancellation or deadline reporting may return later. An already sent request may have incurred usage.

## Validation, comparison and reuse

Every candidate must pass strict bounded contracts and cite the complete immutable original unit with exact hash, offsets, lines and quote. The request supplies an exact citation template. Columns also require exact expression spans, scope, branch/version and dependency roles. The host can locate omitted expression offsets only when the exact expression occurs once in the unit; ambiguous, missing or explicitly wrong spans are rejected. SQL projections include their original aliases; assignment expressions follow the task protocol. A real fragment that omits a JOIN does not establish ownership. Names in comments, literals, unused CTEs, unknown runtime macros and unknown wildcard outputs cannot manufacture dependencies.

Supported parser structure verifies ordinary claims. Separately bounded static SQL UPDATE/MERGE assignment verifiers cover a small tested gap subset. Unsupported branches, ownership or semantics remain unresolved. Join, filter, partition, order and rowset effects remain distinct from output value inputs. Additional AI agreement cannot override this boundary.

Hybrid comparison preserves parser-only facts and reports omissions. AI-only candidates publish only after deterministic checks. Corroboration of one original operation remains one writer. Conflicting/uncertain support stays inspectable; confident traversal stops at unresolved boundaries and unknown writer order.

Accepted project facts and minimal provenance are durable and can be reused by offline parser rebuilds. Selected-file runs preserve compatible unselected contributions. AI cache reuse requires the same source/context, job/settings, route/model, prompt/schema and validation identity; current source and authorization are checked again. Cache hits make zero new requests and do not turn historical usage into zero. **Refresh AI** explicitly bypasses AI extraction reuse; forcing local parser work alone does not authorize AI requests.

Preserved contributions carry their original declaration dependencies into later selected-file snapshots. Changing a declaration invalidates dependent offline reuse even if the most recent run analyzed another file.

Extraction, validation and comparison stage before publication. Final source/settings/revision checks and fact/support materialization commit together. Failed, cancelled or stale runs do not replace the existing graph. Failed billable work does not restart automatically after a process restart.

## Evidence and current limits

Synthetic SQL/SAS holdout labels and mock HTTP tests exercise exact evidence, deceptive negatives, roles, abstention, transport and orchestration. They do not measure a live model's precision. There is no claim of universal SQL/SAS coverage, inferred runtime execution order or a complete database schema.

A bounded development smoke on 2026-10-20 used loopback OmniRoute `auto/best-reasoning` on two synthetic SQL units. Both committed with known token usage: seven accepted claims, no rejected/unresolved candidates and one AI-only UPDATE derivation. Earlier development attempts exposed offset/protocol errors and informed prompt changes. This is a functionality check after tuning, not an independent precision evaluation or SAS qualification.

The live qualification targets remain unestablished: at least 99% accepted table-edge precision and 98% accepted value-column dependency precision, reported separately by language with coverage and sample sizes. The intended minimum is 100 accepted table predictions and 200 accepted value-dependency predictions across at least 20 scripts per language. No provider calls or private-project transmission are part of normal CI or documentation builds. See [testing](TESTING.md), [provider integration](LLM_INTEGRATION.md), [CLI](CLI_GUIDE.md) and [MCP](MCP_INTEGRATION.md).
