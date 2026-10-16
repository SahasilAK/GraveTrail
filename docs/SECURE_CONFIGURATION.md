# Secure runtime configuration

Credentials are retained only for the active runtime and are not saved in application files
or databases. They may need to be re-entered when the application restarts.

Settings → LLM providers supports a masked credential input, session connection and clear
action. Provider configuration is saved only on **Save provider profile**; this explicitly
stores nonsecret preferences and the environment variable name, never its value. URLs with
userinfo, query parameters or fragments are rejected. Keep sensitive endpoint identifiers
out of saved profiles. Newly entered credential names must start with `DATAFORGE_`.

Use `DATAFORGE_OPENAI_API_KEY`, `DATAFORGE_ANTHROPIC_API_KEY`,
`DATAFORGE_OMNIROUTE_API_KEY`, `DATAFORGE_DATABRICKS_TOKEN`, `DATAFORGE_AZURE_OPENAI_API_KEY`,
`DATAFORGE_GEMINI_API_KEY`, `DATAFORGE_OPENROUTER_API_KEY`, `DATAFORGE_OLLAMA_API_KEY`,
`DATAFORGE_LM_STUDIO_API_KEY` or `DATAFORGE_CUSTOM_API_KEY`. Existing explicitly configured
environment references (including `OMNIROUTE_API_KEY`) remain compatible and read-only.
No operating-system or shared process environment variables are written by credential entry.

Adapters use the active session manager through a context-local scope. CLI/MCP use their
launch environment; current agent tools perform deterministic local analysis without an LLM.
New worker integrations must explicitly pass a session manager or construct a scoped child
environment. Never serialize a manager or credentials into job journals. Session secrets
must not be put in globally cached objects. Disconnect drops session references; launch
environment secrets remain available until removed from the launching environment.

Known runtime secrets and common credential patterns are redacted from provider responses,
persisted AI records and structured application logs. Raw transport errors and validation
input are not shown by connection controls. Source originals remain exact evidence: if an
imported source itself contains credentials, that original and source exports/backups still
contain them. Remove secrets from source before importing. Redaction is defense in depth,
not a guarantee that arbitrary encoded secrets can be recognized.

Memory is not a secure enclave: privileged local processes, memory dumps and launch
environment inspection may expose credentials. Python cannot guarantee memory zeroization.
The UI is a local single-user application without authentication; do not expose it on an
untrusted network. Browser sessions isolate entered credentials, but shared workspace data
requires application-level access controls before a multi-user deployment.
