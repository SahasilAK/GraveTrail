# AI controls, budgets and recovery

Enabling **Use AI for analysis** immediately exposes **Maximum files per request**
and **Maximum parallel requests**. Empty values mean Auto; custom values are maxima.

| Control | Meaning |
| --- | --- |
| Files per request: Auto or 1–100 | Distinct files allowed in a request. Requests remain capped at 8 complete items; multiple units may come from one file. |
| Parallel requests: Auto or 1–4 | Maximum outstanding provider requests, constrained further by workspace concurrency, process slots and quota feedback. |
| Maximum source/context characters per request: Auto or 500–2,000,000 | Optional under AI request budget. Auto uses saved workspace/profile character allowances and splits work to fit. An explicit value replaces those character allowances for this build only; it cannot override model token capacity or source permissions. |
| Automatically continue execution windows | Continue an active authorized build across window boundaries; disable for explicit manual continuation. |
| Execution attempts/output/seconds | Per-window ceilings: at most 2,000 attempts, 2,000,000 reserved output tokens and 14,400 active seconds. |
| Project attempts/output/active seconds | A finite lifetime allowance calculated before Start, or an explicitly lower/custom allowance. It persists across rollover and resume. |

Auto grouping begins with one item and can grow through 2, 4 and 8 after three
clean batches. Context/disclosure capacity and expected output can keep a request
smaller. Size/truncation failures shrink pending groups; good item checkpoints stay.
Semantic uncertainty alone is not evidence that a larger group is safe.

The collapsed **Source files and request sizes** table shows original file characters,
planned tasks, maximum complete-request characters, maximum disclosed source/context
characters, effective character allowance, estimated input tokens and known model input
allowance. Click a heading to sort ascending/descending. Values describe planned
single-task requests; the scheduler also checks any combined batch before sending it.
Blank model token allowances mean unknown capacity, not unlimited capacity.

Instructions and response schemas count against the model's token capacity, not the
source-character allowance. A 625-character SQL statement can therefore produce a
request exceeding 8,000 total characters without violating an 8,000 source allowance.
Large source or context is processed through bounded tasks automatically. Partial
source/context views preserve the original locally and cannot certify complete coverage.
Long expressions can be gathered as reviewed dependency components and combined
locally after complete source coverage and validation. The final lineage build
does not need one model request containing the entire file or project.

The table's maxima include provisional review headroom before extraction. Actual
review payloads are checked again after the candidates exist. Original file size,
source/context allowance and full prompt size describe different quantities.

## Why 12,476 attempts can coexist with a 2,000 limit

12,476 is a project-wide conservative extraction/retry/fallback estimate. 2,000 is
one execution window's ceiling. The preview labels these separately, alongside a
finite project allowance for bounded additional work. A larger build does not
require entering 12,476 into a field capped at 2,000.

Reserved output is an authorization ceiling, not measured billing. Actual provider
usage is reported separately, and remains unknown when a provider omits it or a
response is lost. No workflow can remove provider charges, credit exhaustion or
the context/accuracy limitations of a less capable model.

## Provider limits

Context/input/output capacity controls what fits in a request. RPM, input/output
token quotas, daily quotas and account credits control admission over time.
Neither RPM nor a model's context size directly defines parallel file count.

The scheduler observes allowlisted quota/reset headers and honors Retry-After
seconds or dates. Unknown quotas remain unknown. Temporary failures use bounded
retries and backoff; waits are cancellable. The provider's other clients may consume
the same quota, so feedback is advisory. An optional **Shared provider quota group**
under provider settings coordinates profiles using the same account/project quota;
an empty group conservatively coordinates by endpoint.

## Recover from a pause

| State | Action |
| --- | --- |
| Waiting for provider | Leave the active job running or cancel it. Provider waits do not enlarge the lifetime allowance. |
| Execution window reached, automatic continuation enabled | The active build advances to another window automatically. |
| Manual continuation / restart / cancellation | Choose Continue; completed unit/review checkpoints are retained. |
| Project allowance reached | Start a compatible new build with a larger explicitly selected allowance; unchanged validated unit checkpoints are reused unless Refresh is selected. Resume never silently enlarges the saved lifetime allowance. |
| Daily quota or credits exhausted | Restore provider capacity before resuming. Retrying cannot create quota or credit. |
| Unknown dispatched outcome | Inspect the possible duplicate-charge notice, then explicitly enable retry if desired. |
| Source/settings/route changed | Start a fresh compatible build; the old pinned build cannot publish stale facts. |
| Incomplete semantic coverage | Inspect unresolved evidence and use a suitable model/context. Supported facts remain distinct from missing coverage. |

Restart never starts paid work by itself. A response received just before a crash
but not checkpointed is treated conservatively. There is no exactly-once billing
guarantee. Keep the prior graph available while required work is outstanding.

The same policy fields are available in [CLI](../CLI_GUIDE.md) and
[MCP](../MCP_INTEGRATION.md); source/network permissions are still required.
