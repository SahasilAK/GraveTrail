# Troubleshooting

Start with the diagnostic shown by the failing operation and confirm the workspace,
data home and source revision. Preserve the home before attempting recovery. The
[technical troubleshooting reference](../TROUBLESHOOTING.md) covers parser/import
symptoms; the [setup reference](../SETUP_AND_DEPLOYMENT.md#14-troubleshooting) covers
installation, containers and packaged launchers.

## Application or storage problems

| Symptom | Next action |
| --- | --- |
| Dependency or launcher missing | From the repository root, run `uv sync --locked --extra dev`; use `uv run gravetrail-ui`. Confirm Python 3.11+. |
| Port 8501 already used | Stop the intended previous owner or use `gravetrail-ui --port 8502`. |
| Browser does not open | Open the loopback URL printed by the launcher and inspect terminal output. |
| `storage_busy` or DuckDB lock | Stop the process owning that exact home before starting a separate UI/CLI/MCP process. Do not delete database/WAL/lock files. |
| Unexpectedly empty assets after interrupted restart | Preserve the stopped home/WAL; see the [verified secondary-index recovery issue](../TROUBLESHOOTING.md#missing-assets-after-an-interrupted-process). |
| Previously analyzed workspace missing | Check the explicit home. Source and installed launchers can have different defaults; reopen the original home with `--home`. |
| Integrity or migration failure | Stop the owner, retain the failed home and sanitized logs, then restore a compatible backup into a new directory. |

Changing storage locations does not copy workspaces. Separate homes remain independent.
Do not delete a database to solve ownership or migration errors.

## Import and lineage problems

**Directory rejected:** configure an allowed host root before startup. Paths must resolve
beneath that root; a browser-folder upload does not grant general host filesystem access.
For CLI imports, grant `--allowed-root` explicitly.

**File skipped:** check selected extensions, import diagnostics, encoding, binary detection,
file limits and archive paths/ratios. Correct an intentional source copy and reimport rather
than relaxing path protections. CSV metadata does not create a dependency from a similar name.

**Missing or partial edges:** run analysis, review diagnostics and choose the correct SQL
dialect/folder mappings or SAS static configuration. Dynamic SQL, runtime macros and
execution-order-dependent behavior may remain unresolved. Rebuild after extraction changes;
do not replace uncertainty with invented relationships.

**Old source in the evidence panel:** the graph cites the original analyzed hash. A newer
import can still be pending. Analyze that revision to refresh facts; downloads attached to
older evidence correctly retain the older bytes.

**Graph seems incomplete:** select the exact schema/job asset, check direction, depth, node
limits and temporary-step collapsing. Expand tree branches as needed. For CLI/MCP, inspect
freshness, `complete`, boundaries and `next_cursor`; a larger depth does not replace pagination.
For the supplied fixture, use depth 30 and trace `pub.all_kpis` to all 16 sources.

**Column missing:** direct usage is not transitive transformation lineage. A wildcard without
a trusted declaration remains unknown; ambiguous unqualified columns remain diagnostics.
See [SQL parsing](../SQL_PARSING.md), [SAS parsing](../SAS_PARSING.md) and
the [user guide](../user-guide/index.md).

## Optional provider problems

**Credential missing:** enter the masked runtime key again or provision the exact launch
reference named by the profile, then restart. Clearing a session key does not remove a
launch variable. Saved profiles do not contain key values.

**Connection or model failure:** check the endpoint, model/deployment, authentication and
provider availability. Model-list membership does not prove that a route can complete a
request. Review network/privacy grants; a local gateway can forward remotely.

**Result quarantined:** grounding, schema or evidence validation failed and no inferred
relationship was added. Review the bounded source context and response rather than weakening
validation. Re-preview if the imported source changed. Deterministic analysis remains usable
without provider access. See [LLM integration](../LLM_INTEGRATION.md).

## Cleanup and recovery

If a preview expired, refresh it after jobs/data/settings changes and review the new scope.
Active operations block unsafe cleanup. General cleanup requires a whole-home backup; the
specialized history/staging journals are not general undo. Restore a whole-home archive only
into a new directory, validate it and restart with that explicit home.

Removing rows does not guarantee physical DuckDB shrinkage. Shared cache, retained originals,
history and backups have separate lifecycles. Use [data management](../DATA_MANAGEMENT.md)
to understand category dependencies before trying to reclaim disk space.

## Report an issue safely

Use the repository's
[bug report form](https://github.com/SahasilAK/GraveTrail/issues/new?template=bug_report.yml).
Include the application revision, Python/OS/install method, minimal sanitized input,
reproduction steps, expected/actual behavior and relevant diagnostic text. Distinguish
the data home from the source checkout without publishing private absolute paths.
Do not attach a live database, backup, original private ZIP or credential-bearing log.
Use [security reporting](https://github.com/SahasilAK/GraveTrail/blob/main/SECURITY.md)
for vulnerabilities.
