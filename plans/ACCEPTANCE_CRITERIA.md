# Acceptance criteria

- Import nested ZIP, browser directory and host directory restricted to allowed roots.
- Preserve original bytes, hashes, decoded code, diagnostics and per-workspace inventory.
- Analyze supported SQL/SAS deterministically and retain exact statement evidence.
- Demonstrate all eight specification fixture scenarios with automated assertions.
- Resolve across files conservatively; collapse temporary nodes without losing evidence.
- Search ambiguous names using an explicit exact asset selection.
- Traverse both directions, detect cycles, inspect code and export offline HTML/CSV/JSON/ZIP.
- Direct column references respect scope, aliases, ambiguity and wildcard uncertainty.
- Persist profiles without keys, enforce privacy, validate/quarantine LLM output.
- Reopen workspaces; incrementally skip unchanged parses and replace stale relationships.
- Run full tests, lint, health and actual UI; document limits and resume instructions honestly.


## Additional agent integration feature

See [AGENT_ACCEPTANCE.md](AGENT_ACCEPTANCE.md) for the feature-specific 15-point verification
matrix and explicit storage/authentication/parser limitations. CLI and MCP are mandatory;
REST remains optional and omitted. Existing human-first workflows remain unchanged.
