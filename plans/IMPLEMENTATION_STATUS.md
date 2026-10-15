# DataForge implementation status

Updated: 2026-10-15. Specification fully read (1,597 lines).

## Current stage
Core workflows implemented; final packaging/docs/benchmark in progress. Repository initially contained only docs,
README, LICENSE and git configuration. User's existing `.gitignore` change preserved.
Python 3.11 environment installed: Streamlit 1.66.0, DuckDB 1.5.6, SQLGlot 30.23.0.

## Completed and tested backend groups
- Specification review, architecture, design direction, AGENTS and implementation plan.
- Secure ZIP/browser/allowed-root directory ingestion, original blobs, duplicate hashes,
  encodings, size/count/ratio budgets, workspace settings and inventory persistence.
- SQL AST operations, CTE/subquery scopes, direct columns, wildcards and parse diagnostics.
- SAS DATA/procedure rules, static macros, library maps and unresolved dynamic warnings.
- CSV streaming metadata; never evaluates data values as instructions.
- Transactional analysis runs and snapshots, hash-based incremental cache, conservative
  cross-file resolution, explicit operation memberships and stored direct column usages.
- Cycle-safe graph traversal, evidence-preserving temporary contraction, logical ordering.
- Validation: 27 tests pass, including all required deterministic fixture scenarios; the
  invalid-LLM scenario awaits the provider slice. Restart and changed-source replacement tested.

## In progress
- Final hardening, parser edge cases, benchmark, packaging and required documentation.

## Provider slice
- Profile UI and HTTP adapters for OpenAI-compatible services, Anthropic, Ollama, Gemini,
  Azure OpenAI and Databricks; manual models, discovery, connection checks and task routing.
- Focused AI assistance in Builder, versioned prompts/schema/hash, env-only credentials,
  privacy/context gates, redaction, retention, bounded retries and recipient-host fallback.
- Strict evidence validation/quarantine; explicit inferred merge with hash-based invalidation.
- 43 tests pass and Ruff clean before provider UI regression expansion. Live provider calls
  have not been verified; protocol tests use HTTPX MockTransport.

## UI / export verification
- Multipage Streamlit shell, dashboard, ZIP/folder/allowed-root Builder, filtered inventory,
  analysis/rebuild/validation controls and original source viewer implemented.
- Explorer: exact selection, upstream/downstream trees, combined focused graph, depth/node
  limits, temporary collapse, interactive edge/node evidence, path and source exports.
- Column page: direct-reference metrics, filters/grouping, evidence and CSV/JSON/HTML.
- Tools: literal code search, data dictionary, impact analysis, run comparison.
- Settings: parsing, workspace metadata, limits, graph, privacy. Provider UI is next.
- Standalone HTML graph embeds all JS/CSS/data; source bundles preserve original bytes.
- 32 tests pass (including AppTest all pages and graph JS syntax); Ruff clean; health 200.
- Actual browser: imported 7-file host directory, generated 9 assets / 7 dependencies,
  searched summary, selected an edge and verified its two intermediate SAS evidence records.
- Browser found a JS newline escaping defect; regression added and fixed before commit.

## Pending
- Clean install/package validation, final benchmark, complete required documentation,
  browser ZIP/export/column workflow and folder knowledge synchronization.

## Hardening / independent review
- Added transactional schema migration v2 to pin statement content hashes; versioned original
  views and downloads remain accurate after reimport. Immutable blob snapshot parsing also
  prevents concurrent-import cache poisoning; newer files remain pending.
- Fixed unused CTE dependencies, macro conditional false positives, DATALINES payload parsing,
  unsupported SAS name literal guessing and quoted dotted SQL identifier collisions.
- Bound CSV width/record resources and caught header failures per file; stopped imports after
  total-byte exhaustion; tested symlink ZIPs and expansion bombs.
- Bound AI source/target claims within one statement/block; retained merged claims beyond AI
  interaction retention while pruning context bodies. AI relationships remain inferred.
- 56 tests pass; Ruff clean. Read-only independent review findings and fixes: docs/REVIEW.md.
- Parser cache version bumped to 2 so prior analyses do not reuse pre-fix parser output.

## Decisions / handoff
See MASTER_PLAN and ARCHITECTURE_DECISIONS. Run `.venv\Scripts\python.exe -m pytest`.
Local runtime path `.dataforge/`. No LLM credentials detected or needed for core features.
Next concrete action: finish hardening and review, benchmark, clean install, browser ZIP/export
and column workflows, required docs and folder knowledge; commit each tested group.
Commit policy (user steering): commit each feature/group only after its tests pass.
