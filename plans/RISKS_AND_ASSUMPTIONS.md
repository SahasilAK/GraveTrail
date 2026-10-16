# Risks and assumptions

- Static lineage is not execution lineage: runtime SQL, SAS macro control flow and database
  state cannot be known. Report unsupported constructs; do not invent dependencies.
- SQL dialect defaults to generic SQLGlot; configure explicit dialects for vendor SQL.
- SAS WORK datasets have workspace scope because job/session boundaries are not supplied.
  Repeated writes expose a union of possible dependencies, not temporal execution semantics.
- Local single-user process; authentication/multi-user hosting requires deployment controls.
- A local source can contain secrets. External AI requires privacy configuration and an
  explicit assistance action. Redaction is best effort, never a confidentiality guarantee.
- Large inputs are bounded; defaults will be measured and documented. No CSV dataframe load.
- No live provider verification without an available endpoint/key; HTTP transport tests suffice
  for protocol coverage but cannot prove a provider account's model availability.


## Agent integration boundaries

- DuckDB permits one owning process per data home; simultaneous independent UI/CLI/MCP
  processes must use separate homes or explicitly release the existing owner.
- HTTP uses private pre-provisioned bearer credentials; operators provide TLS termination
  and block direct backend access. Multi-user OAuth and remote TLS deployment are unverified.
- OS access to a runtime home is a trusted administration boundary; application permissions
  do not isolate users who can directly read/edit its database or journals.
- Running jobs may complete after access revocation; crashed jobs become interrupted after
  30 seconds without heartbeat and require explicit retry. No automatic job cancellation.
- SAS sample PROC SQL FORMAT= modifiers are a preexisting unsupported syntax: 96 logical
  edges remain unextracted. Report diagnostics, never infer dependencies from fixture labels.
- Token measurements use character/4 estimates, not billing tokens or a universal guarantee.
