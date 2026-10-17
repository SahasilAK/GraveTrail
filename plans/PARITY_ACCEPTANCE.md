# CLI/MCP UI parity acceptance — 2026-10-17

All nine source implementation slices are delivered. The checked capability inventory
accounts for all46 UI IDs:36 implemented equivalents and10 policy restrictions. No pending
catalog entry remains. The two open acceptance gates below remain unverified.

The [user matrix](../docs/CLI_MCP_CAPABILITIES.md) lists every actual CLI route and MCP tool;
the [keyed fixture](../tests/fixtures/parity_capabilities.json) is compared with every catalog
field, actual Typer command tree/help and actual MCP tool schemas. Tool annotations do not
grant permission. Tests invoke actual handlers, including denial of every registered
mutation/network tool under a read-only launch. Full machine-readable sanitized measurements
are in [PARITY_ACCEPTANCE.json](PARITY_ACCEPTANCE.json).

## Delivered source slices and commits

| Slice | Shared behavior, CLI/MCP and UI integration | Commit |
| --- | --- | --- |
| 1 | Versioned capability discovery, independent launch permissions, scoped authorization | 409e4de |
| 2 | Seven typed settings sections/schema/revisions, identity and safe configuration transfer | a0c48f6 |
| 3 | Profiles/routing, approved runtime references, model discovery/connection tests | 9956546 |
| 4 | Five grounded tasks, offline chunks/review, saved results/activity and explicit inferred merge | 21ebcc9 |
| 5 | Inventory/schema/dictionary/health, exact code matches, run/import history/evidence validation | ce3297d |
| 6 | Filtered graph/tree/path/step data, original versions and managed binary/report artifacts | ec5752f |
| 7 | Read-only maintenance discovery and guarded permitted local archive/cleanup/recovery | 12b010f |
| 8 | Shared14 themes/logging, runtime context and actual client setup/handler self-test | 0569f2f |
| Review fixes | Credential audiences, concurrency, exact evidence, cycle boundaries, input limits and UI identity | cea21cb |
| 9 | Actual46-ID catalog/fixture, cross-adapter acceptance runner, user matrix and updated evidence/maps | Final coverage/documentation commit |

## Verification

- Final `uv run pytest`: **320 passed,1 skipped in57.10s** (321 collected). The sole skip is
  the existing Windows symlink privilege test; other path/hardlink/traversal tests pass.
- `uv run ruff check .`, `git diff --check`, root CLI help and all catalog subgroup help pass.
  No application code changed after this full test run; the acceptance script additionally
  asserts the actual85 persistent fixture tables and seven reached layers.
- Actual official SDK stdio and authenticated streamable-HTTP clients pass. Tests exercise
  missing/bad token refusal, authorized structured results, read-only settings denial and
  oversized70KB request rejection with413 against the64KB admission limit. In-process
  handler self-test remains separately labeled; it is not claimed as external connectivity.
- Settings tests cover atomic invalid/stale patches, seven section schemas/defaults/ranges,
  process-only cap rejection, local administrator recovery and MCP non-escalation. Provider
  mocks cover approved origins/references, credential canaries, no process-environment
  mutation, profile-edit binding invalidation and immediate concurrent admission.
- All five tasks run through actual MCP handlers using fenced valid mocked responses.
  Existing grounding/advisory tests cover invented/ambiguous/source-changing evidence,
  quarantine, revocation and exact quotes. Added regressions reproduce source job changes
  after preview, credential fallback audiences and merge/refresh storage lock contention.
- Artifacts preserve original bytes/checksums, source versions, budgeted binary chunks,
  source revocation, workspace boundaries and exclusive CLI output. Combined tree traversal,
  exact graph/path source evidence and incomplete cycle boundaries have dedicated regressions.
- Destructive tests use isolated disposable homes. Shared general cleanup refuses backup
  opt-out; local history/staging apply requires a fresh preview, confirmation and full-home
  backup. Read-only MCP/settings/recovery reads do not trigger automatic cleanup.

## Supplied SQL and SAS ZIPs

`scripts/verify_parity.py` requires a new home. It invokes extension-specific CLI import,
cold/warm analysis, closes/reopens the owner, compares CLI/service/actual MCP lineage and
shared UI dictionary results, validates stored evidence, compares every original file byte
and SHA-256 against its ZIP, and runs a real SDK stdio catalog check. No imported source is
executed and no provider is contacted. Fresh successful run:

```powershell
uv run python scripts/verify_parity.py --home .dataforge/verification/parity-acceptance-v3 --output .dataforge/verification/parity-acceptance-v3.json
```

| Assertion | SQL | SAS |
| --- | ---: | ---: |
| Matching-extension scripts | 86 | 86 |
| Manifest persistent tables | 85 | 85 |
| Exact collapsed logical edges | 128 | 128 |
| Physical evidence edges | 128 | 144 |
| Additional temporary WORK datasets | 0 | 16 |
| Sources reached from pub.all_kpis | 16 | 16 |
| Reached ETL layers | 7 | 7 |
| Warm cached scripts | 86 | 86 |
| All original bytes/hashes and stored evidence | Pass | Pass |

SQL also retains seven isolated setup/schema registry names (92 total assets). SAS retains
31 known setup macro/LIBNAME/inline-data diagnostics, with no parse errors. Exact fixtures
are unchanged. These results establish static fixture correctness, not licensed SAS or
arbitrary imported-script runtime execution.

## Running UI and bounded live checks

The isolated8513 application displayed SQL and SAS `pub.all_kpis`, all16 source tables at
depth30, dictionary/code-search reports, original source and graph downloads, zero invalid
stored evidence, provider save/routing/clear, agent setup and settings/cleanup controls.
Switching equal asset labels between workspaces exposed a stale widget identity; the
workspace-scoped key fix passed AppTest and the real browser. A downloaded original SQL
file matched its fixture exactly:938 bytes, SHA-256
`0dc57ed7241a9589c257a4fee3cbf7367c76f2e2caf2049659a797f702aa9f20`.

An additional disposable8514 running UI used an in-process `httpx.MockTransport` for all
provider calls. The diagnostic review validated original line1, explicit merge reported
one inferred relationship and refreshed lineage. UI lineage cleanup created a mandatory
full-home backup before removing generated facts; UI restore created a new sibling home.
Independent reopen verified the exact97-byte original, three evidence edges including one
inferred claim, and the merged AI record. This was mock-provider UI acceptance, not a live
provider result. Existing AppTests additionally exercise masked runtime connect/clear,
saved result views, stale clicks and history/staging archive/recovery.

The separate bounded live check used only synthetic SQL/SAS, existing named
`OMNIROUTE_API_KEY`, `http://localhost:20128/v1` and **auto/best-reasoning**. Discovery915,
connection, SQL and SAS exact-quote validation, one inferred claim each, merge, refresh and
owner reopen all passed in33.8 seconds. No fixed model substitution, raw credential argument,
credential persistence, session environment mutation or validation/prompt relaxation occurred.
No repeated live retries were needed. Earlier dated gateway failures remain historical;
this bounded success does not promise future service availability.

## Policy restrictions preserved

Restricted IDs are **P02,S07,S09,W03,C01,C02,C03,C04,C05,M01**. Raw secret entry stays in
hidden local CLI input or the UI session; MCP binds only approved named launch references.
Privacy/access widening is local administrator work. MCP cannot grant itself authority or
switch its server home. Shared cache/orphan/application removal remains UI-only; all MCP
maintenance remains read-only, with unrestricted authority required for whole-home metadata.
Backup/download/checkpoint/restore and permitted history/staging mutation remain guarded
local operations. Whole-home restore always creates a new destination.

## Genuine blockers and unexecuted acceptance gates

1. **Standalone offline HTML browser interaction:** the running UI downloaded the HTML,
   and automated offline-assets/escaping/JavaScript tests pass. The browser automation tool
   rejects `file://` URLs and permits HTTP(S) only. No alternative route was used to bypass
   that policy. Opening and interacting with the downloaded standalone file outside the
   checkout remains unexecuted; the slice6 combined acceptance checkbox stays open.
2. **New distribution/platform acceptance:** no new wheel/frozen executable/Docker artifact
   was distributed or rebuilt for parity. Existing artifacts predate these commands and need
   rebuilding plus outside-checkout smoke tests. Native Linux/macOS and hosted release CI
   are unexecuted release gates. Source tests are not evidence for those targets.

No implementation blocker remains identified in the permitted source scope. User homes,
settings, source ZIPs, unrelated edits and MASTER_PROMPT were preserved. One DuckDB owner
per home was maintained; restored destinations were independently opened only as new homes.
