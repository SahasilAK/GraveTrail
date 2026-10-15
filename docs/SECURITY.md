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
Back up the entire data home while the application is stopped; restore together with compatible code.

HTML exports encode embedded JSON and render names/code through textContent. HTML tables escape
content. Source text uses Streamlit code widgets. CSV exports escape formula-leading values.
The graph has no CDN dependency and sends no telemetry.

LLM requests are optional. External transmission is disabled by default, full-source remote
transmission has a separate gate, contexts/retries/responses are bounded, and likely secrets
are redacted. Credentials are environment references, never key values in DuckDB or exports.
Redirects and ambient proxy credentials are disabled. A loopback gateway can forward traffic;
the operator controls its trust. Malformed, invented or cross-statement claims are quarantined.
Minimal merged evidence persists; full AI interaction bodies are opt-in and subject to retention.

Imported source itself may contain secrets. The local inventory intentionally preserves it;
protect the storage directory using OS access controls and encryption where needed. Redaction
is best effort. Do not expose storage or exported code to untrusted users.
