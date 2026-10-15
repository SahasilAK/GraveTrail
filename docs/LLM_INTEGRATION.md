# LLM integration

Builder's unresolved review queue derives at most 100 current SQL/SAS warning/error items.
It excludes pending/reimported sources, informational and CSV diagnostics. Suggested context
uses a containing deterministic statement or at most 40 nearby lines; users can adjust the
exact range. Request buttons are tied to the displayed content hash, which is checked again
inside the provider path before transmission, including same-host fallbacks. Previewing is
offline. Every request is explicit, sequential and subject to existing privacy/context gates.
Validated claims require a separate inferred merge; diagnostics are never automatically
declared resolved. Queue request/merge tests use synthetic HTTP payloads, not a new live pass.

The application is fully usable without an LLM. Settings → LLM providers stores multiple
profiles, task overrides, same-host ordered fallbacks and environment variable names for keys.
Set the actual variable before startup. Neither profile exports nor logs store key values.
External requests are disabled until enabled in Security and privacy. Loopback endpoints are
permitted for offline use; a local gateway may itself forward requests, so configure it carefully.

Protocols: OpenAI and compatible/LM Studio/OmniRoute/OpenRouter use Chat Completions;
Anthropic uses Messages; Gemini uses generateContent; Ollama uses /api/chat;
Databricks uses /serving-endpoints/{name}/invocations; Azure uses a deployment and API version.
Discovery is supported where providers expose listing endpoints. Azure deployment discovery
requires a separate management API, so enter deployment names manually. Configure optional
temperature and JSON mode according to the model's capabilities. No automatic model guessing.

Builder → Optional AI assistance sends an explicit source range only. The full-file privacy
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

The configured local test gateway is `http://localhost:20128/v1`. Its credential is referenced
as `OMNIROUTE_API_KEY`; its value is never stored in project files. On this Windows machine the
user explicitly requested remembering the credential, so it is a Windows user environment
variable. Existing terminals and app processes need the variable injected or a fresh launch
after their parent environment refreshes. `OMNIROUTE_BASE_URL` stores the non-secret endpoint.

Run an opt-in check with an available model identifier:

```powershell
$env:OMNIROUTE_API_KEY = [Environment]::GetEnvironmentVariable('OMNIROUTE_API_KEY', 'User')
uv run python scripts/verify_llm.py --model auto/best-fast --output plans/LLM_LIVE_RESULTS.json
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
