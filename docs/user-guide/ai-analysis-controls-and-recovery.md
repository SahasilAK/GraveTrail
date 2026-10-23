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
outcomes** permits a small finite number within **Shared retries per batch**;
HTTP and transport retries share that allowance. Disabled/exhausted recovery needs
manual acknowledgement. A restart does not reset it. Unknown attempts and their
reservations remain in the report after a later successful response.

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
