# AI controls and recovery

The normal build asks for Static or AI and necessary model configuration. An
optional **Run output token ceiling** limits reserved output across all physical
attempts, including retries and resume. Token capacity determines file splitting
and batching automatically. There are no character, parallel-worker, execution
window or additional-review controls in new builds.

Admins record context/input/output limits with provenance and endpoint/model
binding. For old profiles, choose token capacity or retain an explicit disclosure
restriction. This choice preserves source/network permission checks.

Cancel stops future work; saved valid parts remain. Continue reuses completed parts,
completion and consolidation work within the same run. Source/configuration/prompt
or model changes block stale continuation. A ceiling does not reset on resume.
A lost response can already have been charged. **Automatic retries of unknown
outcomes** permits a small finite number within **Shared retries per batch** in each
recovery pass. HTTP and transport retries share that allowance. A restart does not
reset a pass. Disabled unknown recovery needs manual acknowledgement. Unknown attempts and their
reservations remain in the report after a later successful response.

Missing or invalid extraction items receive concise validation feedback in smaller
batches, down to isolated items. Valid siblings are saved and are not resent.
Other pending files proceed before failed work is revisited. A pass ends with a
durable delay of 1, 2, 4, 8, 16, 32, then at most 60 seconds between passes. When
only failures remain, progress says **Waiting to retry** with the safe reason.
Cancel remains available during HTTP waiting and backoff. There is no default
elapsed-time cutoff, permanent skip policy, or publication of missing required work.
Authentication, permission/freshness, storage, irreducible request-budget problems,
and explicit run spending limits still stop work with saved progress.

**Request budget estimates** distinguishes configured output allowance from advertised
capacity and shows input utilization, expected/reserved output and packing limits.
**Recent request and extraction diagnostics** shows the latest 20 request journals;
the database retains earlier requests. Schema paths and host failure codes exclude
raw responses, source text and arbitrary provider exceptions. Split history preserves
parent/child identities and exact source ranges. Repeated truncation cannot recursively
halve a source into tiny fragments. Completion/consolidation failure retains initial facts.

For an existing OmniRoute profile, explicitly set **Response inactivity timeout**
to accommodate gateway fallback plus generation (new profiles default to 300 seconds),
**Connection timeout** (default 5 seconds), and the retry options. New profiles
default to two shared retries, including at most two unknown-outcome retries.
Old profiles keep their saved response wait and manual unknown retry policy.
Changing the profile invalidates paused-run pins; configure it before a new build.
See [full timeout/recovery behavior](../LLM_INTEGRATION.md#request-timeout-gateway-waiting-and-recovery).

Historical reports remain readable. Old hybrid/window protocols cannot resume;
start a new build. Failed or missing required work preserves the published graph.
Processed uncertainty publishes an explicitly incomplete inferred graph.
