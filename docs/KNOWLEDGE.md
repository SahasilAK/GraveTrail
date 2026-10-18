# docs/

Human and agent operating guides. ARCHITECTURE and DATA_MODEL explain boundaries; parser/security/testing guides state verified coverage and limitations.

`TRANSFORMATION_LINEAGE.md` — dedicated page workflow, tested SQL/SAS subset, dependency
roles, bounded exports/queries and parser11/migration5 upgrade/recovery boundaries. Published
through mkdocs.yml; PERFORMANCE records the synthetic traversal measurements. CLI/MCP
references now enumerate100 executable routes and80 tools; UI has eleven destinations.

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
- `index.md` — Branded MkDocs landing page with “Nothing stays buried.” / “Every dependency leaves a trail.” hero; section indexes organize canonical references without duplication. Only mkdocs.yml nav and named assets are published; REVIEW/prompts/plans/knowledge stay excluded.
- `BUILD_AND_RELEASE.md` — Actual launcher/build options, native artifact contracts, Docker ownership/persistence, CI gates and dated tested/untested platform evidence.
- `SETUP_AND_DEPLOYMENT.md` — Main 17-part installation/operations reference: source/wheel, Docker, host bundles, builds, runtime credentials, CLI/MCP, storage/backup/restore, guarded cleanup, upgrades and limits.
- `DATA_MANAGEMENT.md` — Cleanup dependency matrix, confirmation/dry-run flow, guarded backup/restore and recoverable history/staging boundaries.
- `SECURE_CONFIGURATION.md` — Session credential lifecycle, namespaced read-only startup variables, legacy compatibility, redaction and trusted-host limits.
- `CLI_GUIDE.md` — Commands, jobs, scopes, import roots, exit codes, budgets and single-owner DuckDB workflow; paths XLSX artifact creation/download and explicit evidence/excerpt flags.
- `MCP_INTEGRATION.md` — Official SDK transports/tools/resources/prompts, Codex/Claude examples, private bearer auth and TLS-proxy boundary; XLSX dependency-path metadata and authorized chunk retrieval.
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
- `SAS_PARSING.md` — SAS static rules, PROC SQL modifiers/calculated aliases and parser9 quote-aware %LET expressions/stale-binding invalidation; exact evidence and runtime boundaries.
- `SECURITY.md` — Security and privacy. Maintained documentation; consult implementation status for verification boundaries.
- `SQL_PARSING.md` — AST lineage/direct usage and parser9 bounded PostgreSQL SQL procedure/Snowflake literal bodies, original enclosing evidence and explicit runtime/DDL-schema exclusions.
- `TESTING.md` — Tracked current acceptance matrix distinguishing source, dated Windows/Docker/OmniRoute passes and still-open native/hosted/offline-browser gates; commands and historical counts remain separate.
- `TROUBLESHOOTING.md` — Troubleshooting. Maintained documentation; consult implementation status for verification boundaries.
- `USER_GUIDE.md` — User guide including All graph, fullscreen/copy/focus/history, direction-scoped evidence and copyable used/unused column lists with conservative schema/wildcard limits.

Latest verification/accounting lives in plans/REQUIREMENT_MATRIX.md and IMPLEMENTATION_STATUS;
older numerical results in guides are historical. Parser9 extends literal SQL/SAS macro coverage; both ZIPs retain128 logical edges/seven layers/all16 sources and original bytes.

Maintenance/deployment guidance: `connections.py` isolates session keys; broad cleanup uses
preview/apply guards, while older history/staging helpers remain separately recoverable.
Shared parser cache/original blobs require explicit shared cleanup. Source/AI removal clears
the dependent workspace graph; full runtime reset preserves backups/unrecognized files/schema.
Backups restore only to a new home. Source and installed/frozen launcher default homes differ;
pass explicit homes and respect one DuckDB owner. Platform/build evidence lives in status.

- `CLI_MCP_CAPABILITIES.md` — Actual routes/tools for all46 IDs,36 implemented/10 policy-restricted, independent authority, source/artifact/retry/cleanup boundaries and acceptance links.

Public docs link to tracked contribution/testing/build guides. All KNOWLEDGE.md context maps are tracked for repository navigation; agent instructions and implementation records remain optional local context.

BUILD_AND_RELEASE.md now includes the manual Publish standalone release runbook: committed project+lock version, default branch, exact tag/source, platform assets, no-extra-secret Copilot/fallback, failed-publication handling and hosted acceptance limits.

Product prose and command examples use GraveTrail; BUILD_AND_RELEASE documents preserved legacy storage, imports, variables, commands, Compose identities. Repository, contribution and Pages links use SahasilAK/GraveTrail and /GraveTrail/. Native/archive/image examples use gravetrail.

Rebrand rescan aligns reset/restore phrases and sample installation paths, explicitly documents retained compatibility identifiers, and uses gravetrail-prefixed screenshot filenames.

CLI/MCP references enumerate all100 executable routes/29groups, root and command flags/positional arguments,80 tools with required/optional inputs,2 concrete resources/4templates including legacy aliases and1prompt. Documentation tests compare exact registrations/inputs, independently of the46-ID UI capability catalog. Launcher/build sibling flags and the UI exception to non-Streamlit CLI behavior are explicit.

The delivered eleven-destination UI and before/after action map are documented in USER_GUIDE.md. Sources imports, Analysis runs/diagnostics/history, Lineage switches Graph/Tree, Transformation lineage follows Columns, and four administration routes replace the old long Settings selector. All public onboarding/provider/cleanup guides use delivered labels. Homepage/styles share system typography, adaptive surfaces and immediate/reduced feedback with the app; three real fixture screenshots are refreshed.

Pages now offers exactly four named themes through a native header select: Porcelain, Celadon, Ink and Aubergine. Material retains preference persistence and first-paint behavior; the allowlisted themes.js enhances its native radios. Surface/action colors match the four new app presets (eighteen app choices total). CLI/MCP counts and the UI reference reflect eighteen presets.
