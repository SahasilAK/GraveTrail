# Secure runtime configuration

New profiles default to **This session only**. **Connect for this session** retains a key in
the session's `RuntimeConnections`, with no persistent secret writes or environment mutation.
Only the non-secret source reference is saved when selecting a session source for a profile.
Session memory lasts until disconnected/cleared or process exit; browser disconnection does
not guarantee immediate erasure. Python cannot promise forensic memory zeroization.

**Remember on this device** is explicit opt-in. Save the provider profile first, select that
profile and source, enter the masked key, then press **Save / replace saved key**. The input
clears on success or failure. Keys are kept **until deleted** in encrypted native OS storage;
profiles contain only opaque references and non-secret metadata. Saving a replacement creates
a new application-owned entry and removes the old one. A session override does not replace
the saved key. Merely opening settings never retrieves/decrypts saved keys; their availability
is checked on **Connect saved key for this session** or explicit provider use.

The approved backend is Python `keyring.backends.Windows.WinVaultKeyring`, explicitly set to
`CRED_PERSIST_LOCAL_MACHINE` (2): the current Windows user, this machine, across logons; never
the library's default enterprise/roaming persistence. Backend discovery, keyring configuration,
chained/plaintext/third-party/cloud stores and insecure fallbacks are not used. macOS Keychain
and Linux Secret Service are **not enabled** pending native verification of local-only storage.
On unsupported systems, locked stores or failures, choose **This session only** explicitly;
the app never silently selects another storage backend or credential source.

**Disconnect this session** disables the selected reference in that session, leaving any
saved entry intact. **Connect saved key for this session** explicitly reconnects it.
**Delete saved key** removes local storage and clears its binding. It does **not** revoke the
provider's API key: revoke or rotate it at the provider separately. There is no independent
application master password, nor immunity to malware or other software running as the same
OS user. Protect the OS account and device.

Saved references bind the canonical data-home path, workspace, profile ID, provider and full
endpoint path/authentication/API-version identity. A different recipient cannot reuse the key.
Delete the saved key before changing its recipient, then explicitly save a key for the new
endpoint. Session references also bind that identity. Existing profile-fingerprint invalidation
still clears service runtime connections after profile edits. **Environment reference (advanced)**
preserves legacy automation profiles, without importing their values into OS storage. Missing,
expired, locked, deleted or disconnected credentials never fall back to an environment value
with a reserved session/saved reference. Explicitly switch sources to use another credential.

Profile/workspace/application deletion removes only exact matching application-owned entries.
A deletion failure retains database metadata for retry (earlier entries in a multi-profile
cleanup may already be deleted). Failed saves attempt to remove only the newly created entry;
if cleanup also fails, the UI reports its opaque GraveTrail entry name for manual removal in
Windows Credential Manager. Native-store and database changes cannot be atomic: a crash or
database failure can leave an orphan entry or a missing binding; neither grants a fallback.
Do not manually delete a data home before deleting its saved keys; filesystem deletion alone
cannot clean native storage. Configuration transfers omit provider bindings. Full backups
contain references, never key values; restore clears saved bindings and requires explicit new
binding even if the restored files are later moved to the old path. Original-store entries
remain owned by the original profiles until deleted there.

Connections & AI → Providers & routing supports a masked credential input, session connection and clear
action. Provider configuration is saved only on **Save provider profile**; this explicitly
stores nonsecret preferences and the selected opaque credential/environment reference, never its value. URLs with
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
must not be put in globally cached objects. Disconnect drops session overrides and suppresses
the selected saved reference until explicitly reconnected. Environment variables themselves
remain in the owning process until removed or process exit.

Saved references do not automatically become available to CLI/MCP. A human must pass each exact
reference using `--allowed-credential-ref DATAFORGE_SAVED_...` on the CLI/MCP launch, alongside
the existing workspace, source, network, origin and privacy grants. Copy the non-secret saved
reference shown beside its UI controls. Settings listing hides unapproved references. Agents
cannot enumerate the OS vault, receive raw keys, save keys through tool arguments, or alter
their launch grants. Background work uses the initiating operation's grants; detached work
journals only opaque references and policy metadata. Saved values are resolved in request
scopes, never copied into `os.environ` or a process-global cache. Revoking source/network/
workspace/reference access still blocks subsequent provider disclosure.

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
