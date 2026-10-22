# LLM integration

**AI is optional. Local parser analysis is the primary, default workflow** for
lineage, column usage and supported transformations. Leave **Use AI for analysis**
unchecked to send no source to an AI provider and incur no AI token usage. A saved
provider connection does not automatically enable AI extraction.

For additional coverage in large or complex systems, optional
[AI + parser (hybrid) analysis](AI_ANALYSIS.md) compares local facts with validated
AI proposals. Selected source/context is sent to the configured provider; a local
gateway may forward it upstream. Both capabilities are built in. AI cannot ensure
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

Enter a masked **Runtime credential** under **Session-only credential (optional)** and choose **Connect for this
session**, or provision the named variable before startup. A session's `RuntimeConnections`
manager holds entered keys in memory and passes them directly to provider adapters through
a context-local scope; the process environment is never changed for session credentials.
**Clear runtime credentials** removes session entries. Launch variables remain read-only
and available, so clearing a session entry does not disconnect a startup-provisioned key.
Re-enter credentials in a fresh session/restart unless supplied at launch.
Alternatively, **Optional: Set environment variable here** sets the actual named variable
in the running app's process environment, including before a new profile is saved. That
value is shared across its sessions until exit; the input clears on submission and no `.env`
file or permanent OS setting is written. See [secure configuration](SECURE_CONFIGURATION.md).

New provider references default to `DATAFORGE_` names, such as `DATAFORGE_OPENAI_API_KEY`,
`DATAFORGE_ANTHROPIC_API_KEY` and `DATAFORGE_DATABRICKS_TOKEN`. Explicit legacy references
remain compatible without rewriting unrelated environment variables. Profiles persist only
validated non-secret preferences and credential variable names. Secret-bearing URL userinfo
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

Responses must pass Pydantic schema, known-asset, exact quote, original line range, and explicit
read/write syntax checks. Invalid outputs are quarantined. Valid output can be merged explicitly
as inferred relationships at confidence <= 0.8; never verified. Merged claims are revalidated
on refresh and omitted after source hashes change. AI does not expand runtime macros.

Retries/fallbacks apply to connection failures, HTTP 429 and 5xx only. Fallbacks never change
recipient host. No fallback for authentication, malformed JSON, unsupported claims or privacy
errors. HTTP responses are size bounded; redirects and ambient proxy credentials are disabled.
Metadata records task/provider/model/hash/outcome/duration/tokens; full context/history is opt-in
and retention is configurable. Minimal merged claims are durable lineage evidence; retention
removes their full context/response bodies while retaining claims/provenance. Monetary cost
is not estimated without provider pricing.

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
Cancellation callbacks stop retries and response processing cooperatively; blocking network
waits finish within their configured timeout. There is no preemptive HTTP cancellation claim.

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

[AI project analysis](AI_ANALYSIS.md) adds explicit `hybrid` and experimental `ai` builds through Analysis, CLI and MCP. Parser mode stays offline by default. Project tasks `project_lineage` and `lineage_review` route independently of the five manual tasks and use strict canonical contracts with protocol v2 evidence references and version 3 prompts. Each physical HTTP retry/fallback rechecks current source/privacy/authorization and reserves output tokens. Truncated output is quarantined even if its JSON appears valid and empty; absent usage remains unknown.

Remote project builds require complete-source permission for cumulative chunk disclosure. Preview counts the entire system/JSON/catalog/schema envelope against profile and workspace context limits; the complete envelope can exceed configured allowances. Selected-model capability discovery, Automatic/Custom controls and explicit calculated context remedies are described in [AI project analysis](AI_ANALYSIS.md#context-and-run-budgets). Compact transmitted schemas retain all validation rules; large projects automatically roll over bounded execution windows within a frozen finite project allowance, reusing completed extraction/review checkpoints. Oversized requests can use validated independent projection groups or static PROC SQL statement boundaries; host validation still uses original source. Review sizing is provisional before extraction and exact for saved pending batches. Larger indivisible source/catalog combinations may still need an explicit allowance change. Normal preview, settings reads, browsing and export send zero requests. Source-backed candidates still need deterministic semantic acceptance; reviewer agreement cannot promote unsupported claims. These project-build checks have mock transport evidence, not a qualified live precision result.

## Request timeout and waiting time

Under **Connections & AI → Providers & routing → Advanced request options**, set **Request timeout (seconds)** from **1 to 3,600 seconds (one hour)** and choose **Save provider profile**. Existing saved values and the 30-second default remain unchanged. This controls the HTTP wait timeout; a provider or gateway may impose its own shorter limits.

For project analysis, the separate execution time budget still bounds each request by the time remaining. Automatic planning includes the configured timeout; a Custom overall time budget can shorten the available wait. No timeout setting grants more provider attempts or source access.

The Analysis progress panel refreshes every two seconds, showing total elapsed execution time and the elapsed **Waiting** time for an extraction/review response. Validation and publication have separate stage labels; queued work is labelled separately. Worker heartbeats keep a pending job live without resetting its timers. Completed, failed, cancelled or interrupted jobs stop counting elapsed time. Waiting indicates a pending request, not proof that an upstream model is making progress. Manual assistance, diagnostic review and connection/model checks also show native elapsed-time spinners.

Cancellation remains cooperative. A blocked HTTP wait can return later, and cancelling locally does not prove that upstream processing or billing stopped. Legacy job journals without start timestamps remain readable. No source or credentials are added to timer metadata.

Provider quota feedback, files/request and parallel-request controls are described in [AI controls and recovery](user-guide/ai-analysis-controls-and-recovery.md). Model context metadata and account/project RPM/token quotas remain separate. Optional provider quota groups coordinate profiles; credentials are never quota identifiers.

Project-wide AI analysis automatically fits SQL/SAS/dbt using complete units, projection groups and exact source/context views. The optional per-build source/context character allowance is separate from complete-envelope model token capacity. Dependency components and their review decisions are checkpointed, composed and validated locally before graph linking; there is no final whole-project model call. The collapsed sizing table explains each file and maximum planned request. See [AI controls and recovery](user-guide/ai-analysis-controls-and-recovery.md) and the [complete flow](user-guide/ai-analysis-flow.md).
