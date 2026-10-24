# AI controls and recovery

The normal build asks for Static or AI and necessary model configuration. An
optional **Run output token ceiling** limits reserved output across all physical
attempts, including retries and resume. Token capacity determines file splitting
and batching automatically. There are no character, parallel-worker, execution
window or additional-review controls in new builds.

Expand **AI budget overrides** to choose **Maximum output share (%)**, 10–50% (default
30%). The page shows effective input/output allowances, model/route capacities,
their source and any clamps. Shared context first reserves safety and applicable
reasoning, allocates output its percentage, then gives input the remaining capacity.
For separate windows the percentage applies to output capacity only. These are
maximum allowances, not required output lengths.

**Advanced token overrides** is optional. Explicit run output overrides take
precedence over a saved Custom output allowance; otherwise that saved allowance
caps the slider. Input overrides can narrow the calculated allowance. Real model
limits and source-disclosure grants always apply. Automatic profiles no longer use
the old 8,192-output recommendation. Preview and execution share the calculation;
the chosen allocation is pinned for resume. Compatible old checkpoints keep their
original policy. Dynamic routes need manually confirmed route-safe capacities;
discovered catalog maxima alone are insufficient.

Moving the slider explicitly overrides the saved Custom output default for this
run; Advanced exact output wins if supplied. Saved profiles remain unchanged.
At a declared model output maximum, increasing the share can leave both effective
allowances fixed; the page explains that clamp. Completed offline previews are
reused while source, settings, request, profile and credential availability remain
unchanged. Analyze starts the worker without repeating that preview. While the
worker runs, progress and Cancel render before inventory and preparation controls;
your budget choices persist when those controls return.

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
Other pending files proceed before failed work is revisited, with durable backoff
between passes. After three unsuccessful item passes, work becomes explicitly
unresolved and the build publishes available validated lineage with incomplete
coverage. Failed work is never labelled `no_operations` or complete. Choose
**Retry unresolved AI work** to retry only those items; successful parts and
enrichment checkpoints are reused after close/reopen. Attempts and spending do not
reset. This action requires unchanged source/configuration and no intervening
publication by another run. Cancel remains available during HTTP waiting and backoff.
There is no default elapsed-time cutoff.
Authentication, permission/freshness, storage, irreducible request-budget problems,
and explicit run spending limits still stop work with saved progress.

**Request budget estimates** distinguishes configured output allowance from advertised
capacity and shows file/part counts, input estimate/allowance, counting method,
input utilization, expected/reserved output and why packing stopped.
**Recent request and extraction diagnostics** shows the latest 20 request journals;
the database retains earlier requests. Schema paths and host failure codes exclude
raw responses, source text and arbitrary provider exceptions. Split history preserves
parent/child identities and exact source ranges. Repeated truncation cannot recursively
halve a source into tiny fragments. Completion/consolidation failure retains initial facts.
Incomplete initial extraction defers the one completion wave; incomplete extraction
or completion defers consolidation until repair. Partial views can therefore retain
unconsolidated details. Reports distinguish unresolved work items, unprocessed files
and files with incomplete semantic coverage.

For an existing OmniRoute profile, explicitly set **Response inactivity timeout**
to accommodate gateway fallback plus generation (new profiles default to 300 seconds),
**Connection timeout** (default 5 seconds), and the retry options. New profiles
default to two shared retries, including at most two unknown-outcome retries.
Old profiles keep their saved response wait and manual unknown retry policy.
Changing the profile invalidates paused-run pins; configure it before a new build.
See [full timeout/recovery behavior](../LLM_INTEGRATION.md#request-timeout-gateway-waiting-and-recovery).

Historical reports remain readable. Old hybrid/window protocols cannot resume;
start a new build. Stale inputs, fatal errors and unaccounted missing checkpoints
preserve the published graph. Bounded failures and semantic uncertainty publish an
explicitly incomplete inferred graph with retained validated details.
