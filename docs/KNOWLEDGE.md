# docs/

Human and agent operating guides. ARCHITECTURE and DATA_MODEL explain boundaries; parser/security/testing guides state verified coverage and limitations.

## Subfolders
- `getting-started/` — [getting-started/KNOWLEDGE.md](getting-started/KNOWLEDGE.md).
- `user-guide/` — [user-guide/KNOWLEDGE.md](user-guide/KNOWLEDGE.md).
- `integrations/` — [integrations/KNOWLEDGE.md](integrations/KNOWLEDGE.md).
- `architecture/` — [architecture/KNOWLEDGE.md](architecture/KNOWLEDGE.md).
- `deployment/` — [deployment/KNOWLEDGE.md](deployment/KNOWLEDGE.md).
- `development/` — [development/KNOWLEDGE.md](development/KNOWLEDGE.md).
- `troubleshooting/` — [troubleshooting/KNOWLEDGE.md](troubleshooting/KNOWLEDGE.md).
- `assets/` — [assets/KNOWLEDGE.md](assets/KNOWLEDGE.md).
- `prompts/` — [prompts/KNOWLEDGE.md](prompts/KNOWLEDGE.md).

## Files
- `index.md` — Branded MkDocs landing page; section indexes organize canonical references without duplication. Only mkdocs.yml nav and named assets are published; REVIEW/prompts/plans/knowledge stay excluded.
- `BUILD_AND_RELEASE.md` — Actual launcher/build options, native artifact contracts, Docker ownership/persistence, CI gates and dated tested/untested platform evidence.
- `SETUP_AND_DEPLOYMENT.md` — Main 17-part installation/operations reference: source/wheel, Docker, host bundles, builds, runtime credentials, CLI/MCP, storage/backup/restore, guarded cleanup, upgrades and limits.
- `DATA_MANAGEMENT.md` — Cleanup dependency matrix, confirmation/dry-run flow, guarded backup/restore and recoverable history/staging boundaries.
- `SECURE_CONFIGURATION.md` — Session credential lifecycle, namespaced read-only startup variables, legacy compatibility, redaction and trusted-host limits.
- `CLI_GUIDE.md` — Commands, jobs, scopes, import roots, exit codes, response budgets and single-owner DuckDB workflow.
- `MCP_INTEGRATION.md` — Official SDK transports, tools/resources/prompts, current official Codex/Claude examples, private bearer auth and remote TLS-proxy boundary.
- `AGENT_WORKFLOWS.md` — Focused metadata/evidence/columns/impact/refresh workflows and honest SQL/SAS archive acceptance.
- `TOKEN_OPTIMIZATION.md` — Progressive disclosure, cursor/budget rules and reproducible representative character/token estimates.
- `ARCHITECTURE.md` — Architecture. Maintained documentation; consult implementation status for verification boundaries.
- `DATA_MODEL.md` — Data model. Maintained documentation; consult implementation status for verification boundaries.
- `EXTENDING_THE_APP.md` — Extending GraveTrail. Maintained documentation; consult implementation status for verification boundaries.
- `IMPLEMENTATION_GUIDE.md` — Implementation guide. Maintained documentation; consult implementation status for verification boundaries.
- `LINEAGE_ENGINE.md` — Lineage engine. Maintained documentation; consult implementation status for verification boundaries.
- `LLM_INTEGRATION.md` — Provider protocols, privacy, grounding and auto/best-reasoning evidence: existing fenced SAS processing passes; 2026-10-17 bounded SQL/SAS merge-refresh-reopen passes, preserving earlier gateway failures as history.
- `PERFORMANCE.md` — Performance. Maintained documentation; consult implementation status for verification boundaries.
- `PROMPT_ENGINEERING.md` — Prompt engineering. Maintained documentation; consult implementation status for verification boundaries.
- `REVIEW.md` — Implementation review, 2026-10-15. Maintained documentation; consult implementation status for verification boundaries.
- `SAS_PARSING.md` — SAS static rules, PROC SQL SELECT modifiers/calculated aliases, exact evidence, parser8 refresh and unresolved runtime boundaries.
- `SECURITY.md` — Security and privacy. Maintained documentation; consult implementation status for verification boundaries.
- `SQL_PARSING.md` — SQL parsing. Maintained documentation; consult implementation status for verification boundaries.
- `TESTING.md` — Testing. Maintained documentation; consult implementation status for verification boundaries.
- `TROUBLESHOOTING.md` — Troubleshooting. Maintained documentation; consult implementation status for verification boundaries.
- `USER_GUIDE.md` — User guide. Maintained documentation; consult implementation status for verification boundaries.

Latest verification/accounting lives in plans/REQUIREMENT_MATRIX.md and IMPLEMENTATION_STATUS;
older numerical results in guides are historical. Parser8 handles SAS PROC SQL modifiers with exact original evidence; both ZIPs now match128 logical edges/all16 sources.

Maintenance/deployment guidance: `connections.py` isolates session keys; broad cleanup uses
preview/apply guards, while older history/staging helpers remain separately recoverable.
Shared parser cache/original blobs require explicit shared cleanup. Source/AI removal clears
the dependent workspace graph; full runtime reset preserves backups/unrecognized files/schema.
Backups restore only to a new home. Source and installed/frozen launcher default homes differ;
pass explicit homes and respect one DuckDB owner. Platform/build evidence lives in status.

- `CLI_MCP_CAPABILITIES.md` — Actual routes/tools for all46 IDs,36 implemented/10 policy-restricted, independent authority, source/artifact/retry/cleanup boundaries and acceptance links.

Public docs link to tracked contribution/testing/build guides. All KNOWLEDGE.md context maps are tracked for repository navigation; agent instructions and implementation records remain optional local context.

BUILD_AND_RELEASE.md now includes the manual Publish standalone release runbook: committed project+lock version, default branch, exact tag/source, platform assets, no-extra-secret Copilot/fallback, failed-publication handling and hosted acceptance limits.

Product prose and command examples use GraveTrail; BUILD_AND_RELEASE documents preserved legacy storage, imports, variables, commands, Compose identities and unchanged repository links. Native/archive/image examples use gravetrail.

Rebrand rescan aligns reset/restore phrases and sample installation paths, explicitly documents retained compatibility identifiers, and uses gravetrail-prefixed screenshot filenames.
