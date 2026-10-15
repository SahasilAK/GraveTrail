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
