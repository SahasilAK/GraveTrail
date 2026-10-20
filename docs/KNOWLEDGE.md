# docs/

Human and agent operating guides. ARCHITECTURE and DATA_MODEL explain boundaries; parser/security/testing guides state verified coverage and limitations.

`TRANSFORMATION_LINEAGE.md` — dedicated page workflow, tested SQL/SAS subset, dependency
roles, bounded exports/queries and parser11/migration5 upgrade/recovery boundaries. Published
through mkdocs.yml; PERFORMANCE records the synthetic traversal measurements. CLI/MCP
references now enumerate103 executable routes and83 tools; UI has eleven destinations.

## Subfolders
- `overrides/` — [overrides/KNOWLEDGE.md](overrides/KNOWLEDGE.md): inject shared theme CSS into Material without app dependencies.
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
- `BUILD_AND_RELEASE.md` — Launcher/build options, Windows per-user installer lifecycle and signing setup/limitations, exact-or-bumped dynamic release versions, branch validation vs default-branch publication, integrity/source/trust gates, Docker behavior and dated platform evidence.
- `SETUP_AND_DEPLOYMENT.md` — Main 17-part installation/operations reference: source/wheel, Docker, host bundles, builds, runtime credentials, CLI/MCP, storage/backup/restore, guarded cleanup, upgrades and limits.
- `DATA_MANAGEMENT.md` — Cleanup dependency matrix, confirmation/dry-run flow, guarded backup/restore and recoverable history/staging boundaries.
- `SECURE_CONFIGURATION.md` — Endpoint-first setup, credentials/test/discovery before profile save, fetched/manual models, and session versus masked process-environment credentials; clearing, lifetime/sharing, legacy compatibility, redaction and trusted-host limits.
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

- `CLI_MCP_CAPABILITIES.md` — Actual routes/tools for all48 IDs,38 implemented/10 policy-restricted, independent authority, source/artifact/retry/cleanup boundaries and acceptance links.

Public docs link to tracked contribution/testing/build guides. All KNOWLEDGE.md context maps are tracked for repository navigation; agent instructions and implementation records remain optional local context.

BUILD_AND_RELEASE.md now includes the manual Publish standalone release runbook: committed project+lock version, default branch, exact tag/source, platform assets, no-extra-secret Copilot/fallback, failed-publication handling and hosted acceptance limits.

Product prose and command examples use GraveTrail; BUILD_AND_RELEASE documents preserved legacy storage, imports, variables, commands, Compose identities. Repository, contribution and Pages links use SahasilAK/GraveTrail and /GraveTrail/. Native/archive/image examples use gravetrail.

Rebrand rescan aligns reset/restore phrases and sample installation paths, explicitly documents retained compatibility identifiers, and uses gravetrail-prefixed screenshot filenames.

CLI/MCP references enumerate all103 executable routes/29groups, root and command flags/positional arguments,83 tools with required/optional inputs,2 concrete resources/4templates including legacy aliases and1prompt. Documentation tests compare exact registrations/inputs, independently of the48-ID UI capability catalog. Launcher/build sibling flags and the UI exception to non-Streamlit CLI behavior are explicit.

The delivered eleven-destination UI and before/after action map are documented in USER_GUIDE.md. Sources imports, Analysis runs/diagnostics/history, Lineage switches Graph/Tree, Transformation lineage follows Columns, and four administration routes replace the old long Settings selector. All public onboarding/provider/cleanup guides use delivered labels. Homepage/styles share system typography, adaptive surfaces and immediate/reduced feedback with the app; three real fixture screenshots are refreshed.

Pages now offers exactly four named themes through a native header select: Porcelain, Celadon, Ink and Aubergine. Material retains preference persistence and first-paint behavior; the allowlisted themes.js enhances its native radios. Surface/action colors match the four new app presets (eighteen app choices total). CLI/MCP counts and the UI reference reflect eighteen presets.

Graph image workflow/limits/privacy: USER_GUIDE.md; registered CLI flags and exclusive --output: CLI_GUIDE.md; export_graph SVG/PNG and chunk/capability contracts: MCP_INTEGRATION.md. BUILD_AND_RELEASE.md records source/wheel/Windows smoke evidence and unavailable platforms.

- `AI_ANALYSIS.md` — Explicit AI/hybrid project workflow, native Mermaid architecture, complete-source/context/run budgets, semantic acceptance, staged publication/reuse and unqualified live accuracy targets.

AI guides document selected capability provenance, combined/separate estimates, Automatic/Custom/Reset, explicit context remedy and continuation. Data model/management cover migration7 compact per-file/operation snapshots with v6 fallback. CLI/MCP exact references include nullable execution limits, resume and explicit unknown retry. AI_ANALYSIS includes the updated staging/publication Mermaid flow and primary design evidence.

AI_ANALYSIS/PROMPT_ENGINEERING document exact projection paging, conservative dialect limits, static PROC SQL, response cardinality, conditional root focus prompt hashes and lossless per-batch review continuation. CLI/MCP previews share the service; DATA_MODEL covers unit_spec/review progress in existing tables. Mermaid includes review checkpoints; TESTING distinguishes mock proof from live precision.

Homepage, onboarding, user and AI/provider guides make the default local/no-AI workflow prominent alongside optional hybrid coverage for complex projects. Project size alone does not require AI; validation and unresolved coverage remain explicit.

TESTING documents supplied banking archive manifest agreement, offline/live commands, scenario grouping and absent independent column gold. SQL/SAS guides cover parser13 typed constants and DML scope boundaries; AI_ANALYSIS records validator2 and parser-version continuation pins. Table agreement never becomes a live column-accuracy claim.
