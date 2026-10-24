# Optional AI analysis

Static parser analysis is the offline default. AI analysis independently extracts
structured lineage from actual selected file contents. SQL, SAS and dbt are
separate build families; dbt SQL, YAML, macros, Python, seeds and supplied artifacts
belong to one dbt project. Imported code is never executed.

## Build flow

1. Pin source hashes, settings, model limits and protocol. Preview makes no calls.
2. Prefer whole files. Pack coherent files within input and expected output budgets;
   split oversized files into contiguous character ranges with exact coverage.
3. Send one envelope containing actual source ranges and relevant authorized
   definitions. Validate structure, source ownership, hashes, offsets and identities.
   Static semantic approval is not required. All accepted AI facts remain inferred.
4. Persist each valid item independently. Keep good siblings when another fails.
5. Freeze the source/AI definition index after required initial extraction is resolved. At most one
   targeted completion per affected part can use newly available definitions.
6. Consolidate saved split-file operation/scope groups when needed. Oversized groups
   remain explicit unresolved boundaries; original details are retained.
7. Deterministically link saved files into a versioned NetworkX operation graph and
   adapt those same identities to existing table, column and file views.
8. Recheck freshness and publish atomically. After bounded item recovery, publish
   validated details with explicit unresolved work and incomplete coverage. Fatal
   errors, stale inputs and unaccounted missing checkpoints preserve the previous graph.

## Live progress

The active run shows stage activity, elapsed/provider waiting time and Cancel before
source inventory or preparation. Cancellation stays requested until acknowledged.
Saved and live reports share the same durable-ledger counters:

- Files selected; completed (finalized, processed extraction); partial (saved work
  without completed extraction); unfinished (no saved work). These categories do
  not claim semantic completeness.
- Parts planned across extraction, completion and consolidation; completed valid
  checkpoints; reused saved checkpoints; unresolved bounded failures; remaining
  planned work. Superseded split parents are excluded. Reuse is not skipping.
  Reused parts are a subset of completed parts; unresolved parts are a subset of
  remaining work. File completed/partial/unfinished counts partition the selection.
- Requests planned/queued/in flight/processed are batches; attempts received,
  failed and unknown are physical provider attempts. Failed attempts are not
  failed files. Received responses may still fail validation.
- Initial estimated input and request counts are planning estimates. Output
  reservations count every attempt; actual usage comes only from provider reports.
  Missing usage is Unknown, with known subtotals shown separately.

Stage bars measure saved parts against actual planned parts. Completion,
consolidation and recovery can increase totals; there is no fixed overall
percentage or invented provider progress. Recent activity is bounded to 30 events.
Polling does not prepare sources, dispatch requests or hydrate evidence.
Elapsed time measures the current worker execution; waiting time measures its
current provider wait. Durable attempt/reservation totals persist across resume.

## Inspecting request inputs and outputs

Saved and running reports have collapsible **Inputs** and **Outputs**, linked by
request and physical attempt IDs. Extraction, context completion, consolidation
and retries share the same inspector. A planned request is clearly distinguished
from an attempt that reached the dispatch boundary.

Inputs capture the actual serialized HTTPX request body at dispatch, including
prompts, source/context, model parameters and output allowance. Outputs separate
the captured provider response body from decoded results, validated part IDs,
validation errors and recovery decisions. A received response can fail validation.
Malformed responses and HTTP error bodies are retained when policy and limits
permit. Normalized results are never labelled as the raw provider response.

Capture follows **Workspace settings → Security and privacy → Store full AI
interaction context locally**, which remains off by default. Enabling it applies
to future attempts; previous bodies cannot be reconstructed. Authorization
headers, URLs and credentials are never stored. Existing credential redaction and
additional credential-field redaction apply only to the retained copy; the actual
provider request is unchanged. Redacted artifacts are explicitly marked. Captured
text is displayed as data, never executed or interpreted as instructions.

Migration 10 adds one separate DuckDB artifact table. Each input, output or decoded
artifact is limited to 4 MiB; their combined content is limited to 64 MiB per run.
Retention uses the shorter of the configured AI retention period and seven days.
Cleanup runs when the store opens and when capturing; reads refuse expired or
privacy-disabled content immediately. Cleanup leaves small reason records;
workspace/source/lineage/AI cleanup removes them with their runs. Orphaned run
artifacts are removed during lifecycle cleanup. Backups include retained artifacts
under the same workspace ownership rules. Database pages and existing backup
archives are not securely erased by logical expiry.

The existing 2 MiB provider response limit still applies. Oversized, non-UTF-8,
expired, disabled or otherwise unavailable content has an explicit **Not retained**
reason. Incomplete transfers may have no complete response. Historical runs say
**Not retained**. Nothing is silently truncated and presented as a full payload.

Collapsed sections do not load artifacts. Expand a section, select one item from
pages of 20, then expand its artifact to load 16,000 characters at a time. A
deferred download loads the complete retained, redacted artifact only when clicked.
Selection, expansion and content-page state survive refreshes. Inspection and
reopening saved results never call the provider or repeat source preparation.

## Token capacity and disclosure

Admins configure known context, input and output token limits, with endpoint/model
binding and metadata provenance. Unknown capacity requires configuration. Manual
overrides survive discovery refresh. A successful connection test proves access,
not context size.

Under **Use AI for analysis → AI budget overrides**, **Maximum output share (%)** ranges
from 10–50% and defaults to 30%. Shared-window usable capacity is context minus
`max(512, ceil(5% context))` safety and applicable separately accounted reasoning.
Output receives that percentage of usable capacity, clamped by the model output
limit. Input receives the remainder, clamped by any model input limit. At 30%,
70,000 / 200,000 / 1,000,000 shared tokens yield output maxima of
19,950 / 57,000 / 285,000 and input allowances of 46,550 / 133,000 / 665,000,
before any lower model or explicit limits. These are maxima, not generation targets.

For separate windows, the percentage applies to the independent output capacity;
input capacity minus safety remains independent of output. Reasoning included in
output is counted once. Instructions, schema, definitions, metadata, source and
provider framing all count against the displayed input allowance; protocol overhead
is not also subtracted from that allowance. Preview and dispatch use the same builder.

**Advanced token overrides** can narrow input and explicitly select output. An
explicit run output override takes precedence over a saved Custom output allowance;
otherwise that saved allowance caps the slider. Real model limits always apply.
Automatic profiles use the new model-aware recommendation, without the former
8,192-token ceiling. Saved Custom and disclosure limits are retained. The selected
share and overrides are saved with the run and cannot change during resume. Older
compatible checkpoints retain their original allocation policy.

Moving the UI slider explicitly selects this run's output allowance, overriding the
saved Custom default without editing the profile. Advanced exact overrides take
precedence. Real model limits still apply: once output reaches a declared model
maximum, both effective values can stay fixed as the share increases; the UI says
why. For 38,912 shared tokens without a lower cap, 50% gives 18,483 input and
18,483 maximum output after 1,946 safety tokens.

The controls show effective allowances, capacity provenance and clamp reasons.
Unknown shared context requires confirmed capacity. A missing optional output cap
is shown as unreported, never as verified provider support. Separate windows without
an output capacity need an explicit allowance. Dynamic routes require the existing
manual route-safe capacity confirmation; a catalog maximum does not establish that
every fallback supports it. No gateway routing is changed automatically.

Unknown tokenizers use a conservative UTF-8-byte count plus estimated framing.
Optional matching tiktoken encodings can improve text counting from the bundled checksum-pinned encoding asset;
preview never downloads encoding assets. Neither method claims an exact provider
framing count. Cached/uncached provider execution has identical domain inputs.

There is no automatic 8,000-character ceiling. Existing source/network grants still
apply. Legacy profiles require an explicit choice to use token capacity or retain
an explicit source character restriction. This choice does not grant network access.

## Recovery and limits

One physical request is active per build, using the existing shared request slots.
The optional run-wide output ceiling reserves every physical retry and resumed
attempt. Completed work is reused within the same compatible run. A new build
extracts again. There are no execution windows; every recovery pass reserves tokens in the same run ledger.

Cancellation and transient failure retain saved parts. Unknown outcomes can have
been billed. Each recovery pass has a durable shared HTTP/transport retry allowance.
Invalid items receive safe corrective feedback in smaller batches; validated siblings
are saved immediately. Failed work rotates behind other files with durable backoff.
After three unsuccessful item passes, the item is saved as unresolved with partial
coverage, never `no_operations`. Available validated lineage then publishes as
incomplete. **Retry unresolved AI work** gives only unresolved work another bounded
recovery cycle; successful checkpoints and cumulative attempt/reservation totals
survive close/reopen. Failed initial work defers the completion wave; failed initial
or completion work defers consolidation, so later repair can use one consistent
frozen context and group plan. Partial views may consequently remain unconsolidated.
Automatic unknown-outcome
retries still require the configured opt-in; disabled unknown recovery needs acknowledgement.
Source, settings, model or
prompt changes make a paused run stale. Historical snapshots and migration-9 tables
remain readable; old paused protocols require a new build. Explicit Static builds
use static results instead of restoring prior project AI results.

For slow gateways, enable **Wait until stopped** in the provider profile to disable the client response inactivity timeout, or configure separate connection and response inactivity timeouts. **Cancel AI analysis** closes the client request and prevents further retries; configured run limits still apply. Connection establishment and setup/discovery calls without a cancellation control remain bounded. A gateway can still disconnect or return an error, and closing the client does not guarantee upstream processing is cancelled.
The latter must accommodate fallback plus generation; it is not a total deadline.
Project cancellation and optional run-time limits are checked during silent waits.
Every lost response remains an unknown attempt with its output reservation, even
when a retry succeeds. See [timeout and gateway recovery settings](LLM_INTEGRATION.md#request-timeout-gateway-waiting-and-recovery).

Preview and recent request diagnostics show file/part counts, input estimate and
allowance, counting method, expected/reserved output, utilization and why packing
stopped: input, expected output, disclosure or no remaining work. Smaller eligible
items can use remaining space; failed work rotates behind fresh work. The existing
conservative estimate (256 tokens per item plus half its source/saved-detail UTF-8
bytes) remains labelled as an estimate, without runtime ratio learning.

Each initial provider payload contains only stable instructions/schema, the current
batch's source parts and relevant indexed definitions/references. Provider wire tests
check fresh messages/contents and absence of previous responses, continuation IDs or
growing summaries. Prompt caching remains compatible. Gateway-internal history or
memory is outside application control and has not been verified with live requests;
no undocumented headers or gateway settings are invented.

## Evidence and semantic quality

Source coverage measures processed ranges. It does not prove that every semantic
relationship was extracted. A valid quote/range proves traceability, not semantic
correctness. Model-reported completeness is a signal and never a runtime accuracy
oracle. Missing, ambiguous, cyclic and dynamic semantics stay explicit.

Final counters include uncertainty found while adapting results for publication.
`incomplete_files` counts each analyzed file once, even when extraction, linking
and column publication all identify gaps. `coverage_gaps` adds distinct unresolved
resource boundaries from linking and publication to that file count; it is not a
count of files alone. `unresolved` counts those resource boundaries plus extraction
messages. Retained results from files outside this run do not inflate these counts.
Successful publication does not establish semantic completeness.
`unresolved_parts` counts deferred extraction/completion/consolidation work items;
`unprocessed_files` counts files with unresolved initial extraction. A file with
saved initial facts but failed enrichment can be processed and still incomplete.

The operation graph preserves evidence, scopes, versions and dependency roles.
Duplicate writers do not establish filename-based execution order. SAS stateful
constructs retain their original details or explicit limitations. Targeted upstream
traversal excludes independent components and reports cycles and unknown ordering.

`python scripts/qualify_ai_context.py --files 1000 --family all` uses generated
independent golden fixtures and HTTP mock responses for SQL, SAS and dbt. It checks
exact table/column/file relationships, oversized-file coverage, interruption/reopen,
work reuse and sent token budgets. Tests deliberately omit a relationship from
otherwise valid JSON to prove the semantic oracle catches it.

Mock qualification proves transport, persistence and deterministic graph behavior.
Live-model precision/recall, evidence validity, tokens and cost per correct
relationship remain pending. Larger model capacity alone is not a quality claim.
No paid provider calls run as ordinary tests. SQL generation, SAS translation,
optimization, GraphRAG, vector stores and agent orchestration are outside this work.
