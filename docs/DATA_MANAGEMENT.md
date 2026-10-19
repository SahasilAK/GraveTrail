# Data management and cleanup

Open **Data management → Cleanup & recovery**. Counts and logical JSON row-size estimates
come from the current database. Categories overlap because dependency removals are included;
logical row sizes are not physically reclaimable DuckDB bytes. Managed file bytes are shown
separately. The integrity action also reports the actual database file size and missing or
invalid source blobs. No embedding index or runtime knowledge base is implemented.

Choose a category, optionally select source files or an unreferenced history run, then
**Preview cleanup**. Review every affected table and runtime file. Type the workspace name
to apply; shared cache/orphan cleanup requires `CLEAN SHARED DATA`, and full reset requires
`RESET GRAVETRAIL`. A changed database or file invalidates the preview. A successful full-home backup is mandatory before general cleanup and cannot be disabled. No operation runs simply by selecting a category.

| Operation | Effect |
| --- | --- |
| Sources | Remove selected/all inventory and raw content; invalidate the workspace graph, snapshots, AI records and recovery history that could retain dependent evidence. Other source inventory survives. |
| Lineage | Clear graph, statements, mappings, columns, diagnostics and analysis snapshots; retain originals and settings. |
| Columns | Clear direct-column usages; rebuild lineage to regenerate. |
| AI | Clear AI records and the graph/history that may contain inferred relationships; rebuild deterministic lineage afterwards. |
| History | Remove only terminal analysis/ingestion history unreferenced by active facts/inventory. Optional run ID selects one eligible analysis run. Existing recoverable history archiving remains available under Data management → History & staging. |
| Jobs | Remove terminal or heartbeat-expired journals/results for this workspace. Active jobs block maintenance. |
| Reset | Remove generated graph, analysis/AI/ingestion/recovery history and generated exports; retain imported files, provider preferences and workspace configuration. |
| Workspace | Remove all workspace-owned database records and recognized recovery/export/job/access files. |
| Cache | Clear the application-wide parser cache and Streamlit serializable data cache; retain inventories and lineage. Cached Store resources are retained to preserve database ownership. |
| Orphans | Remove content-addressed source blobs unreferenced by any workspace inventory, retained statement or analysis snapshot. If a database history recovery archive exists, conservatively retain all blobs until that history is removed. |
| Application | Clear all application tables except migration/schema definitions and recognized workspace runtime files, blobs and audit/access data. Preserve backups, unrecognized files, installed code, repository docs and build infrastructure. |

Source blobs are shared by hash. Removing inventory does not immediately delete shared
bytes. Old anonymous parser results can retain source-derived fragments until shared cache
cleanup. To remove unreferenced copies, clear shared cache, then inspect orphan blobs.
Runtime backups retain prior source data and must be managed separately. Application reset
does not recursively remove the data-home directory. Theme configuration is preserved because
the chosen data home may overlap a source checkout. Empty directories may remain.

New cleanup operations commit database changes transactionally before deleting files.
An interrupted filesystem phase can leave harmless unreferenced files; results list retained
files for investigation/retry. They cannot leave active database evidence pointing to removed
sources. Paths must stay inside the runtime home; symlinks, junctions and hardlinks are refused.
Queued/running jobs, analysis and provider requests block maintenance. New provider requests
cannot begin while maintenance owns the home. Corrupt journals fail closed.

Expired recovery staging cleanup is opt-in. It runs when the cleanup page is visited, removes
only eligible app-created `.tmp` files older than 24 hours (100 files/25 MB per visit), and
keeps recoverable database bytes. It is not a background scheduler. Project `KNOWLEDGE.md`,
`README.md`, `AGENTS.md`, prompts and architecture files are never targets.

## Backup, restore and maintenance

**Create runtime backup** creates a checksummed ZIP under `DATAFORGE_HOME/backups` and offers
a download. Database snapshots use DuckDB's database-copy operation under exclusive service
locks; the live Windows database file need not be read directly. Backups include the database,
blobs, recovery files and agent runtime files, up to 512 MB/50,000 files. Larger installations
need an offline filesystem backup after stopping the single database owner. Backups are not
encrypted; store them with the same care as private source code.

**Check integrity and storage** validates schema migration versions, orphan relationships and
source blob hashes. **Checkpoint database** flushes the WAL; physical shrinking is not
guaranteed. Rebuild lineage regenerates derived graph/index metadata using existing parsers.
There is no raw SQL or schema-drop control.

Restore verifies paths, checksums, file limits and schema before creating a new home. The UI
restores a selected managed ZIP into a generated sibling directory. CLI accepts an explicit
new destination. Existing directories are never overwritten. Stop the owner, retain the
old home, then launch with `DATAFORGE_HOME` pointing to the restored path. Schema migrations
are additive through version 5; old facts open without reanalysis. Version-4 backups
remain restorable and upgrade when opened. Column transformation tables participate in
integrity checks, backups and cleanup previews. **Columns** cleanup clears direct usages
and transformation coverage; analyze again to rebuild it.

## Automation

Workspace cleanup uses the same service through CLI. Save an exact preview first:

```sh
gravetrail --home /path/to/home --json --output preview.json cleanup lineage --workspace WORKSPACE_ID
gravetrail --home /path/to/home --json --allow-write cleanup lineage --workspace WORKSPACE_ID --no-dry-run --preview preview.json --confirm "Workspace name" --backup
gravetrail --home /path/to/home maintenance inspect
gravetrail --home /path/to/home --allow-write maintenance backup
gravetrail --allow-write maintenance restore backup.zip /new/home --confirm "RESTORE GRAVETRAIL"
```

Output files must be new. Source/columns/AI/history/jobs/reset/workspace categories use the
same preview/apply syntax; `workspace reset --workspace ID` aliases reset. Shared cleanup
stays in the local UI. CLI write permission, workspace policy and agent-access settings all
apply. MCP `inspect_cleanup` and `preview_cleanup` are read-only; no destructive MCP tool
is registered even with startup write permission. Stop other owners before using standalone
CLI against an active UI/MCP data home; DuckDB supports one owning process per home.

## Project AI facts and active runs

Project AI analysis stages candidates before replacing active facts. A cancelled/failed/stale run keeps the previous graph. Minimal accepted source/decision/provenance data supports compatible offline rebuilds; opt-in full provider bodies remain subject to history privacy/retention. Selected-source analysis must preserve compatible unselected accepted contributions. An incompatible context requires reanalysis rather than silently downgrading saved facts.

Project run/unit/claim/support tables participate in the shared storage lifecycle. Active publishing analysis blocks conflicting maintenance, including gaps between provider requests. Cleanup uses the existing category dependencies, previews and confirmations; removing supporting AI/source facts can invalidate dependent lineage/columns. Backups restore to a new home and preserve evidence. See [AI project analysis](AI_ANALYSIS.md) and [data model](DATA_MODEL.md).
