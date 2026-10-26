# LLM integration

**AI is optional. Local parser analysis is the primary, default workflow** for
lineage, column usage and supported transformations. Leave **Use AI for analysis**
unchecked to send no source to an AI provider and incur no AI token usage. A saved
provider connection does not automatically enable AI extraction.

For additional coverage in large or complex systems, optional
[AI analysis](AI_ANALYSIS.md) independently extracts inferred facts from selected source.
Selected source/context is sent to the configured provider; a local
gateway may forward it upstream. Parser and AI builds are separate choices. AI cannot ensure
that every dependency is populated correctly; inspect evidence and unresolved coverage.

Analysis → Diagnostics → Unresolved review queue derives at most 100 current SQL/SAS warning/error items.
It excludes pending/reimported sources, informational and CSV diagnostics. Suggested context
uses a containing deterministic statement or at most 40 nearby lines; users can adjust the
exact range. Request buttons are tied to the displayed content hash, which is checked again
inside the provider path before transmission, including same-host fallbacks. Previewing is
offline. Every request is explicit, sequential and subject to existing privacy/context gates.
Validated claims require a separate inferred merge; diagnostics are never automatically
declared resolved. Queue request/merge tests use synthetic HTTP payloads, not a new live pass.

The application is fully usable without an LLM. Connections & AI → Providers & routing stores multiple
profiles, task overrides, same-host ordered fallbacks and environment variable names for keys.
Setup follows endpoint, credentials, connection test/model discovery, then model selection
or manual entry and profile save. **Test connection** fetches models using the current draft
without requiring a saved profile or selected model. **Fetched models** fills the editable
model identifier; **Test model connection** optionally validates that model. Azure deployments
use manual entry and the model test.

Choose **This session only**, enter a masked **Runtime credential** under **API key**, then
**Connect for this session**; use **Environment reference (advanced)** for a named launch
variable. A session's `RuntimeConnections`
manager holds entered keys in memory and passes them directly to provider adapters through
a context-local scope; the process environment is never changed for session credentials.
**Clear runtime credentials** removes session entries. Launch variables remain read-only
and available, so clearing a session entry does not disconnect a startup-provisioned key.
Re-enter session credentials after restart unless supplied at launch. **Remember on this device**
explicitly saves an encrypted native key until deleted, using qualified Windows Credential
Manager local-machine persistence. Other OS stores remain disabled pending local-only
verification. Saved-key replacement/deletion and session disconnect/reconnect are separate
actions; exact saved references also require independent CLI/MCP launch grants.
Alternatively, **Optional: Set environment variable here** sets the actual named variable
in the running app's process environment, including before a new profile is saved. That
value is shared across its sessions until exit; the input clears on submission and no `.env`
file or permanent OS setting is written. See [secure configuration](SECURE_CONFIGURATION.md).

Session/saved references are scoped opaque `DATAFORGE_` names. Advanced environment references include `DATAFORGE_OPENAI_API_KEY`,
`DATAFORGE_ANTHROPIC_API_KEY` and `DATAFORGE_DATABRICKS_TOKEN`. Explicit legacy references
remain compatible without rewriting unrelated environment variables. Profiles persist only
validated non-secret preferences and opaque credential/environment references. Secret-bearing URL userinfo
and authentication query parameters are rejected. Entered key values are not persisted in
DuckDB, files, exports, build outputs or logs; provider-echoed known credentials are redacted
before durable result storage. Imported originals deliberately preserve exact bytes and may
themselves contain sensitive information. Protect them and the runtime home accordingly.
See [secure configuration](SECURE_CONFIGURATION.md) for the lifecycle and security boundary,
and [setup and deployment](SETUP_AND_DEPLOYMENT.md#9-llm-connection-configuration) for all
default provider variable names. The runtime manager supports expiration for callers that
register a lifetime; the current UI connects for the session without an expiration control.

External requests are disabled until enabled in Connections & AI → Privacy. Loopback endpoints are
permitted for offline use; a local gateway may itself forward requests, so configure it carefully.

Protocols: OpenAI and compatible/LM Studio/OmniRoute/OpenRouter use Chat Completions;
Anthropic uses Messages; Gemini uses generateContent; Ollama uses /api/chat;
Databricks uses /serving-endpoints/{name}/invocations; Azure uses a deployment and API version.
Discovery is supported where providers expose listing endpoints. Azure deployment discovery
requires a separate management API, so enter deployment names manually. Configure optional
temperature and JSON mode according to the model's capabilities. No automatic model guessing.

Analysis → Diagnostics → Optional AI assistance sends an explicit source range only. The full-file privacy
gate applies to remote providers; source and total profile budgets are enforced. Likely secrets
are redacted by default. A redacted quote may fail exact-evidence validation, deliberately.
No source is sent automatically during parsing. Imported instructions remain untrusted data.

Both Diagnostics panels share preparation, budgeting, evidence validation and explicit acceptance.
Responses must pass Pydantic schema, exact quote, original selection coordinates, executable
read/write/operation and resource identity checks. Known assets provide context; executable source
can establish a proposal for a resource missed by static parsing. Wrong coordinates can be rebound
only to a unique exact quote inside the selected range, retaining reported and corrected locations.
Invalid outputs are quarantined with safe structured reasons. Valid resources and relationships
can be merged explicitly in one transaction as AI-inferred, with confidence <= 0.8; never verified.
Merged claims are revalidated
on refresh and omitted after source hashes change. AI does not expand runtime macros.

Retries/fallbacks apply to connection failures, HTTP 429 and 5xx only. Fallbacks never change
recipient host. No fallback for authentication, malformed JSON, unsupported claims or privacy
errors. HTTP responses are size bounded; redirects and ambient proxy credentials are disabled.
Metadata records task/provider/model/hash/outcome/duration/tokens; full context/history is opt-in
and retention is configurable. Minimal merged claims are durable lineage evidence; retention
removes their full context/response bodies while retaining claims/provenance. Monetary cost
is not estimated without provider pricing.

AI build Inputs/Outputs use the same history opt-in. Actual dispatched bodies and
provider responses live separately from checkpoints in migration-10 artifacts,
with credential redaction, at most seven days (or shorter workspace retention),
4 MiB per artifact and 64 MiB per run. Missing or unavailable payloads have explicit
reasons. Inspection is lazy, paged and offline; [details](AI_ANALYSIS.md#inspecting-request-inputs-and-outputs).

Codex's interactive environment is used to develop this application, not as a hidden runtime API.
ChatGPT/Codex sign-in credentials are not scraped or repurposed. Databricks Genie is a distinct
query agent; it is not a generic chat endpoint in this implementation.

Protocol documentation checked during development:
- [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
- [Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create)
- [Gemini generateContent](https://ai.google.dev/api/generate-content)
- [Databricks serving query](https://docs.databricks.com/api/model-serving-query/v1/query)

Tests use HTTPX MockTransport to verify payloads, privacy, quarantine, grounding and merging.
No live provider test is claimed without a reachable configured endpoint and credentials.

## OmniRoute live verification

The development verification endpoint is `http://localhost:20128/v1`, with model route
`auto/best-reasoning`. The credential is referenced as `OMNIROUTE_API_KEY`; its value is
never stored in project files. Supply this named read-only variable through the launching
environment, or use masked session credentials in the UI. Session credentials are not
persisted and must be supplied again after restart. Do not copy a credential into a profile,
command argument, build artifact, or report.

Run the opt-in check with that route and the existing launch variable available:

```powershell
uv run python scripts/verify_llm.py --model auto/best-reasoning --output plans/LLM_LIVE_RESULTS.json
```

This uses synthetic SQL/SAS in an isolated temporary database, checks discovery, connection,
grounded claims, inferred merge, refresh and restart. It exits nonzero on any failure; it does
not scan the user's imported projects. The model route is a gateway alias and may change its
upstream model. The report records the requested route, not an independently verified model
identity. A listed model is not necessarily callable.

Compatible chat requests explicitly disable streaming. Some gateways/models return a single
Markdown JSON fence even with JSON mode requested. The application accepts that enclosing
fence only; surrounding prose, multiple blocks and non-object JSON remain invalid. Schema and
source grounding checks still apply. Provider HTTP envelopes must be JSON objects.

## Task-specific advisory results

Columns v2 returns cited direct-column suggestions, validated against complete original
parser operations and explicit unambiguous usage. Suggestions remain AI-inferred and do not
modify deterministic column reports. Code explanation v2 returns individually cited advisory
items; exact citations and listed assets are checked, not the semantic truth of model prose.
Neither task may merge lineage, and historical advisory merges are excluded from reanalysis.
Analysis → Diagnostics → Optional AI assistance → Saved AI result reopens retained results without an active
provider profile. Changed-source results display a warning and retain their original quote/hash.
Advisory JSON downloads include provenance. The existing retention policy applies.

## Resource controls

Workspace settings → Resources configures1–4 concurrent requests per workspace (also maximum8 across
this app process) and statement chunk size. Assistance, model connection tests and discovery
share admission. Busy calls refuse rather than queue. The assistance chunk preview is offline:
choose one complete statement/SAS block chunk and explicitly request it. No next chunk runs
automatically. Unknown or interactive SAS procedures retain context through QUIT; oversized
units require a larger budget or different selection. Source/profile budgets still apply.
These shared admission limits are not project-build parallelism controls: each project
build has one active physical request. Cancellation callbacks stop retries and response
processing cooperatively. Project builds also
monitor silent network waits; see [gateway waiting and recovery](#request-timeout-gateway-waiting-and-recovery).
Local cancellation does not prove upstream processing stopped.

Historical fixed-route verification on2026-10-15 passed with cx/gpt-5.6-luna-low, including
grounded SQL/SAS inferred merge and restart; this does not establish current auto-route acceptance.

Current user testing policy: use OmniRoute model `auto/best-reasoning`; the live-check script
defaults accordingly. This supersedes the earlier literal `auto` instruction. Preserve
quarantine for invalid output; do not substitute another route or weaken validation to force
success. Model discovery alone does not prove completion or task-schema compliance.

Historical inspection on2026-10-16: discovery966 advertises `auto/best-reasoning` and omits literal
`auto`. Earlier connection/SQL assistance/merge pass. A fresh SAS response returns HTTP200,
valid fields, exact source evidence and one enclosing JSON fence; existing processing accepts
it unchanged. The old SAS schema failure was not reproduced. A full-workflow probe then fails
at connection with HTTP503: `Maximum combo retry limit reached`,28 attempted candidates from
a pool of787, `terminalReason=max_attempts_exceeded`. This is gateway candidate exhaustion,
which output normalization cannot repair. Individual upstream failure reasons remain unknown.
No preprocessing/prompt/schema change was made. Further live calls stopped per user request.
The command writes safe metadata to the ignored local `plans/LLM_LIVE_RESULTS.json`,
without raw output or credentials.
That dated attempt left the full live gate open.

Current bounded acceptance on 2026-10-17 passed discovery (915 models), connection, synthetic SQL and SAS exact-quote validation, inferred merge, graph refresh and owner reopen in 33.8 seconds. It used `http://localhost:20128/v1`, `auto/best-reasoning` and the existing read-only `OMNIROUTE_API_KEY` launch reference. No fixed route or validation change was used. See [provider verification guidance](TESTING.md); earlier failures remain historical evidence, and this result does not promise continuing provider availability.

## Project analysis

[AI project analysis](AI_ANALYSIS.md) offers `parser` and `ai` builds through Analysis,
CLI and MCP. Parser mode stays offline by default. AI uses the `project_lineage` route
and protocol 5 file extraction, independently of parser lineage and manual assistance.
It validates structure, exact source ownership/hashes/ranges and resource identities;
accepted AI facts remain inferred and do not require parser semantic approval. Parser
results do not fill AI omissions. Hybrid comparison and additional review are unavailable
for new builds.

Preview discloses selected files and project closure, including dbt configuration/macros,
and counts the complete request envelope against known token capacity and disclosure
limits. Whole files are preferred; oversized files use contiguous exact ranges. Valid
items persist independently, followed by at most one frozen-context completion wave,
bounded split-file consolidation and deterministic linking of saved operations. Requests
run sequentially within a build, with no execution windows or file-count/parallel-request
controls. Each physical attempt reserves output against the same durable run ledger.

Remote cumulative disclosure still requires complete-source permission. Freshness,
source/privacy and authorization are rechecked before dispatch. Truncated responses enter
bounded item recovery, and unknown usage remains unknown. After bounded recovery,
validated work can publish with explicit incomplete coverage; unresolved items can be
retried while reusing successes. Fatal errors and stale inputs retain the prior graph.
Normal preview, settings reads, browsing and export send no requests. See
[token capacity and disclosure](AI_ANALYSIS.md#token-capacity-and-disclosure) and
[AI controls/recovery](user-guide/ai-analysis-controls-and-recovery.md).

Project parts/definitions preserve exact original text. The manual-assistance source
redaction step does not sanitize these outgoing project payloads; captured copies and
responses have separate credential redaction. Project packing uses known model token
capacity plus any explicit profile source-character restriction, rather than the legacy
workspace manual-chunk character setting. See
[secure disclosure](SECURE_CONFIGURATION.md#project-ai-disclosure-and-revocation).

## Request timeout, gateway waiting and recovery

In **Connections & AI / Providers & routing / Advanced request options**, set
**Connection timeout (seconds)** independently from **Response inactivity timeout (seconds)**.
Connection wait defaults to 5 seconds (0.05-60 allowed). Read inactivity accepts
0.05-3,600 seconds and measures the wait between response data, not a total deadline.
Allow time for gateway fallback plus generation. A healthy app-to-gateway connection
stays open during that wait. The app does not know which upstream is active.
See [HTTPX timeouts](https://www.python-httpx.org/advanced/timeouts/).

Existing profiles keep their saved `timeout` as the fallback read inactivity value
(historical default 30 seconds) and write timeout. New `read_timeout` overrides the
read wait without overwriting that legacy value. `connect_timeout` defaults to 5.
Existing `unknown_retries` defaults to zero, preserving manual acknowledgement.
New OmniRoute profiles default to read 300 seconds, connect 5 seconds, two shared
retries and two permitted unknown retries. Explicit creation values take precedence.
Existing OmniRoute users must set these controls explicitly and save. Profile changes
invalidate paused-run pins: configure before a new build, or use the existing report's
manual acknowledgement without changing its pinned profile.

**Shared retries per batch** excludes the initial attempt: two means at most three
physical sends for an identical unfinished batch in one recovery pass. HTTP
429/5xx, pre-send and permitted unknown retries share it; unknown retries are a
subset cap. Restart does not renew a pass. After a recoverable failure, the durable
extraction queue processes other work and waits before another pass. Invalid items
receive safe field/code feedback in smaller batches. Every physical attempt still
counts toward optional run-wide attempt, reserved-output and elapsed-time ceilings;
those limits never reset. Successfully checkpointed parts are not resent.

Only connection-establishment/pool failures with pre-send evidence are safe to retry.
Read/write, remote protocol and proxy errors may already have been processed or billed;
automatic recovery requires the configured unknown policy. Authentication and credit
or daily-quota exhaustion remain blockers. Invalid provider responses enter item
recovery with backoff and diagnostics rather than an identical immediate loop. Bounded Retry-After
and backoff remain for retryable HTTP failures. No idempotency header or gateway
request-status lookup support is assumed.

Each physical attempt is journaled before dispatch with its output reservation.
Unknown attempts remain unknown after later success, and unknown usage is never
represented as proven zero. Safe diagnostics include category, durable attempt number,
elapsed attempt time, effective timeouts, outcome, retry/exhaustion decision and HTTP
status when available. Connection diagnostics contain no exception text, headers,
credentials or source. App interruption can leave elapsed time unknown.

Project builds monitor silent sockets through cancellable HTTPX I/O while buffering
ordinary JSON; no model streaming/SSE is introduced. Cancellation, authorization,
freshness and optional run-time limits are checked while waiting and during backoff.
The active app-side request closes before another starts. That does not prove upstream
generation or billing stopped. Callers without check/cancellation callbacks still use
the configured HTTP timeouts. Worker progress refreshes every two seconds; report
messages describe the gateway connection, never an unreported upstream provider switch.

Item recovery is bounded to three unsuccessful passes, with Cancel available during
requests and backoff. Persistently failing items are saved as unresolved/partial,
and available validated lineage publishes with explicit incomplete coverage.
Later retry sends only unresolved work, reusing successful checkpoints and keeping
cumulative attempts/reservations. Completion/consolidation uses the same recovery
path while keeping original facts durable. Truncation first reduces batch width; an isolated source
part can split once with exact cores and bounded disclosed overlap. Irreducible
request sizes require a budget/configuration change. See [controls and recovery](user-guide/ai-analysis-controls-and-recovery.md).

## Protocol 5 file extraction (2026-10-23)

New project builds use independent AI extraction from exact file parts, token-budgeted
items envelopes, persisted file records, one frozen-context completion wave, bounded
file consolidation and deterministic operation-graph publication. Static analysis and
manual assistance remain independent. Legacy hybrid/review protocols cannot resume as
new protocol 5 builds. See [AI analysis](AI_ANALYSIS.md) and
[pipeline architecture](architecture/ai-analysis-pipeline.md).

The 2026-10-24 allocation update replaces the automatic 8,192-output ceiling with
a pinned 10–50% output-share preference (default 30%). Shared windows reserve safety
and applicable reasoning once, then allocate output and remaining input within real
model limits. Separate windows keep input independent. Explicit run output overrides
take precedence over saved Custom output allowances; otherwise Custom caps the share.
Dynamic routes require existing manual route-safe capacity confirmation. Preview and
dispatch count the same complete request body plus estimated framing. Provider maximum
parameters remain protocol-specific: OpenAI `max_completion_tokens`, compatible
Chat Completions/Anthropic `max_tokens`, Ollama `num_predict`, Gemini `maxOutputTokens`.

Initial calls use fresh system/user messages or equivalent provider contents, current
source parts and relevant indexed definitions only. There are no prior extraction
responses, continuation IDs or growing summaries. Local mock wire tests cover these
payloads. Prefix caching remains allowed. Application payload independence does not
establish whether a gateway adds internal history: no live gateway-memory verification
was performed, no undocumented headers were added and routing was not changed.

Bounded partial publication supersedes earlier indefinite pending recovery. Required
initial failures defer completion; initial/completion failures defer consolidation
until repair, preserving one frozen wave and stable saved group inputs. Unknown-outcome
acknowledgement, authorization, freshness, Wait until stopped, responsive cancellation
and optional spending ceilings remain enforced.

Offline qualification uses nonempty independent SQL/SAS/dbt golden transport fixtures. The oracle scores table, column and file relationships separately and catches semantic omissions despite complete model JSON. Mock results do not establish live-model accuracy; live precision/recall and cost evaluation remain pending. Ordinary tests spend no provider credits.

## Optional live provider reasoning

**Current status (2026-10-24): live streaming is disabled for analysis.** Planning
and dispatch use ordinary `stream: false` JSON requests with no `stream_options`.
The reasoning parser, transient buffer and UI remain in place but receive no live
reasoning from new analysis requests. The normal absence caption is shown.
Durable part saving, truncation recovery, eligible response replay and counters
remain enabled, including local decoding of eligible historical SSE artifacts.

Streaming must not be re-enabled until a later plan separates bounded wire overhead
from decoded-answer size and qualifies realistically sized responses. The old 2 MiB
wire cap aborts token-by-token SSE even when the actual answer is small. The following
paragraphs describe the retained, inactive implementation.

The LM Studio analysis path requests `stream: true` and
`stream_options.include_usage: true` at the existing OpenAI-compatible Chat
Completions endpoint. It consumes SSE incrementally inside cancellable HTTPX I/O;
ordinary JSON responses still use the existing decoder. Other provider paths retain
their existing behavior. Request sizing uses the same streaming body as dispatch.

Only explicit `choices[].delta.reasoning` or `reasoning_content` fields supply
reasoning; answer `delta.content` stays separate for extraction decoding. LM Studio
[documents the reasoning field](https://lmstudio.ai/docs/developer/api-changelog)
and [Chat Completions streaming option](https://lmstudio.ai/docs/developer/openai-compat/chat-completions).
These are different from the named events on its
[native REST endpoint](https://lmstudio.ai/docs/developer/rest/streaming-events).
The installed model/template must expose reasoning; no thinking option is enabled
and no extra request obtains or summarizes it. The
[Qwen3.5-4B model card](https://huggingface.co/Qwen/Qwen3.5-4B) does not establish
what the user's installed LM Studio template emits. That live behavior remains
unverified while the earlier HTTP 400 is unresolved.

A narrowly scoped Streamlit fragment refreshes approximately every 500ms while the
job is active. This is incremental polling, not browser push. Non-whitespace reasoning
appears in a collapsible **Model thinking** panel with a fixed 300px scroll body,
current attempt ID and streaming/finished/interrupted status. Scrolling up pauses
auto-follow; **Jump to latest** resumes it. Expansion and scroll state survive panel
updates. Otherwise the small caption reads exactly **No thinking/reasoning available**.
Cancel remains in the independent job controls. Timed reasoning updates stop after
termination; collapsing never cancels or sends another request.

The thread-safe buffer is scoped to workspace/run/attempt, resets for a new attempt,
and is cleared on job disposal. It displays at most 64 KiB UTF-8, trims at character
boundaries, and labels removed history. Extra bounded transient context supports
credential redaction, including values split across chunks; unfinished tails are
withheld. Content is rendered with `textContent`, never executable markup. Tokens
are not written to the job journal or database one by one.

Optional retained SSE wire output uses the existing history artifact and is labeled
`openai_chat_sse`. Replay reconstructs answer, finish reason and reported usage through
the same pure decoder and requires both finish evidence and `[DONE]`. A disconnected
stream stays incomplete/unknown and is never automatically resent as ordinary JSON.
Reasoning alone proves neither response persistence nor extraction success. When a
credential spans SSE events, the wire artifact is omitted if semantic redaction would
change its reconstructed answer or reasoning; no hidden unredacted copy is kept.
History, retention and size limits still apply. Displaying already-generated reasoning
adds no generation tokens; separately enabling model thinking can increase tokens
and latency. Mock/synthetic verification does not establish model accuracy.
