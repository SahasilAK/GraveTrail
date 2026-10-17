# Security and privacy

Bind the local app to loopback; no authentication is provided for public/multi-user hosting.
Imported SQL/SAS/CSV and comments are untrusted data. They are never executed by Python,
DuckDB, SAS, a shell or the AI agent. Parameterized queries persist metadata; table names in
storage SQL come from fixed application-controlled lists.

ZIP inputs are read in memory into content-addressed storage without extraction to source
paths. Relative paths reject traversal, absolute/drive paths, control characters, Windows device
names and ADS syntax. Symlinks are rejected or not traversed. Limits cover file count, compressed
size, decompressed total, file size and entry compression ratio. File-specific errors are reported;
count-limit failures roll back inventory. Total budget stops further reads. Text encoding is
detected with diagnostics; binary input is rejected.

Host imports require resolved paths beneath `DATAFORGE_ALLOWED_ROOTS`. Browser folders use the
browser file-upload API and do not grant general host filesystem access. The app does not read
CSV values as code. CSV width/record/field limits prevent metadata allocation explosions.

Original bytes use SHA-256 names; inventory snapshots verify their hashes before parsing.
Statements pin source hashes. Analysis is transactional and rollback-tested. Source blobs are
retained across reimports and workspace deletion because they may support evidence elsewhere.
Explicit orphan-blob cleanup collects only unreferenced content; retained snapshots protect
hashes and recovery archives conservatively prevent collection. Explicit full application reset
can remove all managed originals after confirmation. Back up before destructive operations.

History recovery is limited to fixed analysis/import columns, at most 100 records per type and
25 MiB per archive. Workspace and archive identities are checked; resolved paths stay under the
data home, archive symlinks are rejected, and checksum/format/workspace validation precedes
transactional restore. Recovery checks detect accidental modification, not a malicious writer
who controls the database or can recompute hashes. Recovery bodies can contain configuration,
snapshots and diagnostics; protect them with the rest of the data home. Maintenance serializes
with analysis and preserves referenced records. Separate general cleanup operations are destructive
and do not have these recovery guarantees; a mandatory whole-home backup is their recovery path.

HTML exports encode embedded JSON and render names/code through textContent. HTML tables escape
content. Source text uses Streamlit code widgets. CSV exports escape formula-leading values.
The graph has no CDN dependency and sends no telemetry.

LLM requests are optional. External transmission is disabled by default, full-source remote
transmission has a separate gate, contexts/retries/responses are bounded, and likely secrets
are redacted. Profiles retain validated non-secret settings and environment variable references,
never entered key values. Masked runtime entry stays in the active browser session's
`RuntimeConnections`; adapters receive it through a context-local scope. Clearing runtime
credentials removes session entries, while explicitly named launch environment credentials
remain available. Fresh sessions/restarts require re-entry unless provisioned at launch.
Application-controlled names use `DATAFORGE_`; legacy explicitly named references are read-only.
Session entry never mutates the global process environment or writes a `.env` file.
Secret-bearing URL userinfo/query parameters are rejected. Provider-echoed known credentials
are redacted before retaining results; complete imported originals are intentionally unchanged.
Redirects and ambient proxy credentials are disabled. A loopback gateway can forward traffic;
the operator controls its trust. Malformed, invented or cross-statement claims are quarantined.
Minimal merged evidence persists; full AI interaction bodies are opt-in and subject to retention.
Diagnostic-review and manual request buttons pin the displayed source version through routing.
The queue omits stale pending-file diagnostics; a changed hash is refused before provider
transmission even if an import occurs after queue lookup. Opening a panel never sends code.
Only durable AI record IDs are kept in session state; source/response bodies stay in the
owning data-home tables under the configured retention policy. Session credential managers hold
secrets in memory and are not a guarantee of forensic memory erasure. Privileged local processes
may inspect process memory or launch environment. Clear/restart the appropriate process and
rotate credentials when necessary; session isolation is not multi-user authentication.

Imported source itself may contain secrets. The local inventory intentionally preserves it;
protect the storage directory using OS access controls and encryption where needed. Redaction
is best effort. Do not expose storage or exported code to untrusted users.

Storage selection is constrained to explicit startup configuration, with no free-text host-path
input. Both app bootstrap and the switch callback validate the selected resolved directory.
A target store opens before session controls reset; failures retain the active workspace.
This local filesystem allowlist is operator configuration, not an authentication boundary for
untrusted users or a defense against a local account that can mutate configured directories.


## Agent access

CLI/MCP launches are read-only unless explicitly authorized with --allow-write; per-workspace
settings may revoke writes, all access or source retrieval. Imports require startup-allowed
roots. Tools cannot execute arbitrary commands/SQL or inspect credential values. Explicit
AI requests additionally require independent outbound-network, exact recipient-origin,
approved credential-reference, source and workspace privacy authorization. Configuration
and application mutations have separate startup grants; MCP cannot grant itself authority.
Queries are workspace scoped, paged and character limited; ambiguity is explicit. Mutations
are audited without source/arguments/credentials. HTTP additionally requires a named environment
bearer credential and explicit workspace IDs. Externally bound deployments require a TLS
reverse proxy and network rules blocking direct plaintext backend access. These application
controls assume the OS user/data-home administrator is trusted. See MCP_INTEGRATION.md for
pre-provisioned-auth and single-owner storage limits.

## Cleanup, backup and distribution

Cleanup uses fixed category/table lists, parameterized predicates and resolved managed paths.
Previews are bound to current rows and files and must be refreshed after changes. Typed scope
confirmation and workspace/startup policy apply independently of preview possession. Active
analysis, jobs and provider requests block unsafe removal. Workspace source/AI deletion
invalidates the entire graph/history. Shared parser cache and original blobs are separate
cleanup scopes; inventory deletion alone is not a secure erasure promise.

The UI exposes shared cache/orphan cleanup and full runtime reset. CLI cleanup is scoped to
authorized workspaces, and MCP exposes only cleanup inspection/previews. Full runtime reset
preserves schema, backups, installed code, documentation and unrecognized files. Symlink,
Windows reparse point and hard-link redirects in managed cleanup paths are rejected. These
checks assume a trusted local administrator; they do not defend against an account able to
race filesystem changes or modify the database outside application interfaces.

Backup creates a separate DuckDB snapshot and managed-runtime archive, capped at 512 MiB and
50,000 files. Restore checks paths, file bounds, SHA-256 values and schema before publishing
into a new nonexistent directory. No in-place restore or arbitrary ZIP extraction is exposed.
Hashes detect accidental changes; they do not authenticate a writer who controls the archive
and can recompute its manifest. Backups are unencrypted and may include sensitive source,
history, non-secret provider settings and opted-in AI content. Store them with appropriate
OS permissions, encryption and retention controls. Never copy an actively owned DuckDB file.

Build subprocesses use an environment allowlist; package/image inputs exclude runtime homes,
DuckDB files and common secret files. Credentials must be injected only at runtime. Docker
runs as UID 10001, and Compose restricts the UI host port to loopback. Host import mounts
should be read-only and data mounts scoped to a dedicated home. Docker administrators and
local data-home administrators can access its contents. Artifact manifests/checksums are not
code signing; native code signing/notarization and a multi-user auth layer are not supplied.
See [setup and deployment](SETUP_AND_DEPLOYMENT.md) for actual launch/recovery commands.
