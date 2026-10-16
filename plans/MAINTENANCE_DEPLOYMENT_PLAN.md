# Maintenance and Deployment Implementation Plan

**Goal:** Extend the existing application with safe cleanup, isolated runtime credentials,
reliable installations and verified release tooling.

**Architecture:** Keep policy and operations in shared Python services. UI, CLI and MCP
delegate to those services. Package the existing UI and assets with the same domain code.

**Tech Stack:** Python 3.11+, Streamlit, DuckDB, Typer, MCP, Docker, PyInstaller.

**Spec:** docs/prompts/FEATURE_MAINTENANCE_AND_DEPLOYMENT.md

## Constraints and review focus

- Preserve user data, master prompt and unrelated edits; test destructive work in isolated homes.
- Secrets stay in session memory or read-only launch environment; never mutate global environment.
- Cleanup must revalidate previews, protect active jobs and shared blobs, and reject redirected paths.
- Database row sizes are logical estimates; deletion does not promise physical space reclamation.
- Installed wheels and frozen apps must locate all pages, prompts and assets outside the checkout.
- Backups require exclusive ownership, bounded safe restore and integrity validation.
- Build inputs must exclude runtime homes, secrets and developer data; cross-platform claims need runners.

## Vertical slices

- [x] 1. Runtime connections: failing isolation/redaction tests; manager, adapters and masked UI;
  regression suite and running Settings verification; commit.
- [x] 2. Cleanup: failing dry-run, dependency, active-job, shared-blob, path and restore tests;
  shared preview/apply/maintenance services, UI, CLI and read-only MCP; tests/UI; commit.
- [x] 3. Python/Docker: failing installed asset/launcher tests; package UI, entry points,
  locked container and Compose; clean install, CLI/MCP/UI and persistent-volume smoke; commit.
- [x] 4. Release: failing manifest/checksum tests; cross-platform build toolkit, host executable,
  tagged CI; run actual artifact smoke tests; commit.
- [x] 5. Documentation/integration: setup guide, README, architecture/security/knowledge;
  full pytest/Ruff, supplied ZIPs and running UI; record evidence and honest limits; commit.

## Storage audit

DuckDB migrations 1–4 own workspace settings/inventory, current graph/evidence, snapshots,
LLM records/profiles and recoverable history/staging. `blobs/<sha256>` is immutable and
shared; retained statement hashes and run snapshots also reference old versions. `parse_cache`
is global, not workspace-owned. Runtime `agent/jobs` journals and `agent/results` exports are
separate files. Repository KNOWLEDGE.md files are maintained source documentation, never cleanup targets.
Existing temporary cleanup is recoverable and bounded; reuse it. No embedding/AST disk index
or generated knowledge-base directory exists. Report absent categories honestly.

## Evidence ledger

- Initial checkout clean. Docker CLI/daemon 29.2.1 available (supersedes old external gate).
- Autonomous inline implementation authorized explicitly by user; no approval handoff needed.
- Runtime slice committed as b261056. Subsequent review reproduced escaped-key persistence,
  arbitrary environment-reference redaction, provider-validation/deletion race and incomplete
  restore; all pinned by regressions and fixed. Workspace-scoped callers cannot request
  a whole-home backup. Whole-request admission protects source reads through result commit.
- Fresh suite: 266 passed, one existing Windows symlink-privilege skip; Ruff and lock checks pass.
- Real Windows executable, clean wheel and clean sdist installations pass CLI SQL import,
  lineage query, stdio MCP and rendered HTTP/WebSocket UI. Linux Docker additionally passes
  non-root UID and volume persistence checks. Actual manifest verifies four artifacts under
  dist/release. Hosted Actions and native Linux/macOS executables remain unexecuted gates.
- 55 local documentation links and all 17 setup sections verified. Source ZIP and 500-file
  benchmark results are in .dataforge/verification/maintenance-*. Existing SAS limitations
  remain; OmniRoute discovery succeeds but auto completion returns ProviderError (no fixed route).
