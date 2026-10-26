# Secure runtime configuration

Credentials are retained only for the active runtime and are not saved in application files
or databases. They may need to be re-entered when the application restarts.

Connections & AI → Providers & routing supports a masked credential input, session connection and clear
action. Provider configuration is saved only on **Save provider profile**; this explicitly
stores nonsecret preferences and the environment variable name, never its value. URLs with
userinfo, query parameters or fragments are rejected. Keep sensitive endpoint identifiers
out of saved profiles. Newly entered credential names must start with `DATAFORGE_`.

Provider setup follows **API base URL → Credentials → Test connection → Model → Save provider
profile**. It works for new profiles before saving: **Test connection** checks the current
endpoint and credentials and fetches its available models. Select one under **Fetched models**
to fill the editable model field, or type an identifier manually. **Discover models** refreshes
the list; changing the endpoint, credential reference or authentication discards old choices.
**Test model connection** optionally checks the entered model. Azure deployments require manual
entry because listing them uses a separate management API. External endpoints still require
the Privacy permission; opening setup never sends a request.

To set an actual environment variable from the UI, enter a credential variable name,
open **Optional: Set environment variable here**, enter the masked
value and press **Set environment variable**. For example, an OmniRoute profile can set
`DATAFORGE_OMNIROUTE_API_KEY`. This writes to the running app's `os.environ`, available to
its sessions and future child processes until the app stops. It does not write a `.env`
file, OS user/system settings, saved profiles, databases or logs. It cannot modify the
parent shell or another running process. The input clears after success or failure;
environment values are read when needed without caching copies in session state. Streamlit
necessarily handles the submitted input transiently before the callback clears it.
Setting a variable also clears this session's override for that name so the new value is used.

Use `DATAFORGE_OPENAI_API_KEY`, `DATAFORGE_ANTHROPIC_API_KEY`,
`DATAFORGE_OMNIROUTE_API_KEY`, `DATAFORGE_DATABRICKS_TOKEN`, `DATAFORGE_AZURE_OPENAI_API_KEY`,
`DATAFORGE_GEMINI_API_KEY`, `DATAFORGE_OPENROUTER_API_KEY`, `DATAFORGE_OLLAMA_API_KEY`,
`DATAFORGE_LM_STUDIO_API_KEY` or `DATAFORGE_CUSTOM_API_KEY`. Existing explicitly configured
environment references (including `OMNIROUTE_API_KEY`) remain compatible and read-only.
**Connect for this session** keeps the existing isolated behavior and never changes the
environment. The separate **Set environment variable** action explicitly changes only the
app's process environment. Clearing session credentials does not remove environment values;
restart the app to discard values entered with this action.

Adapters use the active session manager through a context-local scope. CLI/MCP deterministic
queries are offline; explicit provider/AI operations require approved launch references,
exact recipient origins and independent network/privacy grants. CLI supports hidden input
for the current invocation; MCP accepts reference names only. Its runtime bindings are scoped
to workspace/profile and invalidated after profile edits. Session overrides remain separate;
process-environment values are shared by the owning app process.
Pass session managers explicitly in process; never put session credentials in a process or
child environment. Never serialize a manager or credentials into job journals. Session secrets
must not be put in globally cached objects. Disconnect drops session references; launch
environment secrets remain available for the process lifetime.

Known runtime secrets and common credential patterns are redacted from provider responses,
persisted AI records and structured application logs. Raw transport errors and validation
input are not shown by connection controls. Provider requests keep their sent credential
transiently through response redaction, so rotation during a request does not expose the old
value in saved output; that copy is not placed in session state. Source originals remain exact evidence: if an
imported source itself contains credentials, that original and source exports/backups still
contain them. Remove secrets from source before importing. Redaction is defense in depth,
not a guarantee that arbitrary encoded secrets can be recognized.

Memory is not a secure enclave: privileged local processes, memory dumps and launch
environment inspection may expose credentials. Python cannot guarantee memory zeroization.
The UI is a local single-user application without authentication; do not expose it on an
untrusted network. Browser sessions isolate session overrides; the optional environment action
shares its value across the process. Shared workspace data
requires application-level access controls before a multi-user deployment.

## Project AI disclosure and revocation

[Project analysis](AI_ANALYSIS.md) is a run-level opt-in. A complete file transmitted through
multiple parts still counts as complete-source disclosure for remote routes. Selecting a
dbt member expands to its disclosed admitted project closure, including configuration,
macros and supplied artifacts. Relevant definition context stays within that pinned scope.
Project extraction transmits exact original source parts/context; do not assume the manual
assistance redaction step sanitizes those parts. Remove secrets before import or withhold
source/network permission. Loopback gateways may forward requests upstream.

Each physical extraction/completion/consolidation/retry checks current source, privacy,
route/credential authorization, cancellation and run limits. Job journals omit source,
session keys and full bodies. Minimal validated evidence persists separately from optional
full request/response captures, which have their own size/retention limits and retained-copy
redaction. Full-envelope token fitting includes instructions/schema/context/framing.
An explicit profile source-character restriction still applies; model token capacity does
not grant broader disclosure. Preview, settings reads, browsing and export start no provider
work. A lost response may already have incurred usage; reopening never starts paid work.

## Automatic AI allowance boundaries

Model-limit discovery is explicit and stores allowlisted capacity metadata bound to
recipient/model/auth/reference identity. Metadata refresh alone preserves runtime
credentials; changed capacity values change execution identity. Saved Custom limits remain.
Automatic calculation and offline preview send no source, make no token-count API calls
and grant no network/full-source permissions. The pinned output share/exact overrides
must fit real model capacity. Legacy profiles require an explicit choice of token capacity
or a retained character disclosure limit. Unknown-outcome retries require configured opt-in
or explicit acknowledgement; compatible resume retains cumulative reservations.

The persisted workspace `max_context_chars` and `llm_chunk_chars` support manual assistance
chunk previews. They are not project file-packing caps. Protocol 5 checks the profile's
`source_limit_policy`/`source_disclosure_chars` when explicitly configured, plus the full
request's token allowance. Changing a legacy workspace character setting alone does not
limit an exact-source project request; review the actual project disclosure and profile.
